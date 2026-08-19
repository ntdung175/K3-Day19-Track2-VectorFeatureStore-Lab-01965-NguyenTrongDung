from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

from feast import FeatureStore
from qdrant_client import QdrantClient, models
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.agent import TOPIC_HINTS
from app.embeddings import Embedder

ROOT = Path(__file__).resolve().parent.parent
MEMORY_COLLECTION = "bonus_hybrid_memory"
RRF_K = 60
WORD_RE = re.compile(r"[0-9A-Za-zÀ-ỹ_]+", re.UNICODE)


def _normalize(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def _chunk_text(text: str, max_words: int = 120) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end == len(words):
            break
        start = max(end - 20, start + 1)  # small overlap for semantic continuity
    return chunks


@dataclass
class MemoryHit:
    doc_id: str
    text: str
    score: float
    source: str


class HybridMemoryAgent:
    """Minimal memory POC that combines episodic vector memory and Feast features."""

    def __init__(self) -> None:
        self.embedder = Embedder()
        self.client = QdrantClient(":memory:")
        self.store = FeatureStore(repo_path=str(ROOT / "app" / "feast_repo"))
        self._recent_queries: dict[str, deque[tuple[datetime, str]]] = {}
        self._next_id = 0
        self._init_collection()

    def _init_collection(self) -> None:
        if MEMORY_COLLECTION in {c.name for c in self.client.get_collections().collections}:
            self.client.delete_collection(MEMORY_COLLECTION)
        self.client.create_collection(
            collection_name=MEMORY_COLLECTION,
            vectors_config=VectorParams(size=self.embedder.dim, distance=Distance.COSINE),
        )

    def _recent(self, user_id: str) -> deque[tuple[datetime, str]]:
        if user_id not in self._recent_queries:
            self._recent_queries[user_id] = deque(maxlen=128)
        return self._recent_queries[user_id]

    def _record_query(self, user_id: str, query: str) -> None:
        self._recent(user_id).append((datetime.now(timezone.utc), query))

    def _profile(self, user_id: str) -> dict[str, Any]:
        try:
            res = self.store.get_online_features(
                features=[
                    "user_profile_features:reading_speed_wpm",
                    "user_profile_features:preferred_language",
                    "user_profile_features:topic_affinity",
                    "query_velocity_features:queries_last_hour",
                    "query_velocity_features:distinct_topics_24h",
                ],
                entity_rows=[{"user_id": user_id}],
            ).to_dict()
            return {k: (v[0] if isinstance(v, list) and v else v) for k, v in res.items()}
        except Exception as exc:  # noqa: BLE001
            return {
                "reading_speed_wpm": 180,
                "preferred_language": "vi",
                "topic_affinity": "cloud",
                "queries_last_hour": 0,
                "distinct_topics_24h": 0,
                "_error": str(exc),
            }

    def _live_activity(self, user_id: str) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = [q for ts, q in self._recent(user_id) if ts >= cutoff]
        topic_counts = Counter()
        for q in recent:
            low = q.lower()
            for topic, hints in TOPIC_HINTS.items():
                if any(h in low for h in hints):
                    topic_counts[topic] += 1
        avg_len = (sum(len(_normalize(q)) for q in recent) / len(recent)) if recent else 0.0
        return {
            "live_queries_last_hour": len(recent),
            "live_topics": [t for t, _ in topic_counts.most_common(3)],
            "live_avg_query_len": round(avg_len, 1),
            "recent_queries": recent[-5:],
        }

    def _topic_boost(self, text: str, topic: str | None) -> float:
        if not topic:
            return 0.0
        low = text.lower()
        hints = TOPIC_HINTS.get(topic, [])
        return 0.05 if any(h in low for h in hints) else 0.0

    def remember(self, text: str, user_id: str = "u_001") -> None:
        """Add a new piece of episodic memory for this user."""
        chunks = _chunk_text(text)
        points: list[PointStruct] = []
        for idx, chunk in enumerate(chunks):
            vec = next(self.embedder.embed([chunk])).tolist()
            points.append(
                PointStruct(
                    id=self._next_id,
                    vector=vec,
                    payload={
                        "user_id": user_id,
                        "doc_id": f"mem_{self._next_id:06d}",
                        "chunk_index": idx,
                        "source": "episodic",
                        "text": chunk,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            )
            self._next_id += 1
        self.client.upsert(collection_name=MEMORY_COLLECTION, points=points)

    def _search_memories(self, query: str, user_id: str, topic: str | None, top_k: int = 3) -> list[MemoryHit]:
        q_vec = next(self.embedder.embed([query])).tolist()
        q_filter = models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
        )
        res = self.client.query_points(
            collection_name=MEMORY_COLLECTION,
            query=q_vec,
            query_filter=q_filter,
            limit=max(top_k * 4, 8),
        ).points
        if not res:
            return []

        sem_rank = {p.payload["doc_id"]: i + 1 for i, p in enumerate(res)}
        token_set = set(_normalize(query))
        lex_candidates = []
        for i, p in enumerate(res, start=1):
            text = str(p.payload.get("text", ""))
            overlap = len(token_set.intersection(_normalize(text)))
            lex_candidates.append((overlap, i, p))
        lex_candidates.sort(key=lambda x: (-x[0], x[1]))
        lex_rank = {
            p.payload["doc_id"]: i + 1
            for i, (overlap, _, p) in enumerate(lex_candidates)
            if overlap > 0
        }

        scored: list[tuple[float, MemoryHit]] = []
        for p in res:
            doc_id = str(p.payload["doc_id"])
            text = str(p.payload.get("text", ""))
            score = 1.0 / (RRF_K + sem_rank[doc_id])
            if doc_id in lex_rank:
                score += 1.0 / (RRF_K + lex_rank[doc_id])
            score += self._topic_boost(text, topic)
            scored.append(
                (
                    score,
                    MemoryHit(
                        doc_id=doc_id,
                        text=text,
                        score=score,
                        source=str(p.payload.get("source", "episodic")),
                    ),
                )
            )
        scored.sort(key=lambda x: -x[0])
        return [hit for _, hit in scored[:top_k]]

    def recall(self, query: str, user_id: str = "u_001") -> str:
        """Retrieve top-K memories + user profile features -> return assembled context."""
        self._record_query(user_id, query)
        profile = self._profile(user_id)
        live = self._live_activity(user_id)
        topic_affinity = profile.get("topic_affinity") or "cloud"
        memories = self._search_memories(query, user_id, topic_affinity, top_k=3)

        lines = [
            f"User: {user_id}",
            (
                "Profile: "
                f"language={profile.get('preferred_language', 'vi')}, "
                f"reading_speed={profile.get('reading_speed_wpm', 180)} wpm, "
                f"topic_affinity={topic_affinity}"
            ),
            (
                "Recent activity: "
                f"feast_queries_last_hour={profile.get('queries_last_hour', 0)}, "
                f"live_queries_last_hour={live['live_queries_last_hour']}, "
                f"live_topics={', '.join(live['live_topics']) or 'none'}"
            ),
            f"Question: {query}",
            "Top memories:",
        ]
        if memories:
            for i, mem in enumerate(memories, 1):
                snippet = mem.text[:180].replace("\n", " ")
                lines.append(f"{i}. [{mem.doc_id}] {snippet}")
        else:
            lines.append("1. No episodic memories matched yet.")

        lines.append("Live recent queries:")
        if live["recent_queries"]:
            for q in live["recent_queries"]:
                lines.append(f"- {q}")
        else:
            lines.append("- none")
        return "\n".join(lines)
