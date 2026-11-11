# Progress

## Trạng thái (2026-11-09, nhánh `agent-mode`, đồng bộ `origin/agent-mode`)
- Test đóng băng (VLM Qwen3-VL-8B, chạy 1 lần): escape 3/150 = 2,0 % (cận trên 5,1 %), automation 41,3 %. Oracle: escape 0 %, automation 50 %, field acc 100 %.
- Demo public: https://loan-doc-pipeline-luongducthangws.streamlit.app/ (từ `main`).
- Chế độ agent (dev 50, VLM từ cache, LLM FPT Qwen2.5-VL-7B json mode, 2 lần): nhánh trùng workflow 50/50, escape 0/25, automation 44 %, false review 12 %; +$0,0084 và ~13 s mỗi bộ. Chưa có lượt đọc lại nào (GPU tắt).
- Deskew: 58 ảnh dev xoay góc biết trước, sai số trung vị < 0,05°, lớn nhất 0,25°.
- Test: 123 passed bằng `.venv` của repo (09/11).

## Vấn đề mở
- GPU không vào được từ 09/11; khoá FPT chỉ có Qwen2.5-VL-7B và server không bật tool calling native.
- Việc dở của session khác chưa commit: `docs/OCR_BENCHMARK.md`, `scripts/ocr_benchmark.py`, `requirements-ocr.txt`.

## Bước tiếp theo
Mục đầu tiên chưa tick trong `TASKS.md` (cần GPU).
