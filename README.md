# Loan Document Pipeline

MVP tự động hóa khâu tiếp nhận hồ sơ vay tiêu dùng cá nhân: **trích xuất** thông tin từ 4 loại giấy tờ → **đối chiếu chéo** bằng rule tất định → **route** mỗi bộ vào 1 trong 3 nhánh (auto-pass / người rà soát / yêu cầu bổ sung).

Câu hỏi dự án phải trả lời: *ở cấu hình nào pipeline tự xử lý được nhiều bộ nhất mà không để lọt bộ nào có sai lệch?* Thước đo chính là **escape rate** (bộ có sai lệch bị auto-pass), báo cáo kèm cận trên 95%; automation rate là kết quả đầu ra, không đặt trước.

> **Toàn bộ dữ liệu là synthetic.** Tên người, công ty, ngân hàng đều hư cấu; mọi trang in dòng "MẪU – DỮ LIỆU TỔNG HỢP". Không dùng dữ liệu khách hàng thật dưới bất kỳ hình thức nào, kể cả đã ẩn danh (Nghị định 13/2023 về bảo vệ dữ liệu cá nhân). Các ngưỡng rule là **giả định cho demo**, không phải chính sách tín dụng của ngân hàng nào.

Spec đầy đủ: [`docs/spec.md`](docs/spec.md). Cách sinh dữ liệu và giới hạn: [`docs/data_card.md`](docs/data_card.md).

## Trạng thái

| Giai đoạn | Nội dung | Trạng thái |
|---|---|---|
| M0 | Xác minh bài toán với 2–3 cán bộ tín dụng (A1, A2) | ⏳ bộ câu hỏi sẵn: [`docs/m0_interview.md`](docs/m0_interview.md) |
| M1 | Bộ sinh dữ liệu: 3 layout/loại (C held-out), lỗi E1–E8, near-miss, 3 mức augmentation, manifest | ✅ |
| M2 | Spike trích xuất VLM, gate: field quan trọng ≥ 90% trên dev clean | 🔧 extractor xong, **chưa chạy với model thật** |
| M3 | Rule R0–R8, router, trace JSON, `make eval` | ✅ phần tất định, đã kiểm bằng oracle |
| M4 | Review UI Streamlit, chạy test đóng băng 1 lần, demo | ⏳ |

M3 làm trước M2 có chủ đích: eval harness cần có sẵn để chấm M2, và chạy rule trên ground truth là cách duy nhất kiểm chứng nhãn của bộ sinh dữ liệu là đúng.

### Kết quả hiện tại: oracle (cận trên)

Extractor `oracle` trả đúng chuỗi đã in lên ảnh, không gọi model. Nó đo phần tất định: chuẩn hóa, rule, router. Mọi con số dưới 100% ở đây là bug của code, không phải của model.

| Split | Bộ (có lỗi) | Escape | Cận trên 95% | Automation | False review | Field acc |
|---|---|---|---|---|---|---|
| dev | 50 (25) | 0% | 11,3% | 50% | 0% | 100% |
| test | 300 (150) | 0% | 2,0% | 50% | 0% | 100% |

Recall mọi mã lỗi E1–E8 = 100%, không near-miss nào bị gắn cờ. Kết quả thật với VLM có sau M2.

## Chạy

```bash
pip install -r requirements.txt
pytest -q                                            # 95 test, ~15 giây

python -m datagen.build --seed 42                    # dev 50 + test 300 kèm ảnh -> data/synthetic/  (vài phút)
python -m loanpipe.evaluate --split dev --extractor oracle
#   -> reports/<run_id>/report.md, metrics.json, errors.csv, traces/*.json; reports/runs.csv

# Nhanh, không vẽ ảnh (CI dùng cách này):
python -m datagen.build --seed 42 --no-images --out data/synthetic-fast
python -m loanpipe.evaluate --split dev --data data/synthetic-fast --no-file-check
```

Có `make` thì dùng: `make test`, `make data SEED=42`, `make eval SPLIT=dev`, `make check`.

**Test set đóng băng:** sinh một lần ở M1 và `datagen.build` từ chối ghi đè `test/manifest.jsonl` (trừ khi `--force`). Chỉ chạy eval trên test một lần cho mỗi phiên bản cuối; mọi việc chỉnh prompt, ngưỡng đều làm trên dev.

## Kiến trúc

Workflow tất định 6 bước. Model chỉ xuất hiện ở bước 3, vì đọc ảnh là việc duy nhất code thường không làm được.

```
ingest ─► tiền xử lý ─► trích xuất (VLM, từng giấy tờ) ─► validate + chuẩn hóa + confidence ─► rule R0–R8 ─► router
 (R0: file đọc được?)                                     (Pydantic, code thuần)                (pass/fail/unknown)  AUTO_PASS | REVIEW | REQUEST_MORE
```

| Quyết định | Lý do |
|---|---|
| Workflow, không dùng agent | Các bước và thứ tự đã biết trước. Agent thêm tính bất định, eval khó hơn, khó giải thích vì sao một hồ sơ bị gắn cờ. |
| Trích xuất **từng giấy tờ riêng** | Đưa nhiều giấy tờ vào một prompt, model có thể "sửa" tên trên đơn cho khớp CCCD và che mất sai lệch thật. `tests/test_pipeline.py` giả lập đúng failure mode này và chứng minh eval bắt được. |
| Confidence **nhị phân** từ tín hiệu kiểm chứng được | VLM không trả xác suất đã hiệu chỉnh. `high` khi: định dạng hợp lệ + trả lời rõ ràng + 2 lần trích cho cùng kết quả. Không dùng việc khớp giữa các giấy tờ làm tín hiệu (rule đã kiểm, dùng lại là vòng tròn). |
| `unknown` không bao giờ là `pass` | Thiếu field hoặc confidence thấp → REVIEW. Chỉ bộ qua hết mọi kiểm tra mới AUTO_PASS. |
| Model chỉ chép, code tính | Lương trung bình, chuẩn hóa ngày/tiền/tên đều bằng code có unit test. Luôn giữ `raw` để truy vết. |
| Loại giấy tờ do người upload gắn | Thông tin có sẵn và đúng 100%; classifier để hạng "nên có". |

