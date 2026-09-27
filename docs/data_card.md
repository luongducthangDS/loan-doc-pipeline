# Data card — bộ hồ sơ vay synthetic

## Cách sinh

1. **Profile là nguồn sự thật.** `datagen/truth.py` sinh một profile (họ tên, ngày sinh, CCCD, công ty, lương, tài khoản) rồi dựng 4 giấy tờ từ profile đó. Các giấy tờ nhất quán với nhau; ground truth có sẵn, không gán nhãn tay.
2. **Cài lỗi có chủ đích** lên một giấy tờ và ghi vào manifest. Nhãn **không** được tính bằng code của rule (vd lương TB lấy từ chính các khoản lương đã sinh), nên nếu rule sai thì eval bắt được thay vì nhãn "sai theo".
3. **Render** (`render.py`): 3 layout/loại khác nhau về thứ tự field, cách gọi nhãn, định dạng ngày/tiền, bố cục (dòng, bảng 2 cột, form điền tay chữ nghiêng) và font. Renderer ghi lại **đúng chuỗi đã in** cho từng field (`fields_raw`), dùng cho oracle extractor và để kiểm chuẩn hóa.
4. **Augmentation** (`augment.py`), mỗi bộ một mức: `clean` (gốc, JPEG q95) · `scan` (xoay ±3°, nhiễu, giảm tương phản, JPEG q60) · `photo` (nền bàn, méo phối cảnh, bóng đổ, mờ, JPEG q75).
5. **Seed cố định**: cùng seed → cùng nhãn, cùng raw. Ảnh có thể khác chút giữa máy vì font lấy từ hệ điều hành (Windows: Arial/Times/Tahoma; Linux: DejaVu).

## Chia tập

| Tập | Số bộ | Có lỗi | Layout | Dùng để |
|---|---|---|---|---|
| dev | 50 | 25 | A, B | chỉnh prompt, chọn ngưỡng, phân tích lỗi |
| test | 300 | 150 | A, B, **C (held-out)** | báo cáo, chạy 1 lần/phiên bản cuối |

CCCD chỉ có 1 mẫu thẻ (spec: thẻ căn cước mẫu mới để sau MVP) nên luôn là layout A. Với 150 bộ có lỗi và 0 ca lọt, cận trên 95% của escape rate ≈ 2,0%. Muốn tuyên bố ≤ 1% cần ≥ 300 bộ có lỗi.

Phân bố: ~50% bộ lỗi, mã lỗi chính chia **đều** (không bốc ngẫu nhiên, để recall mỗi mã không dựa trên 2–3 mẫu); ~10% bộ lỗi có thêm lỗi thứ 2 (không ghép với E8). ~50% bộ sạch, 1/3 trong đó có near-miss chia đều N1–N6.

## Nhãn

| Mã | Sai lệch | Cách cài | Rule | Route kỳ vọng |
|---|---|---|---|---|
| E1 | Tên trên đơn ≠ CCCD | bỏ chữ đệm / sai 1 dấu (vẫn còn dấu) / đảo chữ đệm và tên | R1 | REVIEW |
| E2 | Số CCCD trên đơn sai | đổi 1–2 chữ số | R2 | REVIEW |
| E3 | Ngày sinh trên đơn sai | lệch ±1–3 ngày hoặc ±1 tháng | R3 | REVIEW |
| E4 | Thu nhập khai quá cao | khai = lương TB × 1,25–1,8; một nửa số bộ có thêm khoản ghi có lớn không phải lương | R4 | REVIEW |
| E5 | CCCD hết hạn | ngày hết hạn trước ngày ký 10–400 ngày | R5 | REVIEW |
| E6 | TK nhận lương không khớp | đổi 1–2 chữ số trên đơn | R6 | REVIEW |
| E7 | HĐLĐ hết hiệu lực | HĐ xác định thời hạn, kết thúc trước ngày ký | R7 | REVIEW |
| E8 | Thiếu giấy tờ | bỏ CCCD, HĐLĐ hoặc sao kê | R0 | REQUEST_MORE |

| Near-miss | Biến thể hợp lệ, rule KHÔNG được gắn cờ |
|---|---|
| N1 | Tên trên đơn chỉ khác hoa/thường hoặc khoảng trắng |
| N2 | Đơn viết tên không dấu |
| N3 | Thu nhập khai cao hơn lương TB 2–7% (dưới tolerance 10%) |
| N4 | Sao kê có khoản ghi có lớn không phải lương, gồm chuyển khoản từ người **họ Lương** (thử regex) |
| N5 | CCCD hết hạn trong 1–30 ngày sau ngày ký |
| N6 | Lương tháng cuối về sau kỳ sao kê → chỉ 2 khoản lương |

Mọi bộ đều được sinh để qua R8 (sao kê kết thúc 1–20 ngày trước ngày ký, phủ đúng 3 tháng). R8 hiện chưa có mã lỗi riêng nên recall của nó chưa đo được.

Thu nhập thực nhận = lương gross × (1 − 10,5% bảo hiểm) × dao động ±3%, bỏ qua thuế TNCN.

## Manifest (`manifest.jsonl`, mỗi dòng một bộ)

```json
{"bundle_id": "test_0007", "split": "test", "seed": "42-test-7",
 "layout_ids": {"cccd": "A", "don_vay": "C", "hdld": "B", "sao_ke": "A"}, "augment": "photo", "bank": "...",
 "docs": [{"doc_id": "d1", "type": "cccd", "files": ["test_0007/cccd_front.jpg", "test_0007/cccd_back.jpg"],
           "fields_gt": {"ho_ten": "Nguyễn Văn An", "...": "..."},
           "fields_raw": {"ho_ten": {"raw": "NGUYỄN VĂN AN", "page": 1}, "...": "..."}}],
 "missing_docs": [], "injected_errors": [{"code": "E4", "doc_id": "d2", "field": "thu_nhap_thang"}],
 "near_miss": [], "expected_route": "REVIEW"}
```

`doc_id` cố định: d1 CCCD, d2 đơn vay, d3 HĐLĐ, d4 sao kê. Sao kê nhiều trang → `sao_ke_p1.jpg`, `sao_ke_p2.jpg`.

## Giới hạn (phải nêu khi báo cáo kết quả)

- **Dễ hơn giấy tờ thật**: chữ in máy, không con dấu, không chữ viết tay thật, không ảnh chân dung thật. Kết quả trên bộ này là cận trên; tập chụp thật (15–20 bộ in ra rồi chụp điện thoại) dùng để đo khoảng cách.
- **Rule tên hybrid không phân biệt được** tên gốc không dấu (vd "Phan Anh Nam") với bản bị thêm dấu sai. Bộ sinh không cài lỗi dấu cho tên gốc không dấu.
- Phân phối (tỉ lệ lỗi, mức lương, loại HĐLĐ) là giả định, không phản ánh danh mục thật của ngân hàng nào.
- Dev chỉ 25 bộ lỗi (~3 bộ/mã): recall theo mã trên dev chỉ để debug, không để báo cáo.
