# M2: quy trình eval và benchmark trích xuất VLM

Tài liệu này trả lời hai câu hỏi: **chạy eval M2 thế nào cho ra số so sánh được**, và **các cấu hình đã chạy đạt bao nhiêu**. Định nghĩa gốc của metric nằm ở [`spec.md`](spec.md) mục 9; ở đây chỉ nhắc lại phần cần để đọc bảng.

## 1. Dữ liệu

| Split | Bộ | clean / scan / photo | Bộ có lỗi (E1–E8) | Near-miss | Dùng để |
|---|---|---|---|---|---|
| dev | 50 | 26 / 13 / 11 | 25 | 8 | Mọi việc chỉnh prompt, rule, ngưỡng |
| test | 300 | 121 / 84 / 95 | 150 | 50 | **Chạy đúng 1 lần** cho phiên bản cuối (đóng băng) |

Mỗi bộ có đúng một mức ảnh. Gate M2 chỉ tính trên 26 bộ dev clean.

## 2. Metric

**End-to-end (quyết định giữ hay loại một thay đổi)**
- **Escape rate**: bộ có lỗi bị AUTO_PASS / số bộ có lỗi. Luôn báo kèm **cận trên 95%** (Clopper–Pearson): 0/25 không có nghĩa là 0%, mà là ≤ 11,3%.
- **Automation rate**: bộ AUTO_PASS / tổng số bộ. Trần là 50% trên dev (một nửa số bộ có lỗi hoặc thiếu giấy tờ); oracle đạt đúng trần.
- **False review rate**: bộ sạch bị đẩy sang REVIEW / số bộ sạch.

**Rule**: recall theo từng mã lỗi E1–E8; tỉ lệ bộ sạch và near-miss N1–N6 **không** bị gắn cờ.

**Trích xuất**
- Field accuracy và **field quan trọng** (danh sách trong `config/thresholds.yaml`); tách theo mức ảnh, layout, từng field. Chấm theo thứ pipeline dùng, không theo từng ký tự:
  - field text không phân biệt hoa/thường (`Nữ` = `NỮ`); tên vẫn so giữ dấu vì R1 bắt lỗi sai 1 dấu;
  - `giao_dich` đúng khi **lương theo tháng** tính từ sao kê (thứ duy nhất R4 đọc) khớp ground truth. Đọc sai một dòng ghi nợ không làm field trượt.
- **Sao kê theo dòng** (chấm chặt, để chẩn đoán): con số của field `giao_dich` không cho biết model đọc được bao nhiêu dòng. Báo thêm:
  - *row recall*: dòng của ground truth được đọc đúng đủ (ngày, nội dung, số tiền, loại);
  - *row precision*: dòng model trả ra có trong ground truth (bắt dòng bịa);
  - *dòng Ghi có*: recall riêng các dòng tiền vào, là thứ R4 dùng tính lương.

  Sao kê không parse được thì toàn bộ dòng của nó tính là trượt.

**Vận hành**: latency p50/p95 mỗi bộ, số lần gọi model mỗi bộ, chi phí mỗi bộ.

## 3. Quy tắc quyết định

1. **Escape rate tăng → loại thay đổi**, dù automation tăng bao nhiêu. `evaluate` tự in cảnh báo.
2. **Chỉ so run cùng split và cùng bộ lọc** (`--augment`, `--limit`). `evaluate` tự chọn run trước theo cả hai; so run clean với run toàn bộ dev là sai.
3. **Gate M2**: field quan trọng ≥ 90% trên dev clean. Không đạt → đổi model, chưa đi tiếp.
4. Mọi chỉnh sửa làm trên dev. Test chạy một lần, cuối cùng, với cùng backend đã dùng cho gate.
5. Mỗi dòng benchmark phải truy được: `run_id` → `reports/<run_id>/` (report, metrics, errors, traces) và dòng tương ứng trong `reports/runs.csv` (model, prompt_version, rules_version, git commit).

## 4. Quy trình chạy

### 4.1 Chọn backend

Code gọi mọi backend qua API tương thích OpenAI; chỉ đổi `.env`. **Cache lưu theo tên model**, nên hai backend phải có tên khác nhau để không lẫn kết quả (FPT: `Qwen2.5-VL-7B-Instruct`, tự host: `Qwen/Qwen2.5-VL-7B-Instruct`).

| Backend | `.env` | Ghi chú |
|---|---|---|
| FPT AI Marketplace | `VLM_API_BASE=https://mkp-api.fptcloud.com`, giá $0,77/M token vào và ra | Chỉ nhận **1 ảnh mỗi request** (extractor đã gọi từng ảnh) |
| Tự host trên vast.ai | `VLM_API_BASE=http://localhost:8000/v1`, giá để 0 | Mục 4.2 |

