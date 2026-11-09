# Quality Engineering Portfolio

## Mục đích và phạm vi

Tài liệu này mô tả cách kiểm thử MVP tiếp nhận hồ sơ vay tiêu dùng và cung cấp các artefact thực hành cho
Quality Engineering. Đây là demo với dữ liệu synthetic và ngưỡng giả định; không phải hệ thống ngân hàng
thật hay chính sách tín dụng.

Phạm vi kiểm thử chính là trích xuất/chuẩn hóa, đối chiếu rule, routing hồ sơ, hàng đợi rà soát và lưu kết
luận vào SQLite. Không kiểm thử quyết định cấp tín dụng, tích hợp core banking hoặc dữ liệu khách hàng thật.

## Chiến lược kiểm thử theo rủi ro

Ưu tiên cao nhất là **không để hồ sơ có sai lệch đi qua nhánh `AUTO_PASS`**. Hồ sơ thiếu thông tin hoặc có
confidence thấp phải được giữ lại để rà soát; thao tác của reviewer phải được lưu nhất quán và có thể truy vết.

| Lớp | Mục tiêu | Công cụ / cách chạy |
|---|---|---|
| Unit / functional | Chuẩn hóa, rule R0–R8, router, generator và validation | pytest; `tests/test_normalize.py`, `tests/test_rules.py`, `tests/test_router.py`, `tests/test_datagen.py` |
| Integration | Pipeline với oracle, trace/evaluation và lưu kết quả review | pytest; `tests/test_pipeline.py`, `tests/test_app.py`, `tests/test_review.py` |
| UI | Hàng đợi, mở hồ sơ, chỉnh field, chọn kết luận và chuyển trạng thái | Streamlit AppTest; `tests/test_app.py` |
| Regression | Giữ lại lỗi đã phát hiện, đặc biệt lỗi có thể làm sai trạng thái review | pytest; `tests/test_review.py` và CI |
| Data / evaluation | Recall mã lỗi, escape rate, false review, field accuracy | `python -m loanpipe.evaluate`; test set đóng băng, chỉ chạy theo quy trình trong README |
| API | Chưa áp dụng: ứng dụng không công bố REST API | Không tạo Postman collection giả cho giao diện nội bộ của Streamlit |

CI hiện chạy `python -m pytest -q`, kiểm tra đường dẫn dữ liệu, rồi tạo dữ liệu dev không ảnh và chạy evaluation oracle. Điều này kiểm tra logic xác định mà không gọi model hay dùng credential bên ngoài.

## Test cases

| ID | Ưu tiên | Loại | Tiền điều kiện / bước chính | Kết quả mong đợi | Automation |
|---|---|---|---|---|---|
| QE-FUN-01 | P0 | Functional | Chạy oracle trên hồ sơ sạch | Hồ sơ chỉ được `AUTO_PASS` khi đủ field và mọi rule cần thiết pass | `tests/test_datagen.py`, `tests/test_pipeline.py` |
| QE-FUN-02 | P0 | Functional | Đưa hồ sơ có từng lỗi E1–E8 vào oracle | Mã lỗi tương ứng bị phát hiện; không hồ sơ lỗi nào bị auto-pass | `tests/test_datagen.py`, `tests/test_rules.py` |
| QE-FUN-03 | P1 | Functional | Dùng field thiếu/không đáng tin cậy trong pipeline | Kết quả là `REVIEW` hoặc `REQUEST_MORE`, không biến `unknown` thành pass | `tests/test_router.py`, `tests/test_pipeline.py` |
| QE-INT-01 | P1 | Integration/UI | Mở hồ sơ review, sửa field, nhập reviewer, chốt `valid` | Bản ghi SQLite chuyển sang `closed`, lưu reviewer/kết luận/edit và thời điểm đóng | `tests/test_app.py::test_review_flow` |
| QE-INT-02 | P1 | Integration/UI | Mở tất cả hồ sơ mẫu | Mỗi hồ sơ render không có exception; hồ sơ `AUTO_PASS` không nằm trong queue | `tests/test_app.py::test_every_sample_renders`, `test_review_flow` |
| QE-REG-01 | P1 | Regression | Gọi thao tác chốt với `bundle_id` chưa từng mở | Thao tác báo `LookupError`, không tạo/cập nhật bản ghi và không giả thành công | `tests/test_review.py::test_close_item_rejects_unknown_bundle` |
| QE-REG-02 | P1 | Regression | Chốt bản ghi đang mở với kết luận không hợp lệ | Báo `ValueError`; trạng thái vẫn `open`, chưa có `closed_at` | `tests/test_review.py::test_invalid_conclusion_does_not_close_item` |
| QE-MAN-01 | P2 | Manual UI | Mở `streamlit run app.py`, chọn một hồ sơ trong queue | Ảnh, field, lý do bị gắn cờ và nút chỉnh sửa khớp trace | Manual |
| QE-MAN-02 | P1 | Manual UI | Chỉnh field, chốt hồ sơ, tải lại trang / mở lại hồ sơ | Giá trị đã sửa và kết luận được lưu; không sửa hồ sơ khác | Manual; đối chiếu SQL bên dưới |
| QE-MAN-03 | P2 | Manual UI | Thử mở trực tiếp một hồ sơ `AUTO_PASS` bằng URL query param | Không cho nhầm hồ sơ tự duyệt vào hàng đợi cần reviewer | Manual |

