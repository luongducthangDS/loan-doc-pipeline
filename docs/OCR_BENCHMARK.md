# OCR vs VLM benchmark

50 dev bundles (249 image files), EasyOCR 1.7.2 (vi+en, CPU) vs `20260928-164923_dev_Qwen_Qwen3-VL-8B-Instruct@a30`. Truth = the exact string printed on the image (`fields_raw`).

## 1. Document type from OCR text

| Type | Files | Precision | Recall | F1 |
|---|---|---|---|---|
| cccd | 100 | 1.000 | 1.000 | 1.000 |
| don_vay | 50 | 1.000 | 0.980 | 0.990 |
| hdld | 49 | 1.000 | 1.000 | 1.000 |
| sao_ke | 50 | 1.000 | 0.960 | 0.980 |

Accuracy 0.988. Confusion (rows = truth):

| | cccd | don_vay | hdld | sao_ke | unknown |
|---|---|---|---|---|---|
| cccd | 100 | 0 | 0 | 0 | 0 |
| don_vay | 0 | 49 | 0 | 0 | 1 |
| hdld | 0 | 0 | 49 | 0 | 0 |
| sao_ke | 0 | 0 | 0 | 48 | 2 |

Misclassified files: `dev_0026/don_vay.jpg` (photo, → unknown), `dev_0037/sao_ke.jpg` (photo, → unknown), `dev_0049/sao_ke.jpg` (photo, → unknown)

## 2. Field transcription (string fields)

| System | Fields | CER | WER | Exact match |
|---|---|---|---|---|
| VLM (Qwen_Qwen3-VL-8B-Instruct@a30) | 1535 | 0.007 | 0.016 | 96.5% |
| EasyOCR, oracle-aligned (best case) | 1535 | 0.055 | 0.173 | 65.7% |

By augmentation:

| Augment | VLM CER | VLM exact | OCR CER | OCR exact |
|---|---|---|---|---|
| clean | 0.008 | 96.7% | 0.032 | 71.9% |
| scan | 0.007 | 97.0% | 0.067 | 62.6% |
| photo | 0.006 | 95.6% | 0.094 | 54.8% |

Fields where OCR does worst:

| Field | OCR CER | OCR exact | VLM CER | VLM exact |
|---|---|---|---|---|
| don_vay.so_tien_vay | 0.207 | 2.0% | 0.007 | 92.0% |
| don_vay.ngay_ky | 0.204 | 44.0% | 0.186 | 44.0% |
| hdld.muc_luong | 0.123 | 14.3% | 0.000 | 100.0% |
| don_vay.thu_nhap_thang | 0.105 | 32.0% | 0.021 | 72.0% |
| don_vay.dia_chi | 0.098 | 20.0% | 0.001 | 98.0% |
| don_vay.muc_dich | 0.084 | 66.0% | 0.002 | 98.0% |
| sao_ke.ky_den | 0.083 | 29.2% | 0.000 | 100.0% |
| sao_ke.ky_tu | 0.079 | 35.4% | 0.000 | 100.0% |

## 3. Rules-based extraction from OCR (fixed-pattern fields)

| Field | n | OCR + regex exact | VLM exact |
|---|---|---|---|
| cccd.so_cccd | 50 | 100.0% | 100.0% |
| don_vay.so_cccd | 50 | 100.0% | 100.0% |
| don_vay.so_dien_thoai | 50 | 100.0% | 100.0% |
| sao_ke.so_tk | 48 | 89.6% | 100.0% |

## Reading this

- The oracle row is the best OCR can do: it is handed the right line. A real OCR pipeline must still locate
  each field (layout rules or a key-value model) and loses more on top of these numbers.
- Section 3 is the realistic OCR pipeline for the few fields with a fixed pattern.
- Data is synthetic (rendered forms + scan/photo augmentation); real scans are harder for both systems.
