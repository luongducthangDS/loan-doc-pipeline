# loan-doc-pipeline: agent notes

## Git (09/11)

Nhánh `agent-mode`, chưa push, chưa merge vào `main` (main đang deploy demo Streamlit). 3 commit: `0d74c37` QE (`review.close_item` báo lỗi khi không có bộ), `9163fbf` deskew, `2ee4eb3` agent. Không commit `gemini.md`, `.claude/`.

## 2026-11-09: chế độ agent (LLM tự điều phối)

- **Đã xong:** `loanpipe/agent.py`, bật bằng `python -m loanpipe.evaluate ... --agent`. LLM cầm lái từ đầu bằng tool `list_documents` / `read_document(doc_type, original|deskew|hires)` / `run_rules` / `finish(route, note)`; vòng ReAct qua function calling OpenAI, `MAX_TURNS=12`, stdlib. Workflow cũ vẫn là chế độ mặc định. `pipeline.finalize_doc` tách ra để dùng chung; extractor có tham số `method`. Test: `tests/test_agent.py` (LLM giả). Commit `2ee4eb3`.
- **Hàng rào nằm trong code:** agent không đưa giá trị field; đọc lại chỉ nâng low→high khi 2 lượt mới tự nhất quán và khớp mọi lượt đọc hợp lệ trước đó; field high bị khoá; mỗi (giấy tờ, cách đọc) 1 lần; `finish` bị từ chối (trả lý do về cho model) nếu đòi AUTO_PASS khi router không ra AUTO_PASS, hoặc không REQUEST_MORE khi R0 fail; LLM lỗi / hết lượt thì dùng router trên dữ liệu đã đọc.
- **Thêm sau:** token/chi phí/latency LLM vào trace và mục "Agent" của report.md; `app.py` hiện ghi chú + nhật ký agent (test trong `tests/test_app.py`); `AGENT_TOOL_MODE=json` cho server không bật tool parser; thử lại 429/5xx. Toàn suite 123 passed khi chạy bằng `.venv` của repo (có streamlit).
- **Đã đo (dev 50, VLM từ cache Qwen3-VL-8B@a30, LLM FPT Qwen2.5-VL-7B json mode), 2 lần:** nhánh trùng workflow 50/50, escape 0/25, automation 44%, false review 12%; +$0,0084 và ~13 s mỗi bộ. Lần 1 model không dừng sớm ở bộ thiếu giấy tờ; lần 2, sau khi `list_documents` trả `hint` nêu hệ quả R0, 3/3 bộ chốt REQUEST_MORE với 0 lượt VLM. 1 bộ dính 429 sau retry -> router (đúng). Chưa có lần đọc lại nào (GPU tắt). Report ở scratchpad, không ghi vào `reports/runs.csv`.
- **Còn lại (09/11 GPU không vào được: a30 timeout cổng 22, vast refused):** bật VM trên console, `ssh -N a30`, chạy vLLM Qwen3-VL-8B với `--enable-auto-tool-choice --tool-call-parser hermes`, chạy lại `--agent` (native) để đo đọc lại có cứu được 3 bộ false review không; tinh chỉnh prompt trên dev nếu vẫn không dừng sớm.
- **Gotcha:** dùng `.venv/Scripts/python.exe`, không dùng `python` mặc định (trỏ vào venv DocuMind, thiếu streamlit). Khoá FPT trong `.env` chỉ có `Qwen2.5-VL-7B-Instruct` và server không bật tool calling native.

## 2026-11-07: tiền xử lý deskew

- **Đã xong:** `loanpipe/preprocess.py`, bật bằng `VLM_PREPROCESS=deskew`, mặc định tắt. Test ở `tests/test_preprocess.py`. Commit `9163fbf`.
- **Đã đo:** 58 ảnh dev xoay góc đã biết, sai số trung vị dưới 0,05°, lớn nhất 0,25°; không xoay nhầm ảnh clean gốc.
- **Còn lại:** chạy dev với VLM để đo tác động lên trích xuất (cần GPU). Không chạy lại test set đóng băng.
- **Lưu ý:** khoá cache VLM băm file gốc, nên mọi kiểu tiền xử lý mới phải thêm tag vào khoá. Khi tắt, khoá giữ nguyên để cache cũ dùng được. `python` mặc định thiếu `streamlit` nên skip `tests/test_app.py`; `.venv` của repo thì có.
