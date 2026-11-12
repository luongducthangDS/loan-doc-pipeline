"""Traditional OCR (EasyOCR) vs the VLM on the same dev bundles.

    pip install -r requirements-ocr.txt      # see the file: CPU torch first, then easyocr
    python scripts/ocr_benchmark.py --vlm-run reports/20260928-164923_dev_Qwen_Qwen3-VL-8B-Instruct@a30

Three measurements, all against the manifest (fields_raw = the exact string printed on the image):
  1. Document-type classification from OCR text (keyword rules), per file: precision / recall / F1.
     The VLM pipeline is told the type, so this is the step an OCR intake would add.
  2. Field transcription CER / WER / exact match:
       VLM          = the `raw` string the VLM returned for that field (from the run's traces)
       OCR oracle   = the OCR line window closest to the truth (best case: assumes perfect field location)
       OCR + regex  = what a rules-based extractor actually gets, for fields with a fixed pattern
  3. All of the above split by augmentation (clean / scan / photo).

Keywords and regexes were written by looking only at 8 bundles generated with another seed
(`python -m datagen.build --seed 7 --split dev --n 8 --out <tmp>`), never at the dev images scored here.
OCR output is cached in .cache/ocr (EasyOCR on CPU: 10-30 s per image).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "ocr"
TYPES = ["cccd", "don_vay", "hdld", "sao_ke"]
# Header phrases seen on the design set, diacritics stripped (OCR drops them often).
KEYWORDS = {
    "cccd": ["can cuoc", "nhan dang", "personal identification", "dac diem"],
    "don_vay": ["de nghi vay", "vay von", "phuong an tra no"],
    "hdld": ["hop dong lao dong", "nguoi lao dong", "nguoi su dung lao dong"],
    "sao_ke": ["sao ke", "so du", "ghi co", "ghi no"],
}
# Fields a rules-based extractor can find by pattern alone.
PATTERNS = {
    ("cccd", "so_cccd"): r"(?<!\d)\d{12}(?!\d)",
    ("don_vay", "so_cccd"): r"(?<!\d)\d{12}(?!\d)",
    ("don_vay", "so_dien_thoai"): r"(?<!\d)0\d{9}(?!\d)",
    ("sao_ke", "so_tk"): r"(?<!\d)\d{9,14}(?!\d)",
}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).lower().strip()


def ocr(reader, path: Path) -> list[str]:
    key = hashlib.sha1(path.read_bytes()).hexdigest()[:24]
    hit = CACHE / f"{key}.json"
    if hit.exists():
        return json.loads(hit.read_text("utf-8"))
    lines = reader.readtext(str(path), detail=0, paragraph=False)
    CACHE.mkdir(parents=True, exist_ok=True)
    hit.write_text(json.dumps(lines, ensure_ascii=False), "utf-8")
    return lines


def classify(lines: list[str]) -> str:
    text = fold(" ".join(lines))
    scores = {t: sum(k in text for k in kws) for t, kws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def cer(truth: str, pred: str) -> float:
    return Levenshtein.distance(truth, pred) / max(len(truth), 1)


def wer(truth: str, pred: str) -> float:
    t = truth.split()
    return Levenshtein.distance(t, pred.split()) / max(len(t), 1)


def oracle_window(truth: str, lines: list[str]) -> str:
    """Best-case OCR string for a field: the line, line pair, or 'label: value' tail closest to the truth."""
    cands = list(lines) + [a + " " + b for a, b in zip(lines, lines[1:])]
    cands += [c.split(":", 1)[1].strip() for c in cands if ":" in c]
    return min(cands, key=lambda c: cer(truth, c)) if cands else ""


def agg(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    return {"n": n, "CER": sum(r["cer"] for r in rows) / n, "WER": sum(r["wer"] for r in rows) / n,
            "exact": sum(r["exact"] for r in rows) / n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic" / "dev")
    ap.add_argument("--vlm-run", type=Path, required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "OCR_BENCHMARK.md")
    args = ap.parse_args()

    import easyocr  # heavy import only when actually running

    reader = easyocr.Reader(["vi", "en"], gpu=False, verbose=False)
    manifest = [json.loads(x) for x in (args.data / "manifest.jsonl").read_text("utf-8").splitlines()]
    manifest = manifest[: args.limit] if args.limit else manifest

    cls_rows, field_rows, regex_rows = [], defaultdict(list), []
    for i, e in enumerate(manifest):
        trace_p = args.vlm_run / "traces" / f"{e['bundle_id']}.json"
        trace = json.loads(trace_p.read_text("utf-8")) if trace_p.exists() else {"extractions": []}
        vlm = {(x["doc_type"], x["doc_id"]): x["fields"] for x in trace["extractions"]}
        for d in e["docs"]:
            pages = [ocr(reader, args.data / f) for f in d["files"]]
            for f, lines in zip(d["files"], pages):
                cls_rows.append({"truth": d["type"], "pred": classify(lines), "augment": e["augment"], "file": f})
            for name, info in d.get("fields_raw", {}).items():
                truth = info.get("raw")
                if not isinstance(truth, str) or not truth.strip() or name == "giao_dich":
                    continue  # transaction tables are scored by the main eval, not here
                lines = pages[min(int(info.get("page", 1)), len(pages)) - 1]
                o = oracle_window(truth, lines)
                v = ((vlm.get((d["type"], d["doc_id"])) or {}).get(name) or {}).get("raw") or ""
                for system, pred in (("ocr_oracle", o), ("vlm", v)):
                    field_rows[system].append({"cer": cer(truth, pred), "wer": wer(truth, pred), "exact": pred == truth,
                                               "augment": e["augment"], "field": f"{d['type']}.{name}"})
                pat = PATTERNS.get((d["type"], name))
                if pat:
                    found = re.findall(pat, re.sub(r"[ .]", "", " ".join(lines)))
                    gold = re.sub(r"\D", "", truth)
                    regex_rows.append({"field": f"{d['type']}.{name}", "augment": e["augment"],
                                       "found": bool(found), "exact": bool(found) and found[0] == gold,
                                       "vlm_exact": re.sub(r"\D", "", v) == gold})
        print(f"{i + 1}/{len(manifest)} {e['bundle_id']}", flush=True)

    # ---- report ----
    L = ["# OCR vs VLM benchmark", "",
         f"{len(manifest)} dev bundles ({sum(1 for _ in cls_rows)} image files), EasyOCR 1.7.2 (vi+en, CPU) vs "
         f"`{args.vlm_run.name}`. Truth = the exact string printed on the image (`fields_raw`).", "",
         "## 1. Document type from OCR text", ""]
    labels = TYPES + ["unknown"]
    L += ["| Type | Files | Precision | Recall | F1 |", "|---|---|---|---|---|"]
    for t in TYPES:
        tp = sum(r["truth"] == t and r["pred"] == t for r in cls_rows)
        pp = sum(r["pred"] == t for r in cls_rows)
        ap_ = sum(r["truth"] == t for r in cls_rows)
        p, rc = (tp / pp if pp else 0.0), (tp / ap_ if ap_ else 0.0)
        L.append(f"| {t} | {ap_} | {p:.3f} | {rc:.3f} | {2 * p * rc / (p + rc) if p + rc else 0:.3f} |")
    acc = sum(r["truth"] == r["pred"] for r in cls_rows) / len(cls_rows)
    L += ["", f"Accuracy {acc:.3f}. Confusion (rows = truth):", "", "| | " + " | ".join(labels) + " |",
          "|---|" + "---|" * len(labels)]
    for t in TYPES:
        L.append(f"| {t} | " + " | ".join(str(sum(r["truth"] == t and r["pred"] == p for r in cls_rows)) for p in labels) + " |")
    wrong = [r for r in cls_rows if r["truth"] != r["pred"]]
    if wrong:
        L += ["", "Misclassified files: " + ", ".join(f"`{r['file']}` ({r['augment']}, → {r['pred']})" for r in wrong[:15])]

    L += ["", "## 2. Field transcription (string fields)", "",
          "| System | Fields | CER | WER | Exact match |", "|---|---|---|---|---|"]
    names = {"vlm": f"VLM ({args.vlm_run.name.split('_dev_')[-1]})", "ocr_oracle": "EasyOCR, oracle-aligned (best case)"}
    for s in ("vlm", "ocr_oracle"):
        a = agg(field_rows[s])
        L.append(f"| {names[s]} | {a['n']} | {a['CER']:.3f} | {a['WER']:.3f} | {a['exact']:.1%} |")
    L += ["", "By augmentation:", "", "| Augment | VLM CER | VLM exact | OCR CER | OCR exact |", "|---|---|---|---|---|"]
    for aug in ("clean", "scan", "photo"):
        v = agg([r for r in field_rows["vlm"] if r["augment"] == aug])
        o = agg([r for r in field_rows["ocr_oracle"] if r["augment"] == aug])
        if v["n"]:
            L.append(f"| {aug} | {v['CER']:.3f} | {v['exact']:.1%} | {o['CER']:.3f} | {o['exact']:.1%} |")
    worst = sorted({r["field"] for r in field_rows["ocr_oracle"]},
                   key=lambda f: -agg([r for r in field_rows["ocr_oracle"] if r["field"] == f])["CER"])[:8]
    L += ["", "Fields where OCR does worst:", "", "| Field | OCR CER | OCR exact | VLM CER | VLM exact |", "|---|---|---|---|---|"]
    for f in worst:
        o = agg([r for r in field_rows["ocr_oracle"] if r["field"] == f])
        v = agg([r for r in field_rows["vlm"] if r["field"] == f])
        L.append(f"| {f} | {o['CER']:.3f} | {o['exact']:.1%} | {v['CER']:.3f} | {v['exact']:.1%} |")

    L += ["", "## 3. Rules-based extraction from OCR (fixed-pattern fields)", "",
          "| Field | n | OCR + regex exact | VLM exact |", "|---|---|---|---|"]
    for f in sorted({r["field"] for r in regex_rows}):
        rs = [r for r in regex_rows if r["field"] == f]
        L.append(f"| {f} | {len(rs)} | {sum(r['exact'] for r in rs) / len(rs):.1%} | {sum(r['vlm_exact'] for r in rs) / len(rs):.1%} |")

    L += ["", "## Reading this", "",
          "- The oracle row is the best OCR can do: it is handed the right line. A real OCR pipeline must still locate",
          "  each field (layout rules or a key-value model) and loses more on top of these numbers.",
          "- Section 3 is the realistic OCR pipeline for the few fields with a fixed pattern.",
          "- Data is synthetic (rendered forms + scan/photo augmentation); real scans are harder for both systems."]
    args.out.write_text("\n".join(L) + "\n", "utf-8")
    (ROOT / "reports" / "ocr_benchmark.json").write_text(json.dumps({
        "classification_accuracy": acc, "fields": {s: agg(r) for s, r in field_rows.items()},
        "regex": {f: sum(r["exact"] for r in regex_rows if r["field"] == f) / max(1, sum(r["field"] == f for r in regex_rows))
                  for f in {r["field"] for r in regex_rows}}}, indent=2), "utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
