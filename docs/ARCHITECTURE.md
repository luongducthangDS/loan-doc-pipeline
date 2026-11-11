# Architecture

Chi tiết và lý do lựa chọn: [spec.md](spec.md) mục 6–8.

## Stack
Python · Pydantic · pdf2image + OpenCV (tiền xử lý, deskew tuỳ chọn) · VLM qua API tương thích OpenAI (chọn Qwen3-VL-8B ở gate M2; FPT AI Marketplace / vLLM tự host trên GPU thuê) · rule + ngưỡng trong `config.toml` · filesystem + SQLite · Streamlit (review UI, demo public) · pytest.

## Thư mục
```
datagen/      sinh hồ sơ synthetic: render, profiles, truth, augment, build (3 layout/loại, layout C held-out, lỗi E1–E8, near-miss)
loanpipe/extract/{oracle,vlm}.py   oracle trả đúng chuỗi đã in (đo phần tất định); vlm gọi model, cache theo hash file
loanpipe/preprocess.py   deskew (VLM_PREPROCESS=deskew, mặc định tắt)
loanpipe/{normalize,validate,schemas}.py   chuẩn hoá + validate field
loanpipe/rules.py        rule R0–R8 đối chiếu chéo
loanpipe/router.py       3 nhánh: AUTO_PASS / review / REQUEST_MORE
loanpipe/pipeline.py     workflow tất định 6 bước (finalize_doc dùng chung)
loanpipe/agent.py        chế độ agent (--agent): LLM gọi tool, hàng rào trong code
loanpipe/review.py       review queue
loanpipe/evaluate.py     make eval → reports/<run_id>/{report.md, metrics.json, errors.csv, traces/}, reports/runs.csv
app.py                   Streamlit review UI
```

## Luồng
`4 giấy tờ (loại do người upload gắn) → tiền xử lý → VLM trích từng giấy tờ riêng, 2 lượt tự nhất quán → chuẩn hoá + validate → rule R0–R8 → router → AUTO_PASS | review queue | REQUEST_MORE`; bản sửa của reviewer trở thành dữ liệu eval. Chế độ agent: LLM chọn `list_documents / read_document / run_rules / finish`, code chặn mọi kết luận trái router.