`QE-FUN-01`–`03` mô tả hành vi mong đợi; chi tiết assertion được chia theo unit/integration test hiện hữu. Không nên báo cáo các dòng này như test API.

### Chạy kiểm thử

```powershell
python -m pytest tests/test_review.py tests/test_app.py -q
python -m pytest -q
```

`test_app.py` dùng Streamlit AppTest và các bộ mẫu đã commit; test review dùng SQLite tạm trong `tmp_path`, không đọc/ghi `data/review.sqlite` của người dùng.

## SQL kiểm tra dữ liệu review

Các truy vấn dưới đây chỉ đọc cơ sở dữ liệu local. Nếu chạy demo bằng biến `REVIEW_DB`, hãy thay đường dẫn cho đúng. Không chạy trên dữ liệu khách hàng thật.

```sql
-- Tóm tắt hàng đợi theo trạng thái và nhánh
SELECT route, status, COUNT(*) AS item_count
FROM review
GROUP BY route, status
ORDER BY route, status;

-- Hồ sơ đã đóng nhưng thiếu thông tin bắt buộc để audit
SELECT bundle_id, reviewer, conclusion, opened_at, closed_at
FROM review
WHERE status = 'closed'
  AND (reviewer IS NULL OR conclusion IS NULL OR closed_at IS NULL);

-- Thời gian xử lý (giây); hồ sơ chưa đóng sẽ có thời lượng NULL
SELECT bundle_id, status,
       CASE WHEN closed_at IS NOT NULL AND opened_at IS NOT NULL
            THEN ROUND(closed_at - opened_at, 2)
       END AS handling_seconds
FROM review
ORDER BY opened_at;
```

Kiểm tra trực tiếp bằng Python/SQLite:

```python
import sqlite3

con = sqlite3.connect("data/review.sqlite")
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT bundle_id, status, reviewer, conclusion, opened_at, closed_at FROM review"
).fetchall()
print([dict(row) for row in rows])
```

## Defect lifecycle: QE-REG-01

| Trường | Nội dung |
|---|---|
| Tiêu đề | Chốt một hồ sơ không tồn tại không báo lỗi |
| Severity / Priority | Medium / P1 — có thể tạo cảm giác thao tác review đã được ghi nhận trong khi không có bản ghi |
| Tiền điều kiện | Cơ sở dữ liệu review đã khởi tạo; `bundle_id` chưa được mở |
| Bước tái hiện | Gọi `close_item(con, "missing", "reviewer", "valid", {})` |
| Kết quả trước sửa | Hàm không báo lỗi dù câu `UPDATE` không cập nhật hàng nào |
| Kết quả mong đợi | Báo lỗi rõ ràng khi không tìm thấy hồ sơ; không trả về thành công giả |
| Trạng thái | Đã sửa: kiểm tra số hàng được cập nhật và ném `LookupError` nếu không có hồ sơ |
| Regression | `tests/test_review.py::test_close_item_rejects_unknown_bundle` |

Quy trình dùng cho defect khác: ghi build/commit và môi trường → bước tái hiện → actual/expected → severity/priority → evidence (trace/ảnh/SQL) → chuyển trạng thái Open → In Progress → Retest → Closed. Chỉ đóng defect sau khi retest đạt; nếu không tái hiện được thì ghi rõ môi trường và dữ liệu synthetic đã dùng.

## Giới hạn và bước tiếp theo

- Dự án hiện chưa có REST API. Nếu sau này thêm endpoint, cần xác định contract/schema, status code, lỗi validation, auth và idempotency trước khi tạo collection Postman/API automation.
- Thêm negative UI test cho reviewer bỏ trống, nhấn chốt lặp và điều hướng giữa hai hồ sơ nếu các luồng này được xác định là hành vi cần hỗ trợ.
- Khi thay rule hoặc prompt, chỉ tinh chỉnh trên dev; bảo toàn test set đóng băng và tuân theo giới hạn chạy test đã ghi trong README.
