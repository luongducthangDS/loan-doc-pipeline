# loan-doc-pipeline: agent notes

Pipeline hồ sơ vay tiêu dùng: VLM trích xuất 4 giấy tờ → rule tất định R0–R8 → router 3 nhánh; thước đo chính là escape rate. Dữ liệu synthetic.

Đọc trước khi làm: [docs/RULES.md](docs/RULES.md) > [docs/PRD.md](docs/PRD.md) (bản đầy đủ: [spec.md](docs/spec.md)) > [ARCHITECTURE](docs/ARCHITECTURE.md), [DESIGN](docs/DESIGN.md), [TASKS](docs/TASKS.md), [PROGRESS](docs/PROGRESS.md). Khác: `data_card.md`, `m2_eval.md`, `quality-engineering.md`.

## Trạng thái (2026-11-11)
- Nhánh `agent-mode` đã push lên `origin/agent-mode`, chưa merge vào `main` (main deploy demo Streamlit). Gồm QE `0d74c37`, deskew `9163fbf`, agent `2ee4eb3`.
- Test đóng băng: escape 2,0 %, automation 41,3 %; agent mode đo trên dev, chưa đọc lại được vì GPU tắt. Chi tiết ở `docs/PROGRESS.md`.
- Việc tiếp theo: mục đầu tiên chưa tick trong `docs/TASKS.md` (cần GPU).

## Gotchas
- Dùng `.venv/Scripts/python.exe`; `python` mặc định trỏ venv DocuMind, thiếu streamlit.
- Khoá FPT trong `.env` chỉ có `Qwen2.5-VL-7B-Instruct`, server không bật tool calling native → `AGENT_TOOL_MODE=json`.
- GPU: bật VM trên console, `ssh -N a30`, rồi chạy vLLM.
- Không commit `gemini.md`, `.claude/`.
