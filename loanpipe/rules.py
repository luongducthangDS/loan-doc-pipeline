"""Bước 5: 9 rule đối chiếu chéo (spec mục 7). Mỗi rule là hàm thuần -> CheckResult.

Nguyên tắc: thiếu field, field confidence thấp hoặc lỗi định dạng -> `unknown`, KHÔNG BAO GIỜ `pass`.
Ngoại lệ có chủ đích: nếu hai giá trị đã chắc chắn (high) mâu thuẫn nhau thì `fail` luôn,
dù field thứ ba chưa chắc — thêm thông tin cũng không làm mâu thuẫn biến mất.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import combinations
from typing import Any

from loanpipe.config import RulesConfig
from loanpipe.normalize import names_match, strip_accents
from loanpipe.schemas import CheckResult, DocType, Field, GiaoDich, LoaiHd

D = DocType
Ref = tuple[DocType, str]


def add_months(d: date, k: int) -> date:
    y, m = divmod(d.month - 1 + k, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@dataclass
class BundleView:
    """Kết quả trích xuất của một bộ hồ sơ, đã chuẩn hóa. Giấy tờ thiếu thì không có key."""

    docs: dict[DocType, dict[str, Field]]
    unreadable: list[DocType] = field(default_factory=list)  # file không mở/giải mã được

    def get(self, ref: Ref) -> Field | None:
        return self.docs.get(ref[0], {}).get(ref[1])


def is_known(f: Field | None) -> bool:
    """Giá trị dùng được cho rule: có, confidence high, không lỗi định dạng.
    (value=None vẫn có thể 'known' khi raw ghi rõ 'Không xác định', vd ngay_ket_thuc.)"""
    return f is not None and f.confidence == "high" and f.error is None


def _ev(view: BundleView, refs: list[Ref]) -> list[dict[str, Any]]:
    out = []
    for dt, name in refs:
        f = view.get((dt, name))
        v = f.value if f is not None else None
        out.append({"doc_type": dt.value, "field": name,
                    "value": v.isoformat() if isinstance(v, date) else v,
                    "known": is_known(f)})
    return out


def _label(ref: Ref) -> str:
    return f"{ref[0].value}.{ref[1]}"


def _unknown(rule_id: str, view: BundleView, refs: list[Ref], missing: list[Ref]) -> CheckResult:
    return CheckResult(rule_id=rule_id, status="unknown", evidence=_ev(view, refs),
                       message="Thiếu hoặc không chắc: " + ", ".join(map(_label, missing)))


def _all_equal(rule_id: str, view: BundleView, refs: list[Ref],
               eq: Callable[[Any, Any], bool], what: str) -> CheckResult:
    known = [(r, view.get(r).value) for r in refs if is_known(view.get(r))]
    missing = [r for r in refs if not is_known(view.get(r))]
    for (ra, va), (rb, vb) in combinations(known, 2):
        if not eq(va, vb):
            return CheckResult(rule_id=rule_id, status="fail", evidence=_ev(view, refs),
                               message=f"{what} lệch: {_label(ra)}={va} ≠ {_label(rb)}={vb}")
    if missing:
        return _unknown(rule_id, view, refs, missing)
    return CheckResult(rule_id=rule_id, status="pass", evidence=_ev(view, refs), message=f"{what} khớp")


# --- Rule ---------------------------------------------------------------------

def r0_complete(view: BundleView, cfg: RulesConfig) -> CheckResult:
    missing = [d for d in DocType if d not in view.docs and d not in view.unreadable]
    bad = missing + list(view.unreadable)
    if bad:
        return CheckResult(rule_id="R0", status="fail",
                           evidence=[{"doc_type": d.value, "missing": d in missing} for d in bad],
                           message="Thiếu/không đọc được: " + ", ".join(d.value for d in bad))
    return CheckResult(rule_id="R0", status="pass", message="Đủ 4 giấy tờ")


def r1_name(view: BundleView, cfg: RulesConfig) -> CheckResult:
    refs = [(D.DON_VAY, "ho_ten"), (D.CCCD, "ho_ten"), (D.HDLD, "ho_ten_nld"), (D.SAO_KE, "chu_tk")]
    return _all_equal("R1", view, refs, names_match, "Họ tên")


def r2_id(view: BundleView, cfg: RulesConfig) -> CheckResult:
    return _all_equal("R2", view, [(D.DON_VAY, "so_cccd"), (D.CCCD, "so_cccd")],
                      lambda a, b: a == b, "Số CCCD")


def r3_dob(view: BundleView, cfg: RulesConfig) -> CheckResult:
    return _all_equal("R3", view, [(D.DON_VAY, "ngay_sinh"), (D.CCCD, "ngay_sinh")],
                      lambda a, b: a == b, "Ngày sinh")


def salary_months(txs: list[GiaoDich], cfg: RulesConfig) -> dict[tuple[int, int], int]:
    """Tổng lương theo tháng. Lương = ghi có + mô tả (bỏ dấu, viết hoa) khớp regex cấu hình."""
    by_month: dict[tuple[int, int], int] = defaultdict(int)
    for g in txs:
        text = strip_accents(g.mo_ta).upper()
        if g.loai == "ghi_co" and any(p.search(text) for p in cfg.salary_patterns):
            by_month[(g.ngay.year, g.ngay.month)] += g.so_tien
    return dict(by_month)


def salary_avg(txs: list[GiaoDich], cfg: RulesConfig) -> float | None:
    """Trung bình các tháng CÓ lương (không chia cứng cho 3: lương về trễ không bị phạt)."""
    m = salary_months(txs, cfg)
    return sum(m.values()) / len(m) if m else None


def r4_income(view: BundleView, cfg: RulesConfig) -> CheckResult:
    refs = [(D.DON_VAY, "thu_nhap_thang"), (D.SAO_KE, "giao_dich")]
    missing = [r for r in refs if not is_known(view.get(r))]
    if missing:
        return _unknown("R4", view, refs, missing)
    declared = view.get(refs[0]).value
    avg = salary_avg(view.get(refs[1]).value, cfg)
    ev = [_ev(view, refs[:1])[0], {"doc_type": "sao_ke", "field": "luong_tb_3_thang",
                                    "value": None if avg is None else round(avg), "known": avg is not None}]
    if avg is None:
        return CheckResult(rule_id="R4", status="unknown", evidence=ev,
                           message="Không tìm thấy giao dịch lương trên sao kê")
    limit = avg * (1 + cfg.income_tolerance)
    ok = declared <= limit
    return CheckResult(rule_id="R4", status="pass" if ok else "fail", evidence=ev,
                       message=f"Thu nhập khai {declared:,} {'≤' if ok else '>'} "
                               f"lương TB {avg:,.0f} × {1 + cfg.income_tolerance:g}")


def _date_order(rule_id: str, view: BundleView, later: Ref, earlier: Ref, what: str) -> CheckResult:
    refs = [later, earlier]
    missing = [r for r in refs if not is_known(view.get(r)) or view.get(r).value is None]
    if missing:
        return _unknown(rule_id, view, refs, missing)
    a, b = view.get(later).value, view.get(earlier).value
    ok = a >= b
    return CheckResult(rule_id=rule_id, status="pass" if ok else "fail", evidence=_ev(view, refs),
                       message=f"{what}: {_label(later)}={a} {'≥' if ok else '<'} {_label(earlier)}={b}")


def r5_id_valid(view: BundleView, cfg: RulesConfig) -> CheckResult:
    return _date_order("R5", view, (D.CCCD, "ngay_het_han"), (D.DON_VAY, "ngay_ky"), "CCCD còn hạn")


def r6_account(view: BundleView, cfg: RulesConfig) -> CheckResult:
    return _all_equal("R6", view, [(D.DON_VAY, "so_tk_nhan_luong"), (D.SAO_KE, "so_tk")],
                      lambda a, b: a == b, "Số tài khoản nhận lương")


def r7_contract(view: BundleView, cfg: RulesConfig) -> CheckResult:
    refs = [(D.HDLD, "loai_hd"), (D.HDLD, "ngay_ket_thuc"), (D.DON_VAY, "ngay_ky")]
    loai, end, ky = (view.get(r) for r in refs)
    if is_known(loai) and loai.value is LoaiHd.KHONG_XAC_DINH_THOI_HAN:
        return CheckResult(rule_id="R7", status="pass", evidence=_ev(view, refs[:1]),
                           message="HĐLĐ không xác định thời hạn")
    if is_known(end) and end.value is not None:
        return _date_order("R7", view, refs[1], refs[2], "HĐLĐ còn hiệu lực")
    # ngay_ket_thuc trống nhưng loại HĐ xác định thời hạn / không rõ loại -> mâu thuẫn hoặc thiếu
    return _unknown("R7", view, refs, [r for r in refs[:2] if not is_known(view.get(r))] or refs[1:2])


def r8_statement(view: BundleView, cfg: RulesConfig) -> CheckResult:
    refs = [(D.SAO_KE, "ky_tu"), (D.SAO_KE, "ky_den"), (D.DON_VAY, "ngay_ky")]
    missing = [r for r in refs if not is_known(view.get(r))]
    if missing:
        return _unknown("R8", view, refs, missing)
    tu, den, ky = (view.get(r).value for r in refs)
    age = (ky - den).days
    covers = add_months(tu, cfg.statement_min_months) <= den + timedelta(days=1)
    ok = age <= cfg.statement_max_age_days and covers
    return CheckResult(rule_id="R8", status="pass" if ok else "fail", evidence=_ev(view, refs),
                       message=f"Sao kê kết thúc {age} ngày trước ngày ký "
                               f"(tối đa {cfg.statement_max_age_days}); "
                               f"phủ đủ {cfg.statement_min_months} tháng: {'có' if covers else 'không'}")


RULES: list[Callable[[BundleView, RulesConfig], CheckResult]] = [
    r0_complete, r1_name, r2_id, r3_dob, r4_income, r5_id_valid, r6_account, r7_contract, r8_statement,
]


def run_rules(view: BundleView, cfg: RulesConfig) -> list[CheckResult]:
    return [rule(view, cfg) for rule in RULES]
