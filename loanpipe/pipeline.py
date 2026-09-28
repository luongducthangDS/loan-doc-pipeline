"""Workflow tất định 6 bước (spec mục 6). Không dùng agent: các bước và thứ tự đã biết trước.

1 ingest (kiểm file đọc được) -> 2 tiền xử lý -> 3 trích xuất (model) -> 4 validate + chuẩn hóa
+ confidence -> 5 rule -> 6 router. Mỗi bộ hồ sơ sinh một trace JSON để truy ngược mọi quyết định
route tới đúng lần gọi model đã gây ra nó.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from loanpipe.config import RulesConfig, Thresholds
from loanpipe.extract import Extractor
from loanpipe.router import route
from loanpipe.rules import BundleView, run_rules, salary_months
from loanpipe.schemas import DocType, Extraction, field_kinds
from loanpipe.validate import finalize_field


@dataclass
class DocInput:
    doc_id: str
    doc_type: DocType
    files: list[Path]


@dataclass
class BundleInput:
    bundle_id: str
    docs: list[DocInput]


def is_readable(files: list[Path]) -> bool:
    try:
        for f in files:
            with Image.open(f) as im:
                im.verify()
        return bool(files)
    except (OSError, SyntaxError):
        return False


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def run_bundle(inp: BundleInput, extractor: Extractor, rules_cfg: RulesConfig, thr: Thresholds,
               check_files: bool = True) -> dict:
    steps: dict[str, int] = {}
    t = time.perf_counter()
    # 1. ingest
    unreadable = [d.doc_type for d in inp.docs if check_files and not is_readable(d.files)]
    steps["ingest_ms"] = _ms(t)
    # 2. tiền xử lý: MVP chưa cần (ảnh đã là JPEG; deskew/resize thêm khi đo thấy cần ở M2)

    # 3 + 4. trích xuất, chuẩn hóa, confidence
    t = time.perf_counter()
    extractions: list[Extraction] = []
    model_outputs: dict[str, str | None] = {}
    extract_errors: dict[str, list[str]] = {}
    cost = 0.0

    def same_salary(a, b):  # R4 chỉ đọc lương từng tháng; lệch dòng ghi nợ giữa 2 lượt không đổi quyết định nào
        return salary_months(a, rules_cfg) == salary_months(b, rules_cfg)

    for d in inp.docs:
        if d.doc_type in unreadable:
            continue
        r1 = extractor.extract(inp.bundle_id, d.doc_id, d.doc_type, d.files, variant=0)
        r2 = (extractor.extract(inp.bundle_id, d.doc_id, d.doc_type, d.files, variant=1)
              if thr.use_self_consistency else None)
        fields = {}
        for name, kind in field_kinds(d.doc_type).items():
            raw, page = r1.fields.get(name, (None, None))
            check = r2 is not None and thr.is_critical(d.doc_type.value, name)
            second = r2.fields.get(name, (None, None))[0] if check else None
            fields[name] = finalize_field(kind, raw, page, second, check_consistency=check,
                                          **({"same": same_salary} if kind == "transactions" else {}))
        runs = [r for r in (r1, r2) if r is not None]
        cost += sum(r.cost_usd for r in runs)
        model_outputs[d.doc_id] = r1.model_output
        if errs := [e for r in runs for e in r.errors]:
            extract_errors[d.doc_id] = errs
        extractions.append(Extraction(
            bundle_id=inp.bundle_id, doc_id=d.doc_id, doc_type=d.doc_type, fields=fields,
            model=extractor.name, prompt_version=extractor.prompt_version,
            latency_ms=sum(r.latency_ms for r in runs), n_calls=sum(r.n_calls for r in runs)))
    steps["extract_validate_ms"] = _ms(t)

    # 5 + 6. rule, router
    t = time.perf_counter()
    view = BundleView({e.doc_type: e.fields for e in extractions}, unreadable)
    checks = run_rules(view, rules_cfg)
    decision = route(inp.bundle_id, view, checks, rules_cfg, thr)
    steps["rules_route_ms"] = _ms(t)

    return {
        "bundle_id": inp.bundle_id,
        "steps": steps,
        # extract_validate_ms đã chứa thời gian gọi model khi chạy thật -> không cộng thêm lần nữa. Dùng latency
        # model đã ghi (có trong cache) thay cho wall time của bước đó, để run đọc cache vẫn báo đúng latency.
        "latency_ms": steps["ingest_ms"] + steps["rules_route_ms"] + sum(e.latency_ms for e in extractions),
        "n_calls": sum(e.n_calls for e in extractions),
        "cost_usd": cost,
        "unreadable": [d.value for d in unreadable],
        "extractions": [e.model_dump(mode="json") for e in extractions],
        "model_outputs": model_outputs,
        "extract_errors": extract_errors,
        "checks": [c.model_dump(mode="json") for c in checks],
        "decision": decision.model_dump(mode="json"),
    }


def bundle_input_from_manifest(entry: dict, split_dir: Path) -> BundleInput:
    return BundleInput(entry["bundle_id"], [
        DocInput(d["doc_id"], DocType(d["type"]), [split_dir / f for f in d["files"]]) for d in entry["docs"]])