### 4.2 Dựng máy GPU (tự host)

1. Thuê GPU ≥ 24 GB VRAM, ổ ≥ 40 GB cho một model (≥ 60 GB nếu định so hai model trên cùng máy).
2. Trên máy GPU, trong `tmux`:
   ```bash
   VLLM_USE_FLASHINFER_SAMPLER=0 vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
     --host 127.0.0.1 --port 8000 --api-key <key> --max-model-len 16384
   ```
   Với dòng RTX 50xx (Blackwell) cần thêm hai việc đã gặp thật:
   - `uv pip uninstall torchaudio` nếu torchaudio của template khác bản CUDA với torch mà vLLM cài;
   - `VLLM_USE_FLASHINFER_SAMPLER=0` vì FlashInfer biên dịch bằng nvcc 12.8 có sẵn, còn Blackwell cần ≥ 12.9. Project gọi temperature 0 nên không ảnh hưởng kết quả.
3. Trên máy mình, mở tunnel và giữ terminal đó mở: `ssh -N gpu` (host `gpu` khai trong `~/.ssh/config`). Không mở port vLLM ra internet.
4. **Destroy instance khi xong.** Kết quả đã nằm trong `.cache/vlm/` ở máy mình; các lần chạy lại eval sau đó không cần GPU.

### 4.3 Chạy

```bash
# 0. Oracle: cận trên, kiểm phần tất định (mọi số < 100% là bug code)
python -m loanpipe.evaluate --split dev --extractor oracle
python -m loanpipe.evaluate --split dev --extractor oracle --augment clean

# 1. Smoke test 5 bộ: kiểm backend, ước chi phí
python -m loanpipe.evaluate --split dev --extractor vlm --augment clean --limit 5 --workers 8

# 2. Gate M2: dev clean
python -m loanpipe.evaluate --split dev --extractor vlm --augment clean --workers 8

# 3. Toàn bộ dev: độ bền theo mức ảnh
python -m loanpipe.evaluate --split dev --extractor vlm --workers 8
```

Sau mỗi run, đọc theo thứ tự: `report.md` (tổng quan) → `errors.csv` (`kind=route` để biết vì sao bộ sạch vào REVIEW, `rule_miss`, `false_flag`) → `traces/<bundle>.json` (`model_outputs` là output thô, `extract_errors` là lỗi API).

**Sửa parser hoặc rule không tốn tiền API**: cache lưu output thô và parse lại mỗi lần đọc, nên chỉ cần chạy lại bước 2–3. Sửa prompt thì chỉ loại giấy tờ có prompt đổi bị gọi lại.

### 4.4 Ghi kết quả

Thêm một dòng vào bảng mục 5 cho mỗi cấu hình (model × backend × prompt_version), kèm `run_id`. Commit code trước khi chạy run dùng cho benchmark, để `git_commit` trong `runs.csv` không có hậu tố `-dirty`.

## 5. Benchmark

Dev, seed 42, commit `c22a5d1`. Escape ghi dạng *k/n (cận trên 95%)*. Field chấm theo mục 2 (text không phân biệt hoa/thường, `giao_dich` theo lương từng tháng); cột "Sao kê" là số chấm chặt theo dòng.

### Toàn bộ dev (50 bộ)

| Cấu hình | Escape | Automation | False review | Field | Field quan trọng | Sao kê: dòng đúng / Ghi có | p95 mỗi bộ | Run |
|---|---|---|---|---|---|---|---|---|
| B0: mọi bộ vào REVIEW | 0/25 | 0% | 100% | – | – | – | – | – |
| Oracle (trần) | 0/25 (≤ 11,3%) | 50,0% | 0% | 100% | 100% | 100% / 100% | ~0 | `20260928-103936_dev_oracle` |
| Qwen2.5-VL-7B tự host, prompt v4 | **0/25 (≤ 11,3%)** | **32,0%** | 36,0% | 98,5% | 99,0% | 68,6% / 85,4% | 136 s | `20260928-103936_dev_Qwen_Qwen2.5-VL-7B-Instruct` |

### Dev clean (26 bộ, gate M2)

| Cấu hình | Escape | Automation | False review | Field quan trọng | Sao kê: dòng đúng / Ghi có | Gate | Run |
|---|---|---|---|---|---|---|---|
| Oracle (trần) | 0/12 (≤ 22,1%) | 53,8% | 0% | 100% | 100% / 100% | – | `20260928-103937_dev_oracle` |
| Qwen2.5-VL-7B tự host, prompt v4 | **0/12 (≤ 22,1%)** | **42,3%** | 21,4% | **100%** | 67,7% / 88,1% | **Đạt** | `20260928-103937_dev_Qwen_Qwen2.5-VL-7B-Instruct` |

