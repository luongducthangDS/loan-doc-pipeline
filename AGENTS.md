# loan-doc-pipeline: agent notes

Pipeline hồ sơ vay tiêu dùng: VLM trích xuất 4 giấy tờ → rule tất định R0–R8 → router 3 nhánh; thước đo chính là escape rate. Dữ liệu synthetic.

Đọc trước khi làm: [docs/RULES.md](docs/RULES.md) > [docs/PRD.md](docs/PRD.md) (bản đầy đủ: [spec.md](docs/spec.md)) > [ARCHITECTURE](docs/ARCHITECTURE.md), [DESIGN](docs/DESIGN.md), [TASKS](docs/TASKS.md), [PROGRESS](docs/PROGRESS.md). Khác: `data_card.md`, `m2_eval.md`, `quality-engineering.md`.

## Trạng thái (2026-11-13)
- Nhánh `agent-mode` đã push lên `origin/agent-mode`, chưa merge vào `main`. Gồm QE `0d74c37`, deskew `9163fbf`, agent `2ee4eb3`.
- Test đóng băng: escape 2,0 %, automation 41,3 %; agent mode đo trên dev, chưa đọc lại được vì GPU tắt. Chi tiết ở `docs/PROGRESS.md`.
- Demo Render (13/11): https://loan-doc-pipeline.onrender.com, deploy từ `agent-mode` qua `render.yaml`/Dockerfile (`$PORT`). Đây là demo duy nhất (đã bỏ bản Streamlit Cloud 13/11).
- B1 OCR (EasyOCR + anchor, `--extractor ocr`, cần `requirements-ocr.txt`) đã commit: dev escape 0/25, automation 8 %, field acc 72,3 %. Bảng so sánh xem được trên GitHub ở `docs/COMPARISON.md` (chép tay từ `reports/`, bị gitignore).
- Việc tiếp theo: mục đầu tiên chưa tick trong `docs/TASKS.md` (cần GPU).

## Gotchas
- Dùng `.venv/Scripts/python.exe`; `python` mặc định trỏ venv DocuMind, thiếu streamlit.
- Khoá FPT trong `.env` chỉ có `Qwen2.5-VL-7B-Instruct`, server không bật tool calling native → `AGENT_TOOL_MODE=json`.
- LLM agent dự kiến dùng Gemini free: hạn mức mỗi model nhỏ (Flash 20 RPD, Flash Lite 500 RPD) nên `AGENT_MODEL` là pool `tên:rpm:rpd,...`; mỗi bộ dính một model, `agent.models` trong trace ghi model thật đã dùng. Trộn model làm kết quả lẫn, báo cáo tách theo `bundles_by_model`.
- GPU: bật VM trên console, `ssh -N a30`, rồi chạy vLLM.
- Không commit `gemini.md`, `.claude/`.
- Render CLI đã đăng nhập (`render services`, `render deploys list <srv>`); service tạo bằng `render services create`, không qua Blueprint sync. Từ Git Bash phải đặt `MSYS_NO_PATHCONV=1`, không thì tham số `/...` bị đổi thành đường dẫn Windows.
