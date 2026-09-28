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
- **False review rate**: bộ sạch bị đẩy sang REVIEW / số bộ sạch. Nhãn "sạch" lấy từ ground truth, không tính chất lượng đọc: bộ sạch mà model đọc ra chữ rác (`GARBLED`) bị tính là false review dù đưa sang người là đúng.
- **Dữ liệu bộ AUTO_PASS**: độ chính xác field, chỉ trên các bộ được auto-pass, và số bộ auto-pass có ít nhất 1 field sai. Đây là dữ liệu vào hệ thống không qua người, kể cả field không rule nào đọc (như ngày cấp CCCD). Hai model có thể cùng automation mà khác hẳn ở chỉ số này.

**Rule**: với mỗi mã lỗi E1–E8, đếm rule trả về gì trên các bộ mang lỗi đó: **fail** (bắt được), **unknown** (không chắc, bộ vẫn vào REVIEW: an toàn nhưng không phải "bắt được"), **pass** (sót thật). Recall = fail / n. Thêm: tỉ lệ bộ sạch và near-miss N1–N6 **không** bị gắn cờ.

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
   VLLM_USE_FLASHINFER_SAMPLER=0 vllm serve Qwen/Qwen3-VL-8B-Instruct \
     --host 127.0.0.1 --port 8000 --api-key <key> --max-model-len 16384
   ```
   Với dòng RTX 50xx (Blackwell) cần thêm hai việc đã gặp thật:
   - `uv pip uninstall torchaudio` nếu torchaudio của template khác bản CUDA với torch mà vLLM cài;
   - `VLLM_USE_FLASHINFER_SAMPLER=0` vì FlashInfer biên dịch bằng nvcc 12.8 có sẵn, còn Blackwell cần ≥ 12.9. Project gọi temperature 0 nên không ảnh hưởng kết quả.
   **Đổi model trên cùng máy:** `huggingface_hub` bản mới lưu trọng số trong thư mục chung `$HF_HOME/hub/blobs`, nên xóa `models--<tên>` không giải phóng ổ. Dừng vLLM, xóa cả `$HF_HOME/hub` rồi mới `vllm serve` model mới (đã gặp: máy 32 GB còn 8 GB trống sau khi "xóa" 7B).
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

Dev, seed 42, prompt v4, `rules-v2`. Cả hai model tự host trên cùng một RTX 5090 (vLLM 0.30, `--workers 8`); mọi run dưới đây chấm lại từ cache với cùng code nên so trực tiếp được. Escape ghi dạng *k/n (cận trên 95%)*. Field chấm theo mục 2; cột "Sao kê" là số chấm chặt theo dòng. Latency là tổng thời gian các lần gọi model của một bộ, đo khi 8 bộ chạy song song trên một GPU (có thời gian chờ hàng đợi): dùng để so hai model với nhau, không so trực tiếp với mục tiêu 60 s của spec.

### Toàn bộ dev (50 bộ)

| Cấu hình | Escape | Automation | False review | Field quan trọng | **Dữ liệu bộ AUTO_PASS**: field đúng / bộ có field sai | Sao kê: dòng đúng / Ghi có | p95 mỗi bộ | Run |
|---|---|---|---|---|---|---|---|---|
| B0: mọi bộ vào REVIEW | 0/25 | 0% | 100% | – | – | – | – | – |
| Oracle (trần) | 0/25 (≤ 11,3%) | 50,0% | 0% | 100% | 100% / 0 trên 25 | 100% / 100% | ~0 | `20260928-111027_dev_oracle` |
| Qwen2.5-VL-7B | 0/25 (≤ 11,3%) | 46,0% | 8,0% | 99,0% | 98,4% / **10 trên 23** | 68,6% / 85,4% | 136 s | `20260928-111029_dev_Qwen_Qwen2.5-VL-7B-Instruct` |
| **Qwen3-VL-8B** | **0/25 (≤ 11,3%)** | 44,0% | 12,0% | **99,3%** | **100% / 0 trên 22** | **87,7% / 90,9%** | 161 s | `20260928-111031_dev_Qwen_Qwen3-VL-8B-Instruct` |
| Qwen3-VL-8B, A30 24 GB | 0/25 (≤ 11,3%) | 44,0% | 12,0% | 99,3% | 100% / 0 trên 22 | 89,6% / 91,5% | 217 s | `20260928-161824_dev_Qwen_Qwen3-VL-8B-Instruct@a30` |

### Dev clean (26 bộ, gate M2)

| Cấu hình | Escape | Automation | False review | Field quan trọng | Dữ liệu bộ AUTO_PASS | Sao kê: dòng đúng / Ghi có | Gate | Run |
|---|---|---|---|---|---|---|---|---|
| Oracle (trần) | 0/12 (≤ 22,1%) | 53,8% | 0% | 100% | 100% / 0 trên 14 | 100% / 100% | – | `20260928-111032_dev_oracle` |
| Qwen2.5-VL-7B | 0/12 (≤ 22,1%) | 53,8% (= trần) | 0% | 100% | 98,9% / **4 trên 14** | 67,7% / 88,1% | Đạt | `20260928-111034_dev_Qwen_Qwen2.5-VL-7B-Instruct` |
| **Qwen3-VL-8B** | **0/12 (≤ 22,1%)** | 53,8% (= trần) | 0% | 99,7% | **100% / 0 trên 14** | **91,9% / 92,9%** | **Đạt** | `20260928-111035_dev_Qwen_Qwen3-VL-8B-Instruct` |
| Qwen3-VL-8B, A30 24 GB | 0/12 (≤ 22,1%) | 53,8% (= trần) | 0% | 99,7% | 100% / 0 trên 14 | 92,0% / 94,0% | Đạt | `20260928-163513_dev_Qwen_Qwen3-VL-8B-Instruct@a30` |

**Đổi GPU (RTX 5090 → A30).** Cùng model, prompt, code; A30 chạy vLLM 0.30 với `--max-model-len 8192 --gpu-memory-utilization 0.92 --max-num-seqs 8`. Mọi quyết định routing giống hệt 5090 (cùng 3 bộ sạch vào REVIEW, cùng E4 `dev_0007` = unknown); trích xuất chỉ lệch nhẹ (row recall 89,6% so với 87,7%, photo 98,0% so với 98,3%). A30 chậm hơn khoảng 1,35× (p95 217 s so với 161 s). Run test dùng A30, nên gate cho test là hai dòng A30 ở trên.

### So sánh chi tiết (toàn bộ dev)

| | Qwen2.5-VL-7B | Qwen3-VL-8B |
|---|---|---|
| Field accuracy clean / scan / photo | 99,4% / 98,3% / 96,6% | 99,8% / 99,5% / 98,3% |
| `cccd.ngay_cap` | 68,0% | 100% |
| `giao_dich` (lương từng tháng đúng) | 43/48 | 44/48 |
| Rule E1–E8: fail / unknown / **sót** | 26 / 1 / **0** | 26 / 1 / **0** |
| Near-miss không bị gắn cờ | 7/8 (N3 `dev_0041`: đọc CCCD "KIÊN" thành "KIỀN" → R1) | 8/8 |
| Bộ sạch vào REVIEW | 2: `dev_0035` (lương 2 lượt lệch nhau), `dev_0041` (R1, sai dấu) | 3: `dev_0001`, `dev_0013` (đọc lệch hàng: dòng lương dính số ghi nợ), `dev_0025` (chữ rác, xem dưới) |
| Sai lọt trong bộ AUTO_PASS | 10 bộ: 10 × thiếu `cccd.ngay_cap`, 1 lương đọc 26.558.000 thành 26.358.000 (cả 2 lượt cùng sai, confidence high), 1 "LAM SƠN" thành "LAM SON" | 0 |
| p95 mỗi bộ | 136 s | 161 s (≈ 1,2×) |

Cả hai E4 không bị bắt (`dev_0034` với 7B, `dev_0007` với 8B) là R4 = unknown vì sao kê đọc không chắc: bộ vẫn vào REVIEW, không có lỗi nào bị sót thật. `dev_0025` với 8B là bộ sạch nhưng model đọc ảnh photo ra chữ rác ("CÐNG TY … BကC NAM"); eval tính là false review, nhưng đưa sang người là hành vi đúng.

**Kết luận: chọn Qwen3-VL-8B.** Sau khi nới tự nhất quán (mục 6, #11), automation của hai model ngang nhau (46% và 44% là chênh 1 bộ trên 25, trong nhiễu). Khác biệt nằm ở dữ liệu đi thẳng vào hệ thống: 7B để lọt field sai ở 10/23 bộ auto-pass, 8B không có bộ nào. 8B cũng bền hơn khi ảnh xấu và không gắn cờ nhầm near-miss, đổi lại chậm hơn khoảng 1,2 lần.

### Chưa chạy

| Cấu hình | Mục đích |
|---|---|
| Qwen3-VL-8B qua API (FPT hoặc nhà cung cấp khác, nếu có) | Kiểm tra tự host có cho kết quả tương đương API không |
| Một model đóng (GPT-4o hoặc Gemini) | Mốc trên của khả năng đọc. Ưu tiên thấp: 8B đã chạm trần trên dev clean |

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
| 9 | Qwen2.5-VL-7B đọc bảng sao kê dài kém (row recall 68,6%), nhầm dấu tên và bỏ sót ngày cấp CCCD | Đổi sang Qwen3-VL-8B, giữ nguyên prompt v4 và code | Toàn bộ dev: automation 32% → 44%, false review 36% → 12%, row recall 68,6% → 87,7%, escape giữ 0/25 |
| 10 | Model đọc sai ngày lương (06/06 thành 30/05), cả 2 lượt cùng sai nên confidence high → một tháng có 2 khoản lương; R4 chia theo số tháng có lương nên lương TB bị đội ~50% (40tr thành 60tr), một bộ khai khống (E4) có thể lọt (`dev_0037`, 8B) | R4 = unknown khi một tháng có ≥ 2 khoản lương (`rules-v2`) | Chặn đường escape này; `dev_0037` giờ có thêm R4 = unknown. Không đổi automation trên dev (datagen chỉ sinh 1 khoản lương/tháng). Giới hạn: sao kê thật trả lương 2 lần/tháng cũng vào REVIEW |
| 11 | Tự nhất quán của `giao_dich` đòi 2 lượt khớp cả ~25 dòng, kể cả dòng ghi nợ không rule nào đọc (`dev_0035`: lương đúng mà vẫn confidence thấp) | So tự nhất quán trên lương từng tháng | Toàn bộ dev, 7B: automation 32% → 46%, false review 36% → 8%; 8B: gỡ `dev_0035`. Escape giữ 0/25 cả hai |
| 12 | Model trả chữ rác ở field không rule nào đọc (tên công ty trên đơn, ảnh photo) mà bộ vẫn AUTO_PASS → dữ liệu rác vào hệ thống (`dev_0025`, 8B) | Ký tự ngoài chữ Việt/ASCII → field lỗi `GARBLED`; router đưa bộ có `GARBLED` ở bất kỳ field nào sang REVIEW | `dev_0025` sang REVIEW. Chỉ bắt ký tự lạ, không bắt chữ Việt sai chính tả ("y té") |
| 13 | Eval gộp "rule không chắc → REVIEW" vào "sót", E4 recall 2/3 trông như lọt lỗi; và không đo dữ liệu của bộ auto-pass | Tách fail / unknown / pass; thêm chỉ số "Dữ liệu bộ AUTO_PASS" | Lộ ra điểm khác biệt thật giữa 7B và 8B (10 bộ auto-pass có field sai so với 0) |
| 14 | `latency_ms` mỗi bộ cộng thời gian gọi model 2 lần khi chạy thật (wall time của bước trích xuất + latency từng lần gọi) | Chỉ cộng latency từng lần gọi (có trong cache) | 8B không chậm 2,3× như báo trước mà ≈ 1,2× (161 s so với 136 s) |

## 7. Còn lại sau M2

- **Model đọc sai mà tự tin.** Tự nhất quán không bắt được lỗi khi cả 2 lượt cùng sai (7B: 26.558.000 thành 26.358.000; 8B: ngày lương 06/06 thành 30/05). R4 giờ chặn trường hợp lệch tháng; lệch số tiền nhỏ vẫn lọt nếu không đổi quyết định. Hướng thử: lượt 2 dùng biến thể ảnh khác mạnh hơn (crop theo bảng) để hai lượt ít cùng sai.
- **Sao kê đọc lệch hàng** (8B: `dev_0001`, `dev_0013`): số tiền của dòng ghi nợ bên cạnh dính vào dòng lương. Code từ chối vì mơ hồ (đúng), nhưng tốn automation.
- **Latency p95 161 s/bộ với 8B** (8 bộ song song trên một GPU). Phần lớn nằm ở sao kê (output dài, 2 lượt). Hướng giảm: chạy song song các giấy tờ trong một bộ; tắt tự nhất quán chỉ khi escape dev không tăng.
- **Chi phí tự host** chưa quy về $/bộ; cần ghi giá thuê GPU/giờ và thời gian chạy.
- Dev chỉ có 25 bộ sạch: chênh 1 bộ là 4 điểm automation. Kết luận giữa hai model dựa trên chỉ số dữ liệu auto-pass (10 so với 0), không dựa trên automation.
