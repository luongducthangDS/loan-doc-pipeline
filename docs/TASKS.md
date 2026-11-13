# Tasks

Milestone gốc: [spec.md](spec.md) mục 12.

## Đã xong
- [x] M1 bộ sinh dữ liệu; M2 spike VLM (gate đạt, chọn Qwen3-VL-8B); M3 rule R0–R8 + router + eval; M4 review UI, test đóng băng chạy 1 lần, demo public
- [x] Deskew tuỳ chọn (07/11), chế độ agent + hàng rào (09/11, nhánh `agent-mode`)
- [x] Benchmark OCR vs VLM (12/11); Dockerfile + cổng mật khẩu `DEMO_PASSWORD` cho demo (12/11)
- [x] UI tổng quan + responsive, demo Render https://loan-doc-pipeline.onrender.com, ảnh chụp trong README (13/11)
- [x] Khung so sánh biến thể `loanpipe/compare.py` + `reports/comparison.{md,csv}` (13/11): gộp run theo cấu hình, paired diff route, mặc định chỉ so trên rules/thresholds hiện tại

## Tiếp theo (lần lượt từ trên xuống)
- [x] Adapter OCR (EasyOCR + anchor) chạy end-to-end qua rules/router thành B1: dev 50 bộ, escape 0/25, automation 8 %, field acc 72,3 %; phân biệt oracle-aligned và thêm vào comparison
- [ ] Chạy agent B5b trên dev với pool Gemini (Flash Lite 3.1/3.5 làm chính, các bản Flash 20 RPD làm dự phòng; tool calling native), VLM từ cache: đo nhánh, escape, lượt LLM/bộ, số bộ chốt trước LLM, tách theo model. Chờ user thêm `AGENT_API_KEY` vào `.env`; kiểm tên model bằng `GET <base>/models` trước
- [ ] Bật GPU (a30 timeout cổng 22, vast refused ngày 09/11), chạy vLLM Qwen3-VL-8B với `--enable-auto-tool-choice --tool-call-parser hermes`, chạy lại `--agent` native trên dev: đọc lại có cứu 3 bộ false review không
- [ ] Đo tác động của deskew lên trích xuất trên dev (cần GPU)
- [ ] Tinh chỉnh prompt agent trên dev nếu vẫn không dừng sớm ở bộ thiếu giấy tờ
- [ ] Quyết định merge `agent-mode` vào `main` (user)
- [ ] M0: phỏng vấn 2–3 cán bộ tín dụng (`m0_interview.md`)
