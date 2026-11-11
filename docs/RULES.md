# Rules

## Bất biến
- Test set (300 bộ) đã chạy **một lần** với VLM thật; không chạy lại và không chỉnh gì dựa trên nó. Mọi tinh chỉnh làm trên dev.
- Oracle extractor phải luôn đạt escape 0 % và field accuracy 100 %; dưới 100 % là bug code, không phải lỗi model.
- Rule, chuẩn hoá, router là code tất định; model chỉ ở bước trích xuất.
- Chế độ agent: agent không được đưa giá trị field; đọc lại chỉ nâng low→high khi 2 lượt mới tự nhất quán và khớp các lượt đọc hợp lệ trước; field high bị khoá; `finish` bị từ chối nếu đòi AUTO_PASS khi router không ra AUTO_PASS, hoặc không REQUEST_MORE khi R0 fail. Workflow vẫn là chế độ mặc định.
- Mọi kiểu tiền xử lý mới phải thêm tag vào khoá cache VLM (khoá băm file gốc); khi tắt, khoá giữ nguyên.
- Chỉ dữ liệu synthetic.

## Quy ước
- Dùng `.venv/Scripts/python.exe` của repo (có streamlit); `python` mặc định trỏ venv DocuMind và skip `tests/test_app.py`.
- `main` đang deploy demo Streamlit; việc mới làm trên nhánh riêng.

## AI không bao giờ được
- Commit `gemini.md`, `.claude/`, `.env`.
- Ghi số đo vào `reports/runs.csv` cho lần chạy thử nghiệm ngoài quy trình.
- Push hoặc merge vào `main` khi user chưa yêu cầu.
