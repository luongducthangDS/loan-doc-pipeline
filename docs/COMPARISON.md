<!-- Bản chụp của reports/comparison.md (reports/ không commit). Sinh lại: make compare SPLIT=dev, rồi chép sang đây. -->

# So sánh biến thể — `dev`

- Bộ lọc: `augment=None limit=None`; rules: `rules-v2/thr-v1`
- Baseline paired: `20260928-164923_dev_Qwen_Qwen3-VL-8B-Instruct@a30`
- Nguồn: 12 run khớp, gộp còn 5 biến thể (giữ run mới nhất mỗi cấu hình).

- Bỏ qua 8 run khác rules/thresholds (mặc định chỉ so trên `rules-v2/thr-v1`, dùng `--rules all` để xem tất cả).
- Run cũ không ghi `self_consistency`/`preprocess`; giá trị suy ra từ thresholds được đánh dấu ≈, còn lại là `?`.
- Chi phí $0.0000 nghĩa là chưa cấu hình giá (hoặc self-host), không phải miễn phí.
- OCR $0 là chi phí API, chưa gồm CPU. OCR chỉ một lượt độc lập; không dùng đọc lại cùng ảnh làm bằng chứng tự nhất quán.
- Calls/bộ đếm lượt trích xuất, không gồm LLM điều phối. Latency dùng thời gian inference lưu trong cache, không phải wall time lần replay; cache OCR được xây với mức song song khác nhau, không dùng p95 này để kết luận tốc độ hơn VLM.
- Có run escape 0 trên dev: dev chưa đủ để kết luận an toàn, hãy đọc cận trên 95% và so sánh trên bộ stress; test đóng băng.

## Bảng chính

| Mã | Biến thể | n | Rules | Escape | Cận trên 95% | Automation | False review | Field acc | Critical acc | Calls/bộ | $/bộ | $/auto-pass | p95 (ms) | Run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | B0 oracle (trần tầng rule) | 50 | `rules-v2/thr-v1` | 0.0% | 11.3% | 50.0% | 0.0% | 100.0% | 100.0% | 7.88 | $0.0000 | $0.0000 | 1 | `20260928-111027_dev_oracle (+2)` |
| B1 | B1 ocr · workflow, EasyOCR + anchor (CPU, đọc lại không độc lập) | 50 | `rules-v2/thr-v1` | 0.0% | 11.3% | 8.0% | 84.0% | 72.3% | 82.0% | 4.98 | $0.0000 | $0.0000 | 248708 | `20261113-170224_dev_ocr` |
| B3 | B3 Qwen/Qwen2.5-VL-7B-Instruct · workflow, 2 lượt≈ | 50 | `rules-v2/thr-v1` | 0.0% | 11.3% | 46.0% | 8.0% | 98.5% | 99.0% | 9.96 | $0.0000 | $0.0000 | 136435 | `20260928-111029_dev_Qwen_Qwen2.5-VL-7B-Instruct (+2)` |
| B3 | B3 Qwen/Qwen3-VL-8B-Instruct · workflow, 2 lượt≈ | 50 | `rules-v2/thr-v1` | 0.0% | 11.3% | 44.0% | 12.0% | 99.4% | 99.3% | 9.96 | $0.0000 | $0.0000 | 161133 | `20260928-111031_dev_Qwen_Qwen3-VL-8B-Instruct (+2)` |
| B3 | B3 Qwen/Qwen3-VL-8B-Instruct@a30 · workflow, 2 lượt≈ | 50 | `rules-v2/thr-v1` | 0.0% | 11.3% | 44.0% | 12.0% | 99.3% | 99.3% | 9.96 | $0.0000 | $0.0000 | 217338 | `20260928-164923_dev_Qwen_Qwen3-VL-8B-Instruct@a30 (+1)` |

Không tính lại metric: mọi số đọc từ `metrics.json` của run gốc. `$/auto-pass` = `$/bộ ÷ automation rate`.

## Field accuracy theo augment

| Biến thể | clean | scan | photo |
|---|---|---|---|
| B0 oracle (trần tầng rule) | 100.0% | 100.0% | 100.0% |
| B1 ocr · workflow, EasyOCR + anchor (CPU, đọc lại không độc lập) | 82.5% | 67.7% | 54.0% |
| B3 Qwen/Qwen2.5-VL-7B-Instruct · workflow, 2 lượt≈ | 99.4% | 98.3% | 96.6% |
| B3 Qwen/Qwen3-VL-8B-Instruct · workflow, 2 lượt≈ | 99.8% | 99.5% | 98.3% |
| B3 Qwen/Qwen3-VL-8B-Instruct@a30 · workflow, 2 lượt≈ | 99.8% | 99.5% | 98.0% |

## So với baseline (cùng bộ)

| Biến thể | Bộ chung | Cùng route | Sửa | Làm hỏng | Escape baseline→variant | False review baseline→variant | Đổi route |
|---|---|---|---|---|---|---|---|
| B0 oracle (trần tầng rule) | 50 | 47 | 3 | 0 | 0→0 | 3→0 | RV→AP 3 |
| B1 ocr · workflow, EasyOCR + anchor (CPU, đọc lại không độc lập) | 50 | 32 | 0 | 18 | 0→0 | 3→21 | AP→RV 18 |
| B3 Qwen/Qwen2.5-VL-7B-Instruct · workflow, 2 lượt≈ | 50 | 45 | 3 | 2 | 0→0 | 3→2 | RV→AP 3; AP→RV 2 |
| B3 Qwen/Qwen3-VL-8B-Instruct · workflow, 2 lượt≈ | 50 | 50 | 0 | 0 | 0→0 | 3→3 | — |

- **Sửa**: baseline sai route, variant đúng. **Làm hỏng**: baseline đúng, variant sai.
- Escape/False review đếm trên các bộ chung có `expected_route` trong manifest.

## Cách đọc

- Xếp hạng từ điển: escape (+ cận trên) → automation → cost. Tăng escape là loại, bất kể automation.
- Muốn quy kết tác động của một thay đổi, cần giữ các trục khác cố định; bảng nhiều phương án không tự chứng minh quan hệ nhân quả.
- Test đã đóng băng và đã chạy: không chạy lại để chỉnh biến thể; mọi tinh chỉnh mới chỉ trên dev.
