# Progress

## Trạng thái (2026-11-09, nhánh `agent-mode`, đồng bộ `origin/agent-mode`)
- Test đóng băng (VLM Qwen3-VL-8B, chạy 1 lần): escape 3/150 = 2,0 % (cận trên 5,1 %), automation 41,3 %. Oracle: escape 0 %, automation 50 %, field acc 100 %.
- Demo public: https://loan-doc-pipeline.onrender.com (Render, từ `agent-mode`); bản Streamlit Cloud đã bỏ (13/11).
- Chế độ agent (dev 50, VLM từ cache, LLM FPT Qwen2.5-VL-7B json mode, 2 lần): nhánh trùng workflow 50/50, escape 0/25, automation 44 %, false review 12 %; +$0,0084 và ~13 s mỗi bộ. Chưa có lượt đọc lại nào (GPU tắt).
- Deskew: 58 ảnh dev xoay góc biết trước, sai số trung vị < 0,05°, lớn nhất 0,25°.
- Test: 124 passed bằng `.venv` của repo và trong Docker image (12/11).
- Docker: `docker build -t loan-doc-pipeline .` chạy review UI (healthcheck `/_stcore/health`), image ~900 MB; `DEMO_PASSWORD` bật cổng mật khẩu.
- OCR vs VLM (dev 50 bộ, `docs/OCR_BENCHMARK.md`): VLM exact match 96,5 % / CER 0,007; EasyOCR (oracle-aligned) 65,7 % / CER 0,055; phân loại giấy tờ từ text OCR accuracy 0,988.
- So sánh biến thể (13/11): `reports/comparison.md` dựng từ 11 run rules-v2, baseline Qwen3-VL-8B@a30. Dev full: oracle automation 50 % (trần tầng rule), Qwen2.5 46 % / false review 8 %, Qwen3 44 % / 12 %; mọi run escape 0 (cận trên 95 % 11,3 %). Bảng chưa có B1 OCR và B5 agent.

## B1 OCR end-to-end (2026-11-13)
- Run `20261113-170224_dev_ocr`, dev đủ 50 bộ/249 ảnh có box cache: escape 0/25 (cận trên 95 % 11,3 %), automation 8 %, false review 84 %, field acc 72,3 %, critical acc 82,0 %.
- Sao kê parse được 17/48, row recall 33,3 %, credit-row recall 20,7 %. Dấu +/- bị OCR bỏ mất, tiêu đề cột và dấu tiếng Việt là điểm yếu; không suy hướng giao dịch từ mô tả, không bỏ qua dòng tiền lỗi.
- Cùng 50 bộ với Qwen3@a30: 32 route giống, 18 bộ VLM xử lý tự động bị OCR đẩy sang REVIEW. Oracle-aligned trong benchmark cũ là phép căn chỉnh có dùng nhãn, không phải baseline end-to-end; metric cũng khác nên không so trực tiếp hai phần trăm.
- B1 dùng một lượt OCR, không có kiểm chứng độc lập bằng đọc lại. 4,98 lượt trích xuất/bộ; $0 là API, chưa gồm CPU. Latency p95 ~248,7 s lấy từ cache xây ở mức song song khác nhau, không phải wall time replay hay benchmark tốc độ công bằng với VLM.
- `reports/comparison.md` có 5 biến thể, mốc VLM không đổi khi thêm OCR; chưa có B5b đo bằng LLM thật. Chỉ sao chép run B1 đã kiểm chứng vào reports, không sửa `reports/runs.csv`; không chạy lại test đóng băng.
- Kiểm thử sau B1: 154 passed trong `.venv` của repo. Đã commit (13/11); bảng so sánh chép sang `docs/COMPARISON.md` để xem trên GitHub.

## Demo Render + UI (2026-11-13)
- https://loan-doc-pipeline.onrender.com (service `srv-dbrefil6e07s73bef4vg`, Docker, free, Singapore, nhánh `agent-mode`, auto-deploy). Free ngủ sau ~15 phút, lần mở đầu chờ ~1 phút; SQLite rà soát ở `/data` trong container, mất khi redeploy.
- UI: thêm trang Tổng quan pipeline, nav có trạng thái active, responsive (kiểm bằng Playwright ở 390/900/1440px). 154 test pass. Ảnh chụp từ bản live trong `docs/img/`, nhúng vào README.

## Vấn đề mở
- GPU không vào được từ 09/11; khoá FPT chỉ có Qwen2.5-VL-7B và server không bật tool calling native.
- CI (`.github/workflows/ci.yml`) có từ 27/09 nhưng GitHub ghi 0 lần chạy tới 12/11; push 12/11 để kiểm tra.

## Bước tiếp theo
Mục đầu tiên chưa tick trong `TASKS.md`; B5b kiểm chứng offline trước, chỉ chạy FPT khi có duyệt chi phí.
