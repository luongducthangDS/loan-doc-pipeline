"""Eval 3 tầng: trích xuất, rule, routing end-to-end (spec mục 9).

    python -m loanpipe.evaluate --split dev --extractor oracle
    -> reports/<run_id>/{report.md, metrics.json, errors.csv, traces/*.json} + reports/runs.csv

Test set chỉ chạy MỘT lần cho mỗi phiên bản cuối. Mọi tinh chỉnh làm trên dev.
Thay đổi nào làm tăng escape rate so với run trước thì bị loại, dù automation rate có tăng.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from loanpipe import normalize as n
from loanpipe.config import load_rules, load_thresholds
from loanpipe.extract import get_extractor
from loanpipe.pipeline import bundle_input_from_manifest, run_bundle
from loanpipe.schemas import ERROR_RULE, DocType, ErrorCode, field_kinds

ROUTES = ["AUTO_PASS", "REVIEW", "REQUEST_MORE"]
_json = TypeAdapter(Any)


# --- Thống kê ------------------------------------------------------------------

def upper_bound_95(k: int, n_: int) -> float:
    """Cận trên một phía 95% (Clopper–Pearson) của tỉ lệ khi quan sát k/n. k=0 -> 1 - 0.05^(1/n) ≈ 3/n."""
    if n_ == 0:
        return 1.0
    if k >= n_:
        return 1.0

    def cdf(p: float) -> float:
        return sum(math.comb(n_, i) * p**i * (1 - p) ** (n_ - i) for i in range(k + 1))

    lo, hi = k / n_, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > 0.05 else (lo, mid)
    return hi


def _rate(k: int, n_: int) -> float | None:
    return k / n_ if n_ else None


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


# --- So khớp field với ground truth -----------------------------------------------

def gt_value(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == "name":
        return n.normalize_name(v)
    if kind == "text":
        return n.clean_text(v)
    if kind == "transactions":
        return [{**g, "mo_ta": n.clean_text(g["mo_ta"])} for g in v]
    return v


def field_rows(entry: dict, trace: dict) -> list[dict]:
    pred = {e["doc_id"]: e["fields"] for e in trace["extractions"]}
    rows = []
    for d in entry["docs"]:
        dt = DocType(d["type"])
        for name, kind in field_kinds(dt).items():
            p = pred.get(d["doc_id"], {}).get(name)
            gt = _json.dump_python(gt_value(kind, d["fields_gt"][name]), mode="json")
            pv = p["value"] if p else None
            rows.append({"bundle_id": entry["bundle_id"], "doc_type": dt.value, "field": name,
                         "layout": entry["layout_ids"][dt.value], "augment": entry["augment"],
                         "ok": pv == gt, "schema_error": bool(p and p["error"]),
                         "pred": pv, "gt": gt, "raw": p["raw"] if p else None})
    return rows


# --- Metric ---------------------------------------------------------------------------

def compute_metrics(entries: list[dict], traces: dict[str, dict], thr) -> tuple[dict, list[dict]]:
    errors_csv: list[dict] = []
    frows = [r for e in entries if e["bundle_id"] in traces for r in field_rows(e, traces[e["bundle_id"]])]

    def acc(rows):
        return {"n": len(rows), "acc": _rate(sum(r["ok"] for r in rows), len(rows))}

    by = defaultdict(list)
    for r in frows:
        by[("field", f"{r['doc_type']}.{r['field']}")].append(r)
        by[("augment", r["augment"])].append(r)
        by[("layout", f"{r['doc_type']}:{r['layout']}")].append(r)
        if thr.is_critical(r["doc_type"], r["field"]):
            by[("critical", "all")].append(r)
        if not r["ok"]:
            errors_csv.append({"bundle_id": r["bundle_id"], "kind": "field",
                               "detail": f"{r['doc_type']}.{r['field']}", "expected": json.dumps(r["gt"], ensure_ascii=False)[:200],
                               "actual": json.dumps(r["pred"], ensure_ascii=False)[:200]})
    extraction = {
        "field_accuracy": acc(frows),
        "critical_field_accuracy": acc(by[("critical", "all")]),
        "schema_error_rate": _rate(sum(r["schema_error"] for r in frows), len(frows)),
        "by_field": {k: acc(v) for (g, k), v in sorted(by.items()) if g == "field"},
        "by_augment": {k: acc(v) for (g, k), v in sorted(by.items()) if g == "augment"},
        "by_layout": {k: acc(v) for (g, k), v in sorted(by.items()) if g == "layout"},
    }

    # Rule: recall theo mã lỗi, precision trên bộ sạch (tách near-miss)
    recall: dict[str, dict] = {}
    for code in ErrorCode:
        rule = ERROR_RULE[code]
        hits = [e for e in entries if any(x["code"] == code.value for x in e["injected_errors"])]
        caught = [e for e in hits if _status(traces[e["bundle_id"]], rule) == "fail"]
        recall[code.value] = {"rule": rule, "n": len(hits), "caught": len(caught),
                              "recall": _rate(len(caught), len(hits))}
        for e in hits:
            if e not in caught:
                errors_csv.append({"bundle_id": e["bundle_id"], "kind": "rule_miss", "detail": f"{code.value}->{rule}",
                                   "expected": "fail", "actual": _status(traces[e["bundle_id"]], rule)})
    clean = [e for e in entries if not e["injected_errors"]]

    def flagged(e):
        return [c["rule_id"] for c in traces[e["bundle_id"]]["checks"] if c["status"] == "fail"]

    plain = [e for e in clean if not e["near_miss"]]
    near = defaultdict(list)
    for e in clean:
        for x in e["near_miss"]:
            near[x["code"]].append(e)
    for e in clean:
        if flagged(e):
            errors_csv.append({"bundle_id": e["bundle_id"], "kind": "false_flag",
                               "detail": ",".join(x["code"] for x in e["near_miss"]) or "clean",
                               "expected": "no fail", "actual": ",".join(flagged(e))})
    rules = {
        "recall_by_error": recall,
        "clean_not_flagged": _rate(sum(not flagged(e) for e in plain), len(plain)),
        "near_miss_not_flagged": {k: {"n": len(v), "rate": _rate(sum(not flagged(e) for e in v), len(v))}
                                  for k, v in sorted(near.items())},
    }

    # End-to-end
    conf = {a: {b: 0 for b in ROUTES} for a in ROUTES}
    for e in entries:
        actual = traces[e["bundle_id"]]["decision"]["route"]
        conf[e["expected_route"]][actual] += 1
        if actual != e["expected_route"]:
            errors_csv.append({"bundle_id": e["bundle_id"], "kind": "route", "detail": ";".join(
                traces[e["bundle_id"]]["decision"]["reasons"]), "expected": e["expected_route"], "actual": actual})
    bad = [e for e in entries if e["expected_route"] != "AUTO_PASS"]
    escaped = sum(traces[e["bundle_id"]]["decision"]["route"] == "AUTO_PASS" for e in bad)
    good = [e for e in entries if e["expected_route"] == "AUTO_PASS"]
    false_review = sum(traces[e["bundle_id"]]["decision"]["route"] != "AUTO_PASS" for e in good)
    auto = sum(t["decision"]["route"] == "AUTO_PASS" for t in traces.values())
    end_to_end = {
        "n_bundles": len(entries), "n_with_errors": len(bad), "n_clean": len(good),
        "escape_rate": _rate(escaped, len(bad)), "escaped": escaped,
        "escape_rate_upper95": upper_bound_95(escaped, len(bad)),
        "false_review_rate": _rate(false_review, len(good)),
        "automation_rate": _rate(auto, len(entries)),
        "confusion": conf,
    }

    lat = sorted(t["latency_ms"] for t in traces.values())
    ops = {
        "latency_p50_ms": statistics.median(lat) if lat else None,
        "latency_p95_ms": lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)] if lat else None,
        "calls_per_bundle": statistics.mean(t["n_calls"] for t in traces.values()) if traces else None,
        "cost_per_bundle_usd": statistics.mean(t["cost_usd"] for t in traces.values()) if traces else None,
        "docs_extract_failed": sum(len(t.get("extract_errors", {})) for t in traces.values()),
    }
    return {"extraction": extraction, "rules": rules, "end_to_end": end_to_end, "ops": ops}, errors_csv


def _status(trace: dict, rule_id: str) -> str:
    return next(c["status"] for c in trace["checks"] if c["rule_id"] == rule_id)


# --- Báo cáo ----------------------------------------------------------------------------

def render_report(meta: dict, m: dict, prev: dict | None) -> str:
    e2e, ext, rl, ops = m["end_to_end"], m["extraction"], m["rules"], m["ops"]
    L = [f"# Eval run `{meta['run_id']}`", "",
         "| | |", "|---|---|"]
    L += [f"| {k} | `{v}` |" for k, v in meta.items() if k != "run_id"]
    L += ["", "## End-to-end", "",
          f"- **Escape rate**: {_pct(e2e['escape_rate'])} ({e2e['escaped']}/{e2e['n_with_errors']} bộ có lỗi bị "
          f"auto-pass); cận trên 95%: **{_pct(e2e['escape_rate_upper95'])}**",
          f"- **Automation rate**: {_pct(e2e['automation_rate'])}",
          f"- **False review rate**: {_pct(e2e['false_review_rate'])} (bộ sạch bị đẩy sang review)",
          "- Baseline B0 (mọi bộ vào REVIEW): automation 0%, escape 0%.", "",
          "| expected \\ actual | " + " | ".join(ROUTES) + " |", "|---|" + "---|" * len(ROUTES)]
    L += [f"| {a} | " + " | ".join(str(e2e["confusion"][a][b]) for b in ROUTES) + " |" for a in ROUTES]
    if prev:
        pe = prev["end_to_end"]
        d_esc = (e2e["escape_rate"] or 0) - (pe["escape_rate"] or 0)
        d_auto = (e2e["automation_rate"] or 0) - (pe["automation_rate"] or 0)
        verdict = "**LOẠI: escape rate tăng**" if d_esc > 0 else "không tăng escape rate"
        L += ["", f"So với run trước `{prev['_run_id']}`: escape {d_esc:+.1%}, automation {d_auto:+.1%} → {verdict}"]
    L += ["", "## Rule", "", "| Mã lỗi | Rule | n | Bắt được | Recall |", "|---|---|---|---|---|"]
    L += [f"| {c} | {r['rule']} | {r['n']} | {r['caught']} | {_pct(r['recall'])} |"
          for c, r in rl["recall_by_error"].items()]
    L += ["", f"Bộ sạch không bị gắn cờ: {_pct(rl['clean_not_flagged'])}", "",
          "| Near-miss | n | Không bị gắn cờ |", "|---|---|---|"]
    L += [f"| {k} | {v['n']} | {_pct(v['rate'])} |" for k, v in rl["near_miss_not_flagged"].items()]
    L += ["", "## Trích xuất", "",
          f"- Field accuracy: {_pct(ext['field_accuracy']['acc'])} (n={ext['field_accuracy']['n']})",
          f"- Field quan trọng: {_pct(ext['critical_field_accuracy']['acc'])}",
          f"- Tỉ lệ lỗi định dạng/schema: {_pct(ext['schema_error_rate'])}", "",
          "| Nhóm | n | Accuracy |", "|---|---|---|"]
    for grp in ("by_augment", "by_layout", "by_field"):
        L += [f"| {grp[3:]}: {k} | {v['n']} | {_pct(v['acc'])} |" for k, v in ext[grp].items()]
    L += ["", "## Vận hành", "",
          f"- Latency p50 / p95: {ops['latency_p50_ms']} / {ops['latency_p95_ms']} ms",
          f"- Số lần gọi model mỗi bộ: {ops['calls_per_bundle']}",
          f"- Chi phí mỗi bộ: ${ops['cost_per_bundle_usd']:.4f}",
          f"- Giấy tờ trích xuất lỗi (API/JSON, sau retry): {ops['docs_extract_failed']}", ""]
    return "\n".join(L)


def git_commit() -> str:
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                           check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                               text=True).stdout.strip()
        return h + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--extractor", default="oracle")
    ap.add_argument("--data", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--no-file-check", action="store_true", help="bỏ kiểm ảnh (khi sinh bằng --no-images)")
    ap.add_argument("--augment", choices=["clean", "scan", "photo"], help="chỉ chạy các bộ có mức này (gate M2: clean)")
    ap.add_argument("--limit", type=int, help="chỉ chạy N bộ đầu (spike, tiết kiệm chi phí API)")
    ap.add_argument("--workers", type=int, default=1, help="số bộ chạy song song (VLM qua API)")
    args = ap.parse_args()

    split_dir = args.data / args.split
    entries = [json.loads(line) for line in (split_dir / "manifest.jsonl").read_text("utf-8").splitlines()]
    entries = [e for e in entries if not args.augment or e["augment"] == args.augment][:args.limit]
    rules_cfg, thr = load_rules(), load_thresholds()
    kw = {"manifest": entries} if args.extractor == "oracle" else {}
    extractor = get_extractor(args.extractor, **kw)

    run_id = f"{datetime.now():%Y%m%d-%H%M%S}_{args.split}_{extractor.name}"
    out = args.out / run_id
    (out / "traces").mkdir(parents=True)
    def one(e: dict) -> dict:
        t = run_bundle(bundle_input_from_manifest(e, split_dir), extractor, rules_cfg, thr,
                       check_files=not args.no_file_check)
        (out / "traces" / f"{e['bundle_id']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), "utf-8")
        return t

    with ThreadPoolExecutor(args.workers) as pool:
        traces = {e["bundle_id"]: t for e, t in zip(entries, pool.map(one, entries))}

    metrics, errs = compute_metrics(entries, traces, thr)
    meta = {"run_id": run_id, "split": args.split, "filter": f"augment={args.augment} limit={args.limit}",
            "n_bundles": len(entries), "model": extractor.name,
            "prompt_version": extractor.prompt_version, "rules_version": rules_cfg.version,
            "thresholds_version": thr.version, "git_commit": git_commit()}
    index = args.out / "runs.csv"
    prev = None
    if index.exists():
        rows = [r for r in csv.DictReader(index.open(encoding="utf-8")) if r["split"] == args.split]
        if rows and (args.out / rows[-1]["run_id"] / "metrics.json").exists():
            prev = json.loads((args.out / rows[-1]["run_id"] / "metrics.json").read_text("utf-8"))
            prev["_run_id"] = rows[-1]["run_id"]

    (out / "metrics.json").write_text(json.dumps({"meta": meta, **metrics}, ensure_ascii=False, indent=2), "utf-8")
    (out / "report.md").write_text(render_report(meta, metrics, prev), "utf-8")
    with (out / "errors.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bundle_id", "kind", "detail", "expected", "actual"])
        w.writeheader()
        w.writerows(errs)
    e2e = metrics["end_to_end"]
    row = {**meta, "escape_rate": e2e["escape_rate"], "escape_upper95": round(e2e["escape_rate_upper95"], 4),
           "automation_rate": e2e["automation_rate"], "false_review_rate": e2e["false_review_rate"],
           "field_accuracy": metrics["extraction"]["field_accuracy"]["acc"]}
    new = not index.exists()
    with index.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"{run_id}: escape {_pct(e2e['escape_rate'])} (cận trên {_pct(e2e['escape_rate_upper95'])}), "
          f"automation {_pct(e2e['automation_rate'])}, false review {_pct(e2e['false_review_rate'])}, "
          f"field acc {_pct(metrics['extraction']['field_accuracy']['acc'])} -> {out / 'report.md'}")
    if prev and (e2e["escape_rate"] or 0) > (prev["end_to_end"]["escape_rate"] or 0):
        print("CẢNH BÁO: escape rate tăng so với run trước -> thay đổi này bị loại.")


if __name__ == "__main__":
    main()
