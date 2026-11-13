"""So sánh các biến thể eval trên cùng split, dựng từ reports/<run_id>/metrics.json + traces.

Không tính lại metric: đọc metrics.json để con số khớp report gốc. Paired diff đọc trace + manifest để
so route từng bộ với baseline; chỉ bộ có mặt trong cả hai run mới so được.

    python -m loanpipe.compare --split dev
    -> reports/comparison.md, reports/comparison.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from loanpipe.config import Thresholds, load_rules, load_thresholds

ROUTE_SHORT = {"AUTO_PASS": "AP", "REVIEW": "RV", "REQUEST_MORE": "RM"}
CODE_ORDER = {"B0": 0, "B1": 1, "B2": 2, "B3": 3, "B4": 4, "B5": 5, "B?": 6}
CSV_FIELDS = ["code", "variant", "model", "orchestration", "self_consistency", "preprocess",
              "n_bundles", "runs_grouped", "rules_version", "thresholds_version", "escape_rate",
              "escape_upper95", "automation_rate", "false_review_rate", "field_accuracy",
              "critical_field_accuracy", "calls_per_bundle", "cost_per_bundle_usd",
              "cost_per_autopass_usd", "latency_p95_ms", "git_commit", "run_id"]


@dataclass(frozen=True)
class Run:
    run_id: str
    meta: dict
    metrics: dict
    path: Path


def _pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def _num(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def _usd(x: float | None) -> str:
    return "—" if x is None else f"${x:.4f}"


def _orchestration(meta: dict) -> str:
    if meta.get("orchestration"):
        return meta["orchestration"]
    if "+agent:" in (meta.get("prompt_version") or "") or (meta.get("run_id") or "").endswith("_agent"):
        return "agent"
    return "workflow"


def _self_consistency(meta: dict, thr: Thresholds) -> tuple[bool | None, bool]:
    """(giá trị, có phải suy ra không). Run cũ không ghi field này: suy từ thresholds version."""
    if meta.get("self_consistency") is not None:
        return bool(meta["self_consistency"]), False
    if meta.get("thresholds_version") == thr.version:
        return thr.use_self_consistency, True
    return None, False


def _preprocess(meta: dict) -> str:
    return meta.get("preprocess") or "?"


def _code(meta: dict, thr: Thresholds) -> str:
    if _orchestration(meta) == "agent":
        return "B5"
    if meta.get("model") == "oracle":
        return "B0"
    if meta.get("model") == "ocr":
        return "B1"
    if _preprocess(meta) not in ("?", "off", "n/a", None):
        return "B4"
    return {True: "B3", False: "B2"}.get(_self_consistency(meta, thr)[0], "B?")


def _label(run: Run, thr: Thresholds) -> str:
    m = run.meta
    code = _code(m, thr)
    if m.get("model") == "oracle" and code == "B0":
        return f"{code} oracle (trần tầng rule)"
    if m.get("model") == "ocr":
        return f"{code} ocr · {_orchestration(m)}, EasyOCR + anchor (CPU, đọc lại không độc lập)"
    sc, inferred = _self_consistency(m, thr)
    sc_txt = {True: "2 lượt", False: "1 lượt", None: "?"}[sc] + ("≈" if inferred and sc is not None else "")
    pre = _preprocess(m)
    pre_txt = "" if pre in ("off", "n/a", "?") else f", {pre}"
    return f"{code} {m.get('model', '?')} · {_orchestration(m)}, {sc_txt}{pre_txt}"


def _variant_key(run: Run, thr: Thresholds) -> tuple:
    m = run.meta
    return (m.get("split"), m.get("filter"), m.get("model"), m.get("prompt_version"),
            _orchestration(m), _self_consistency(m, thr)[0], _preprocess(m),
            m.get("rules_version"), m.get("thresholds_version"), m.get("n_bundles"))


def load_runs(out: Path) -> tuple[list[Run], int]:
    runs, skipped = [], 0
    for path in sorted(out.glob("*/metrics.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            skipped += 1
            continue
        meta = data.get("meta") or {}
        if not meta.get("run_id"):
            skipped += 1
            continue
        runs.append(Run(meta["run_id"], meta, data, path.parent))
    return runs, skipped


def _dedupe(runs: list[Run], thr: Thresholds) -> list[tuple[Run, int]]:
    groups: dict[tuple, list[Run]] = defaultdict(list)
    for r in runs:
        groups[_variant_key(r, thr)].append(r)
    return [(max(rs, key=lambda r: r.run_id), len(rs)) for rs in groups.values()]


def _trace_routes(run_dir: Path) -> dict[str, str]:
    routes = {}
    for f in sorted((run_dir / "traces").glob("*.json")):
        try:
            route = (json.loads(f.read_text("utf-8")).get("decision") or {}).get("route")
        except (OSError, ValueError):
            continue
        if route:
            routes[f.stem] = route
    return routes


def _expected_routes(split_dir: Path) -> dict[str, str]:
    manifest = split_dir / "manifest.jsonl"
    if not manifest.exists():
        return {}
    out = {}
    for line in manifest.read_text("utf-8").splitlines():
        e = json.loads(line)
        if e.get("expected_route"):
            out[e["bundle_id"]] = e["expected_route"]
    return out


def _paired(base: dict[str, str], var: dict[str, str], expected: dict[str, str]) -> dict:
    common = sorted(set(base) & set(var))
    p = {"n": len(common), "same": 0, "fixes": 0, "breaks": 0, "expected_known": 0,
         "escape": [0, 0], "false_review": [0, 0], "transitions": Counter()}
    for b in common:
        exp = expected.get(b)
        if exp:
            p["expected_known"] += 1
            for i, routes in enumerate((base, var)):
                if routes[b] == "AUTO_PASS" and exp != "AUTO_PASS":
                    p["escape"][i] += 1
                if routes[b] != "AUTO_PASS" and exp == "AUTO_PASS":
                    p["false_review"][i] += 1
        if base[b] == var[b]:
            p["same"] += 1
            continue
        p["transitions"][(base[b], var[b])] += 1
        if exp:
            base_ok, var_ok = base[b] == exp, var[b] == exp
            p["fixes"] += var_ok and not base_ok
            p["breaks"] += base_ok and not var_ok
    return p


def _acc(ext: dict, key: str) -> float | None:
    v = ext.get(key) or {}
    return v.get("acc")


def _table(runs: list[tuple[Run, int]], thr: Thresholds) -> list[str]:
    L = ["| Mã | Biến thể | n | Rules | Escape | Cận trên 95% | Automation | False review | Field acc "
         "| Critical acc | Calls/bộ | $/bộ | $/auto-pass | p95 (ms) | Run |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r, grouped in runs:
        e2e, ext, ops = r.metrics.get("end_to_end") or {}, r.metrics.get("extraction") or {}, r.metrics.get("ops") or {}
        auto, cost = e2e.get("automation_rate"), ops.get("cost_per_bundle_usd")
        per_ap = cost / auto if cost is not None and auto else None
        grouped_txt = r.run_id if grouped == 1 else f"{r.run_id} (+{grouped - 1})"
        L.append(f"| {_code(r.meta, thr)} | {_label(r, thr)} | {r.meta.get('n_bundles') or e2e.get('n_bundles') or '—'} "
                 f"| `{r.meta.get('rules_version')}/{r.meta.get('thresholds_version')}` "
                 f"| {_pct(e2e.get('escape_rate'))} | {_pct(e2e.get('escape_rate_upper95'))} "
                 f"| {_pct(auto)} | {_pct(e2e.get('false_review_rate'))} "
                 f"| {_pct(_acc(ext, 'field_accuracy'))} | {_pct(_acc(ext, 'critical_field_accuracy'))} "
                 f"| {_num(ops.get('calls_per_bundle'))} | {_usd(cost)} | {_usd(per_ap)} "
                 f"| {_num(ops.get('latency_p95_ms'), 0)} | `{grouped_txt}` |")
    return L


def _paired_table(rows: list[tuple[Run, dict]], thr: Thresholds) -> list[str]:
    if not rows:
        return ["Không có cặp run nào cùng bộ để so route."]
    L = ["| Biến thể | Bộ chung | Cùng route | Sửa | Làm hỏng | Escape baseline→variant "
         "| False review baseline→variant | Đổi route |",
         "|---|---|---|---|---|---|---|---|"]
    for r, p in rows:
        moves = "; ".join(f"{ROUTE_SHORT.get(a, a)}→{ROUTE_SHORT.get(b, b)} {n}"
                          for (a, b), n in p["transitions"].most_common()) or "—"
        L.append(f"| {_label(r, thr)} | {p['n']} | {p['same']} | {p['fixes']} | {p['breaks']} "
                 f"| {p['escape'][0]}→{p['escape'][1]} | {p['false_review'][0]}→{p['false_review'][1]} "
                 f"| {moves} |")
    return L


def _augment_table(runs: list[tuple[Run, int]], thr: Thresholds) -> list[str]:
    rows = [(r, r.metrics.get("extraction", {}).get("by_augment") or {}) for r, _ in runs]
    rows = [(r, a) for r, a in rows if a]
    if not rows:
        return []
    cols = [k for k in ("clean", "scan", "photo") if any(k in a for _, a in rows)]
    cols += sorted({k for _, a in rows for k in a} - set(cols))
    L = ["| Biến thể | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for r, a in rows:
        L.append(f"| {_label(r, thr)} | " + " | ".join(_pct((a.get(k) or {}).get("acc")) for k in cols) + " |")
    return L


def _pick_baseline(runs: list[Run], thr: Thresholds, wanted: str | None) -> Run | None:
    if wanted:
        exact = next((r for r in runs if r.run_id == wanted), None)
        if exact:
            return exact
        matches = [r for r in runs if r.run_id.startswith(wanted)]
        if len(matches) != 1:
            raise ValueError(f"Baseline {wanted!r}: cần khớp đúng một run, tìm thấy {len(matches)}")
        return matches[0]
    references = [r for r in runs if _code(r.meta, thr) in ("B2", "B3")]
    workflows = [r for r in runs if r.meta.get("model") != "oracle" and _orchestration(r.meta) == "workflow"]
    pool = references or workflows or runs
    return max(pool, key=lambda r: r.run_id) if pool else None


def build_comparison(out: Path, split: str, data: Path, filter_: str = "augment=None limit=None",
                     baseline_id: str | None = None, rules: str = "current") -> dict:
    thr = load_thresholds()
    all_runs, skipped = load_runs(out)
    runs = [r for r in all_runs if r.meta.get("split") == split]
    if filter_ != "all":
        runs = [r for r in runs if r.meta.get("filter") == filter_]
    before = len(runs)
    rules_cfg = load_rules()
    if rules == "current":
        runs = [r for r in runs if r.meta.get("rules_version") == rules_cfg.version
                and r.meta.get("thresholds_version") == thr.version]
    elif rules != "all":
        runs = [r for r in runs if r.meta.get("rules_version") == rules]
    excluded_rules = before - len(runs)
    deduped = _dedupe(runs, thr)
    deduped.sort(key=lambda x: (CODE_ORDER.get(_code(x[0].meta, thr), 99), -(
        (x[0].metrics.get("end_to_end") or {}).get("automation_rate") or 0), x[0].run_id))

    baseline = _pick_baseline(runs, thr, baseline_id)
    expected = _expected_routes(data / split)
    paired_rows = []
    if baseline:
        base_routes = _trace_routes(baseline.path)
        for r, _ in deduped:
            if r.run_id == baseline.run_id:
                continue
            var_routes = _trace_routes(r.path)
            if base_routes and var_routes:
                paired_rows.append((r, _paired(base_routes, var_routes, expected)))

    warnings = []
    if skipped:
        warnings.append(f"Bỏ qua {skipped} thư mục run thiếu/hỏng `metrics.json`.")
    if excluded_rules:
        warnings.append(f"Bỏ qua {excluded_rules} run khác rules/thresholds (mặc định chỉ so trên "
                        f"`{rules_cfg.version}/{thr.version}`, dùng `--rules all` để xem tất cả).")
    if len({r.meta.get("n_bundles") for r, _ in deduped}) > 1:
        warnings.append("Các run không cùng số bộ: so sánh tổng hợp chỉ để tham khảo, paired diff mới đáng tin.")
    if any(_self_consistency(r.meta, thr)[1] for r, _ in deduped):
        warnings.append("Run cũ không ghi `self_consistency`/`preprocess`; giá trị suy ra từ thresholds "
                        "được đánh dấu ≈, còn lại là `?`.")
    if any((r.meta.get("model") not in ("oracle", "ocr") or _orchestration(r.meta) == "agent")
           and ((r.metrics.get("ops") or {}).get("cost_per_bundle_usd") or 0) == 0
           for r, _ in deduped):
        warnings.append("Chi phí $0.0000 nghĩa là chưa cấu hình giá (hoặc self-host), không phải miễn phí.")
    if any(r.meta.get("model") == "ocr" for r, _ in deduped):
        warnings.append("OCR $0 là chi phí API, chưa gồm CPU. OCR chỉ một lượt độc lập; "
                        "không dùng đọc lại cùng ảnh làm bằng chứng tự nhất quán.")
        warnings.append("Calls/bộ đếm lượt trích xuất, không gồm LLM điều phối. Latency dùng thời gian "
                        "inference lưu trong cache, không phải wall time lần replay; cache OCR được xây "
                        "với mức song song khác nhau, không dùng p95 này để kết luận tốc độ hơn VLM.")
    if split == "dev" and any((r.metrics.get("end_to_end") or {}).get("escaped") == 0 for r, _ in deduped):
        warnings.append("Có run escape 0 trên dev: dev chưa đủ để kết luận an toàn, hãy đọc cận trên 95% "
                        "và so sánh trên bộ stress; test đóng băng.")
    if not baseline:
        warnings.append("Không chọn được baseline để so route.")
    if not expected:
        warnings.append(f"Không thấy manifest của split `{split}` tại `{data / split}`: bỏ qua đếm sửa/làm hỏng.")

    L = [f"# So sánh biến thể — `{split}`", "",
         f"- Bộ lọc: `{filter_}`; rules: `{rules if rules == 'all' else rules_cfg.version + '/' + thr.version}`",
         f"- Baseline paired: `{baseline.run_id if baseline else '—'}`",
         f"- Nguồn: {len(runs)} run khớp, gộp còn {len(deduped)} biến thể (giữ run mới nhất mỗi cấu hình).", ""]
    L += [f"- {w}" for w in warnings]
    L += ["", "## Bảng chính", ""] + _table(deduped, thr)
    L += ["", "Không tính lại metric: mọi số đọc từ `metrics.json` của run gốc. `$/auto-pass` = "
              "`$/bộ ÷ automation rate`.", ""]
    if aug := _augment_table(deduped, thr):
        L += ["## Field accuracy theo augment", ""] + aug + [""]
    L += ["## So với baseline (cùng bộ)", ""] + _paired_table(paired_rows, thr) + [""]
    L += ["- **Sửa**: baseline sai route, variant đúng. **Làm hỏng**: baseline đúng, variant sai.",
          "- Escape/False review đếm trên các bộ chung có `expected_route` trong manifest.",
          "", "## Cách đọc", "",
          "- Xếp hạng từ điển: escape (+ cận trên) → automation → cost. Tăng escape là loại, "
          "bất kể automation.",
          "- Muốn quy kết tác động của một thay đổi, cần giữ các trục khác cố định; bảng nhiều phương án "
          "không tự chứng minh quan hệ nhân quả.",
          "- Test đã đóng băng và đã chạy: không chạy lại để chỉnh biến thể; mọi tinh chỉnh mới chỉ trên dev.", ""]
    return {"markdown": "\n".join(L), "rows": deduped, "baseline": baseline, "paired": paired_rows,
            "skipped": skipped}


def _csv_rows(result: dict, thr: Thresholds) -> list[dict]:
    rows = []
    for r, grouped in result["rows"]:
        e2e, ext, ops = r.metrics.get("end_to_end") or {}, r.metrics.get("extraction") or {}, r.metrics.get("ops") or {}
        auto, cost = e2e.get("automation_rate"), ops.get("cost_per_bundle_usd")
        sc, _ = _self_consistency(r.meta, thr)
        rows.append({
            "code": _code(r.meta, thr), "variant": _label(r, thr), "model": r.meta.get("model"),
            "orchestration": _orchestration(r.meta), "self_consistency": sc, "preprocess": _preprocess(r.meta),
            "n_bundles": r.meta.get("n_bundles"), "runs_grouped": grouped,
            "rules_version": r.meta.get("rules_version"), "thresholds_version": r.meta.get("thresholds_version"),
            "escape_rate": e2e.get("escape_rate"), "escape_upper95": e2e.get("escape_rate_upper95"),
            "automation_rate": auto, "false_review_rate": e2e.get("false_review_rate"),
            "field_accuracy": _acc(ext, "field_accuracy"),
            "critical_field_accuracy": _acc(ext, "critical_field_accuracy"),
            "calls_per_bundle": ops.get("calls_per_bundle"), "cost_per_bundle_usd": cost,
            "cost_per_autopass_usd": cost / auto if cost is not None and auto else None,
            "latency_p95_ms": ops.get("latency_p95_ms"), "git_commit": r.meta.get("git_commit"),
            "run_id": r.run_id,
        })
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="So sánh các biến thể eval trên cùng split")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--data", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--filter", default="augment=None limit=None",
                    help="giá trị filter trong meta; 'all' để lấy mọi run cùng split")
    ap.add_argument("--baseline", help="run_id (hoặc tiền tố duy nhất); mặc định VLM B2/B3 mới nhất")
    ap.add_argument("--rules", default="current",
                    help="current (mặc định) | all | version cụ thể, vd rules-v1")
    args = ap.parse_args()

    try:
        result = build_comparison(args.out, args.split, args.data, args.filter, args.baseline, args.rules)
    except ValueError as e:
        ap.error(str(e))
    (args.out / "comparison.md").write_text(result["markdown"], "utf-8")
    with (args.out / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(_csv_rows(result, load_thresholds()))
    print(f"{len(result['rows'])} biến thể -> {args.out / 'comparison.md'}, {args.out / 'comparison.csv'}")


if __name__ == "__main__":
    main()