### Lệch so với spec (có chủ đích)

| Điểm | Spec | Repo | Lý do |
|---|---|---|---|
| So khớp tên (R1) | Khớp tuyệt đối, giữ dấu | **Hybrid**: khớp có dấu → pass; một bên *hoàn toàn* không dấu → so sau khi bỏ dấu; cả hai có dấu mà khác → fail | Sao kê in tên không dấu, đơn thường viết không dấu. Giữ dấu tuyệt đối thì mọi bộ hồ sơ đều fail R1. Vẫn bắt được E1 "sai 1 dấu" giữa đơn và CCCD. |
| Render | HTML + Jinja2 → WeasyPrint/Playwright | PIL | Không cần dependency hệ thống, chạy trên Windows. Nâng cấp nếu extractor đạt ~100% (test quá dễ). |
| Profile | Faker vi_VN | Danh sách tự soạn | Faker vi_VN sinh tên/địa chỉ kém tự nhiên; bớt một dependency. |
| Định dạng ảnh | PNG | JPEG (q95/q60/q75 theo mức) | PNG của ảnh nhiễu ~5–10 lần nặng hơn; JPEG chất lượng thấp vốn là một phần của augmentation. |

## Cấu trúc

```
loanpipe/
  schemas.py      # 4 schema giấy tờ + Field/Extraction/CheckResult/Decision + mã E1–E8, N1–N6
  normalize.py    # chuẩn hóa tên (giữ dấu, so khớp hybrid), ngày, tiền, CCCD, số TK
  validate.py     # raw -> value + confidence nhị phân
  rules.py        # R0–R8, hàm thuần
  router.py       # 3 nhánh, theo thứ tự spec mục 8
  pipeline.py     # workflow 6 bước + trace JSON
  evaluate.py     # eval 3 tầng, report.md / metrics.json / errors.csv, so với run trước
  extract/        # giao diện Extractor, oracle (cận trên), vlm (API tương thích OpenAI)
config/
  rules.yaml      # tolerance, regex giao dịch lương      (rules_version)
  thresholds.yaml # field quan trọng, tự nhất quán       (thresholds_version)
datagen/
  truth.py        # profile -> bộ hồ sơ, cài lỗi và near-miss
  render.py       # 3 layout/loại, ghi lại chuỗi raw đã in
  augment.py      # clean / scan / photo
  build.py        # CLI, chia dev/test, manifest.jsonl, đóng băng test
scripts/check_data_paths.py   # CI chặn ảnh/PDF ngoài data/synthetic/
docs/spec.md, docs/data_card.md
```

## M2: chạy spike VLM

Extractor `vlm` gọi API tương thích OpenAI (mặc định FPT AI Marketplace, `Qwen2.5-VL-7B-Instruct`; đổi `VLM_API_BASE` sang vLLM local nếu tự host). Mỗi lần gọi một giấy tờ; lỗi mạng hoặc output không phải JSON thì thử lại 1 lần rồi để field trống → REVIEW. Kết quả được cache trong `.cache/vlm/`, nên đổi ngưỡng rồi chạy lại eval không tốn thêm tiền.

```bash
cp .env.example .env        # điền VLM_API_KEY, giá token; ĐẶT GIỚI HẠN CHI TIÊU phía nhà cung cấp
python -m loanpipe.evaluate --split dev --extractor vlm --augment clean --limit 5          # ước chi phí
python -m loanpipe.evaluate --split dev --extractor vlm --augment clean --workers 4        # gate M2
python -m loanpipe.evaluate --split dev --extractor vlm --workers 4                         # đủ 3 mức ảnh
```

**Gate M2:** dòng "Field quan trọng" trong `report.md` của lần chạy `--augment clean` ≥ 90%. Không đạt → đổi model (vd Qwen3-VL-8B), chưa đi tiếp. Mỗi bộ tốn khoảng 8 lần gọi (4 giấy tờ × 2 lượt tự nhất quán); đặt `use_self_consistency: false` trong `config/thresholds.yaml` để giảm một nửa, nhưng chỉ giữ nếu escape rate trên dev không tăng.

Khi đọc kết quả, xem `errors.csv` (field sai: giá trị kỳ vọng vs model đọc) và `traces/*.json` (`model_outputs` là output thô của model).

## Việc tiếp theo

1. **M0**: phỏng vấn theo [`docs/m0_interview.md`](docs/m0_interview.md). Nếu ngân hàng đã có OCR/eKYC điền sẵn field, kể lại dự án quanh đối chiếu chéo + routing thay vì trích xuất.
2. **M2**: chạy spike ở trên, qua gate thì phân tích lỗi theo field × layout × augmentation trên dev.
3. Vẽ đường cong automation vs escape trên dev (có/không tự nhất quán, danh sách field quan trọng khác nhau), chọn điểm vận hành, rồi mới chạy test một lần.
