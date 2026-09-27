"""Bước 6: route mỗi bộ hồ sơ vào đúng 1 nhánh (spec mục 8).

Xét theo thứ tự, dừng ở điều kiện đầu tiên thỏa. Chỉ bộ qua HẾT mọi kiểm tra mới AUTO_PASS.
"""

from __future__ import annotations

from loanpipe.config import RulesConfig, Thresholds
from loanpipe.rules import BundleView
from loanpipe.schemas import CheckResult, Decision


def route(bundle_id: str, view: BundleView, checks: list[CheckResult],
          rules_cfg: RulesConfig, thr: Thresholds) -> Decision:
    def decide(r: str, reasons: list[str]) -> Decision:
        return Decision(bundle_id=bundle_id, route=r, reasons=reasons,
                        rules_version=rules_cfg.version, thresholds_version=thr.version)

    critical = [(dt.value, name, f) for dt, fields in view.docs.items()
                for name, f in fields.items() if thr.is_critical(dt.value, name)]
    format_errors = [f"FORMAT:{d}.{n}" for d, n, f in critical if f.error]
    by_id = {c.rule_id: c for c in checks}

    # 1. Thiếu giấy tờ / ảnh không đọc được / ảnh quá xấu -> xin bổ sung
    if by_id["R0"].status == "fail" or len(format_errors) >= thr.request_more_min_format_errors:
        return decide("REQUEST_MORE", (["R0"] if by_id["R0"].status == "fail" else []) + format_errors)

    # 2. Có rule fail -> người rà soát
    failed = [c.rule_id for c in checks if c.status == "fail"]
    if failed:
        return decide("REVIEW", failed)

    # 3. Chưa chắc chắn -> người rà soát. unknown không bao giờ được coi là pass.
    unknown = [f"UNKNOWN:{c.rule_id}" for c in checks if c.status == "unknown"]
    low = [f"LOW_CONF:{d}.{n}" for d, n, f in critical if f.confidence == "low"]
    if unknown or low:
        return decide("REVIEW", unknown + low)

    return decide("AUTO_PASS", [])
