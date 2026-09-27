# M0 — Xác minh bài toán (A1, A2)

Mục tiêu: trả lời 2 giả định trước khi đầu tư tiếp.

- **A1**: nhập liệu và đối chiếu tay là điểm nghẽn ở khâu tiếp nhận hồ sơ vay tiêu dùng.
- **A2**: 4 giấy tờ (CCCD, đơn vay, HĐLĐ, sao kê 3 tháng) đại diện cho bộ hồ sơ phổ biến.

**Nguyên tắc:** chỉ hỏi về *quy trình*. Không xin, không chụp, không ghi lại bất kỳ dữ liệu khách hàng nào. Báo trước với người hướng dẫn thực tập rằng đây là phỏng vấn cho dự án cá nhân. Mỗi buổi 15–20 phút, 2–3 người (lý tưởng: 1 RM, 1 cán bộ thẩm định/hỗ trợ tín dụng).

## Câu hỏi

**Quy trình và thời gian (A1)**

1. Từ lúc nhận hồ sơ vay tiêu dùng đến lúc hồ sơ sẵn sàng thẩm định, anh/chị làm những bước nào?
2. Một bộ hồ sơ mất bao nhiêu phút cho riêng việc nhập thông tin và đối chiếu giấy tờ? Mỗi ngày bao nhiêu bộ?
3. Hiện có công cụ nào tự đọc giấy tờ không (eKYC đọc CCCD, OCR, LOS tự điền)? Nó bao phủ giấy tờ nào, còn phần nào vẫn làm tay?
4. Lần gần nhất phát hiện sai lệch giữa các giấy tờ là lỗi gì? Phát hiện ở bước nào, ai phát hiện?
5. Lỗi hay gặp nhất: tên, số CCCD, thu nhập khai cao, CCCD hết hạn, HĐLĐ hết hạn, hay loại khác?
6. Hồ sơ bị trả về bổ sung chiếm khoảng bao nhiêu phần? Lý do phổ biến nhất?

**Bộ giấy tờ (A2)**

7. Bộ hồ sơ vay tiêu dùng tín chấp điển hình gồm giấy tờ gì? Có khác theo sản phẩm (vay lương, thẻ, vay mua xe) không?
8. Chứng minh thu nhập thường là sao kê mấy tháng? Sao kê giấy, PDF từ app, hay ảnh chụp màn hình?
9. Có quy tắc nội bộ kiểu "thu nhập khai không vượt X% so với sao kê" hay "sao kê không cũ hơn N ngày" không? *(Chỉ hỏi có hay không và dạng quy tắc; không cần con số nội bộ nếu là thông tin mật.)*

**Mở**

10. Nếu có một công cụ tự đối chiếu và chỉ đưa hồ sơ có vấn đề cho anh/chị, điều gì khiến anh/chị *không* tin nó?

## Ghi chép (mỗi người một cột)

| | Người 1 | Người 2 | Người 3 |
|---|---|---|---|
| Vai trò | | | |
| Phút nhập + đối chiếu / bộ | | | |
| Số bộ / ngày | | | |
| Công cụ tự động đang có | | | |
| Lỗi hay gặp nhất | | | |
| Bộ giấy tờ điển hình | | | |
| Quy tắc đối chiếu nội bộ (dạng) | | | |
| Điều khiến không tin công cụ | | | |

## Cách ra quyết định

- **A1 đứng**: đối chiếu tay tốn ≥ vài phút/bộ và chưa có công cụ nào làm phần *đối chiếu chéo*. Giữ nguyên hướng.
- **A1 yếu**: ngân hàng đã có eKYC/OCR điền sẵn field. Khi đó phần trích xuất không còn là giá trị chính; kể lại dự án quanh **đối chiếu chéo + routing + đo escape rate**, là phần OCR không làm.
- **A2 lệch**: thay giấy tờ trong schema (mục 4) *trước* M2. Đổi schema sau khi có VLM thì phải chạy lại toàn bộ eval.
- Ghi kết quả vào mục 11 của spec (cột "Khi nào" → "Đã xác minh: …").
