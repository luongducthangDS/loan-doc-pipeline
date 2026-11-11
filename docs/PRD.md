# PRD: Loan Document Pipeline

Bản đầy đủ: [spec.md](spec.md) (mục 1–3, 9–11). File này là tóm tắt; khi lệch nhau thì `spec.md` thắng và phải sửa cho khớp.

## Bài toán
Tự động hoá khâu tiếp nhận hồ sơ vay tiêu dùng cá nhân: trích xuất thông tin từ 4 loại giấy tờ → đối chiếu chéo bằng rule tất định → route mỗi bộ vào auto-pass / human review / yêu cầu bổ sung. Câu hỏi chính: ở cấu hình nào pipeline tự xử lý được nhiều bộ nhất mà không để lọt bộ nào có sai lệch.

## Người dùng
Cán bộ tiếp nhận (upload, biết ngay thiếu/vướng gì), người rà soát (review queue: ảnh gốc cạnh field, lý do gắn cờ, sửa field), engineer (eval, chỉnh prompt/ngưỡng).

## Thước đo
Error escape rate (0 ca trên test, kèm cận trên 95 %) là chính; mismatch recall ≥ 95 % mỗi loại lỗi; field accuracy ≥ 95 % cho field quan trọng; automation rate là kết quả đầu ra; latency p95 < 60 s; chi phí đo và báo cáo.

## Không làm
Chấm điểm tín dụng / quyết định cho vay; phát hiện giả mạo, tra CIC, tích hợp core banking; fine-tune model; dữ liệu thật (kể cả đã ẩn danh).