Qwen2.5-VL-7B theo mức ảnh (field accuracy): clean 99,4%, scan 98,3%, photo 96,6%. `giao_dich` 43/48 sao kê đúng lương từng tháng (4 không parse được, 1 đọc 26.558.000 thành 26.358.000). Recall rule trên toàn bộ dev: E1–E3, E5–E8 đều 100%; E4 2/3 (bộ còn lại vẫn vào REVIEW vì R4 = unknown, không phải escape). Near-miss: 7/8 không bị gắn cờ; N3 `dev_0041` bị R1 gắn cờ vì model đọc CCCD "KIÊN" thành "KIỀN".

### Chưa chạy

| Cấu hình | Mục đích |
|---|---|
| Qwen2.5-VL-7B qua FPT, prompt v4 | Kiểm tra tự host có cho kết quả tương đương API không |
| Qwen3-VL-8B tự host | Ứng viên thay thế; điểm yếu cần so là đọc bảng sao kê dài |
| Một model đóng (GPT-4o hoặc Gemini) | Mốc trên của khả năng đọc; đo cái giá của yêu cầu data residency |

## 6. Nhật ký thay đổi tìm ra khi chạy M2

Mỗi dòng là một lỗi thật gặp trên dev, cách sửa, và tác động đo được.

| # | Lỗi | Sửa | Tác động |
|---|---|---|---|
| 1 | FPT trả HTTP 400 "Invalid image URL" với request nhiều ảnh → CCCD (2 mặt) trống toàn bộ | Gọi từng ảnh rồi gộp; sao kê nhiều trang nối danh sách giao dịch (prompt v2) | CCCD từ 0% lên 88% (5 bộ, FPT) |
| 2 | Qwen bọc từng dòng giao dịch trong `{"raw": ..., "page": ...}` | Parser bóc lớp bọc; cache parse lại từ output thô | Sao kê parse được |
| 3 | Mặt sau CCCD không có chữ "ngày cấp", chỉ có "Ngày, tháng, năm" | Ghi rõ nhãn đó trong hint | `ngay_cap` 0% (5 bộ) → 68% (toàn bộ dev) |
| 4 | Sao kê hai cột Ghi có / Ghi nợ: model gán nhầm loại | Chép cả hai cột `ghi_co`/`ghi_no`, code suy ra loại (prompt v3) | Layout A đọc đúng phần lớn dòng |
| 5 | Model chép cả nhãn "ÔNG/BÀ:" vào tên → R1 fail giả | System prompt: chỉ chép giá trị, không chép nhãn (prompt v4) | `hdld.ho_ten_nld` 80% → 100% (5 bộ) |
| 6 | Sao kê một cột có dấu: model dùng khuôn hai cột và chép "-595,000" vào `ghi_co`; code từ chối vì mâu thuẫn → 21/48 sao kê bị loại | Dấu +/- chép từ ảnh quyết định loại giao dịch, bỏ qua cột model chọn | Toàn bộ dev: automation **12% → 32%**, escape giữ 0/25; sao kê parse được 24 → 44/48 |
| 7 | Dòng giao dịch dạng chuỗi (ảnh scan) làm crash cả run | Dòng không phải object → lỗi field → REVIEW | Run không còn crash |
| 8 | Eval chấm quá khắt: `giao_dich` trượt nếu lệch 1/25 dòng (kể cả dòng ghi nợ R4 không đọc); `Nữ` ≠ `NỮ` | Chấm theo thứ rule dùng: lương từng tháng, text không phân biệt hoa/thường; row recall giữ chặt để chẩn đoán | Chỉ đổi số trích xuất: field quan trọng toàn bộ dev 95,8% → 99,0%, dev clean 96,1% → 100%; routing không đổi |

## 7. Còn lại sau M2

- **Sao kê là nút thắt**: 8/9 bộ sạch vào REVIEW ở toàn bộ dev là vì `giao_dich` confidence thấp. Row recall 68,6% (layout A kém hơn B). Đây là chỗ đáng thử Qwen3-VL-8B nhất.
- **`cccd.ngay_cap` 68%** trên toàn bộ dev.
- **Latency p95 136 s/bộ**, trên mục tiêu 60 s của spec. Phần lớn nằm ở sao kê (output dài, 2 lượt tự nhất quán). Hướng giảm: tắt tự nhất quán (giữ nếu escape dev không tăng) hoặc chạy song song các giấy tờ trong một bộ.
- **Chi phí tự host** chưa quy về $/bộ; cần ghi giá thuê GPU/giờ và thời gian chạy.
