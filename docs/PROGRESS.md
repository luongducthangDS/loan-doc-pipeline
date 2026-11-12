# Progress

## Trạng thái (2026-11-09, nhánh `agent-mode`, đồng bộ `origin/agent-mode`)
- Test đóng băng (VLM Qwen3-VL-8B, chạy 1 lần): escape 3/150 = 2,0 % (cận trên 5,1 %), automation 41,3 %. Oracle: escape 0 %, automation 50 %, field acc 100 %.
- Demo public: https://loan-doc-pipeline-luongducthangws.streamlit.app/ (từ `main`).
- Chế độ agent (dev 50, VLM từ cache, LLM FPT Qwen2.5-VL-7B json mode, 2 lần): nhánh trùng workflow 50/50, escape 0/25, automation 44 %, false review 12 %; +$0,0084 và ~13 s mỗi bộ. Chưa có lượt đọc lại nào (GPU tắt).
- Deskew: 58 ảnh dev xoay góc biết trước, sai số trung vị < 0,05°, lớn nhất 0,25°.
- Test: 123 passed bằng `.venv` của repo (09/11).
- OCR vs VLM (dev 50 bộ, `docs/OCR_BENCHMARK.md`): VLM exact match 96,5 % / CER 0,007; EasyOCR (oracle-aligned) 65,7 % / CER 0,055; phân loại giấy tờ từ text OCR accuracy 0,988.

## Vấn đề mở
- GPU không vào được từ 09/11; khoá FPT chỉ có Qwen2.5-VL-7B và server không bật tool calling native.
- CI (`.github/workflows/ci.yml`) có từ 27/09 nhưng GitHub ghi 0 lần chạy tới 12/11; push 12/11 để kiểm tra.

## Bước tiếp theo
Mục đầu tiên chưa tick trong `TASKS.md` (cần GPU).
