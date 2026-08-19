from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bonus.agent import HybridMemoryAgent


def load_corpus() -> list[dict]:
    docs: list[dict] = []
    with (ROOT / "data" / "corpus_vn.jsonl").open(encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


def get_doc(docs: list[dict], doc_id: str) -> dict:
    for doc in docs:
        if doc["doc_id"] == doc_id:
            return doc
    raise RuntimeError(f"no corpus doc matched doc_id={doc_id!r}")


def main() -> int:
    docs = load_corpus()
    agent = HybridMemoryAgent()

    # Seed the agent with actual corpus documents from the lab corpus.
    seed_docs = [
        get_doc(docs, "cloud_083"),
        get_doc(docs, "cloud_000"),
        get_doc(docs, "security_062"),
        get_doc(docs, "security_071"),
    ]
    for doc in seed_docs:
        agent.remember(f"{doc['title']}. {doc['text']}", user_id="u_001")

    queries = [
        "Tôi đã đọc gì về Kubernetes?",
        "Recommend đọc gì tiếp",
        "Tôi đang quan tâm gì gần đây?",
        "Tài liệu về tự động mở rộng hạ tầng?",
        "Cho tôi summary cloud security",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n=== Query {i} ===")
        print(query)
        print(agent.recall(query, user_id="u_001"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
