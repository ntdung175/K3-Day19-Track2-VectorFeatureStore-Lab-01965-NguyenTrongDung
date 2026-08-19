# Reflection — Lab 19

**Tên:** _Nguyễn Trọng Dũng_
**Cohort:** _<A20-K3>_
**Path đã chạy:** `lite`

---

## Câu hỏi (≤ 200 chữ)

> Trên golden set 50 queries, mode nào thắng ở loại query nào (`exact` /
> `paraphrase` / `mixed`), và tại sao? Khi nào bạn **không** dùng hybrid
> (i.e. khi nào pure BM25 hoặc pure vector là lựa chọn đúng)?

Trên golden set, `exact` queries thường nghiêng về BM25 vì các từ khóa trong query
trùng trực tiếp với corpus. `paraphrase` queries lại phụ thuộc nhiều vào semantic
retrieval, nhưng với embedding mặc định tiếng Anh thì độ phủ tiếng Việt không
thật sự tốt, nên kết quả có thể thấp hơn kỳ vọng. `mixed` queries là nơi hybrid
thường thắng rõ nhất vì RRF kết hợp được tín hiệu keyword và semantic, giảm rủi
ro khi một trong hai phía bị thiếu signal.

Tôi không dùng hybrid khi bài toán yêu cầu latency cực thấp và truy vấn rất
đơn giản, ví dụ query gần như exact match và BM25 đã đủ tốt. Pure vector cũng
hợp lý khi query mang tính diễn giải mạnh, corpus nhỏ, và embedding model phù
hợp ngôn ngữ/ngữ cảnh hơn keyword search.

---

## Điều ngạc nhiên nhất khi làm lab này

Điều ngạc nhiên nhất là chỉ cần đổi cách benchmark và cache/warm-up hợp lý thì
P99 thay đổi rất mạnh, trong khi quality score gần như không đổi. Lab này cũng
cho thấy một model embedding “đúng concept nhưng sai ngôn ngữ” có thể làm
semantic search yếu đi rõ rệt dù pipeline vẫn chạy đúng.

---

## Bonus challenge

- [x] Đã làm bonus (xem `bonus/`)
- [ ] Pair work với: _<tên đồng đội nếu có>_
