"""Mỗi rule: pass, fail, unknown (spec mục 7) + near-miss rule KHÔNG được gắn cờ."""

from datetime import date

import pytest
from conftest import F

from loanpipe.rules import BundleView, r0_complete, run_rules, salary_avg
from loanpipe.schemas import DocType, GiaoDich, LoaiHd

D = DocType

# (rule, doc, field, giá trị làm FAIL)
FAIL_CASES = [
    ("R1", D.DON_VAY, "ho_ten", "NGUYỄN VĂN ÁN"),
    ("R1", D.HDLD, "ho_ten_nld", "NGUYỄN AN"),
    ("R2", D.DON_VAY, "so_cccd", "001090123457"),
    ("R3", D.DON_VAY, "ngay_sinh", date(1990, 6, 1)),
    ("R4", D.DON_VAY, "thu_nhap_thang", 22_100_000),   # > 20tr x 1,1
    ("R5", D.CCCD, "ngay_het_han", date(2026, 4, 19)),
    ("R6", D.SAO_KE, "so_tk", "123456780"),
    ("R7", D.HDLD, "ngay_ket_thuc", date(2026, 4, 19)),
    ("R8", D.SAO_KE, "ky_den", date(2026, 3, 1)),        # cũ hơn 30 ngày
]
# (rule, doc, field) mà thiếu/low-conf thì rule phải unknown
UNKNOWN_CASES = [("R1", D.SAO_KE, "chu_tk"), ("R2", D.CCCD, "so_cccd"), ("R3", D.CCCD, "ngay_sinh"),
                 ("R4", D.SAO_KE, "giao_dich"), ("R5", D.CCCD, "ngay_het_han"), ("R6", D.DON_VAY, "so_tk_nhan_luong"),
                 ("R7", D.HDLD, "ngay_ket_thuc"), ("R8", D.SAO_KE, "ky_tu")]


def status(view, cfg, rule_id):
    return next(c for c in run_rules(view, cfg) if c.rule_id == rule_id).status


def test_clean_bundle_all_pass(view, cfg):
    assert {c.rule_id: c.status for c in run_rules(view, cfg)} == {f"R{i}": "pass" for i in range(9)}


@pytest.mark.parametrize("rule,doc,field,value", FAIL_CASES)
def test_fail(docs, cfg, rule, doc, field, value):
    docs[doc][field] = F(value)
    assert status(BundleView(docs), cfg, rule) == "fail"


@pytest.mark.parametrize("rule,doc,field", UNKNOWN_CASES)
@pytest.mark.parametrize("how", ["missing", "low_conf", "format_error"])
def test_unknown_never_pass(docs, cfg, rule, doc, field, how):
    if how == "missing":
        del docs[doc][field]
    elif how == "low_conf":
        docs[doc][field] = F(docs[doc][field].value, conf="low")
    else:
        docs[doc][field] = F(None, conf="low", error="sai định dạng")
    assert status(BundleView(docs), cfg, rule) == "unknown"


def test_known_conflict_fails_even_if_third_unknown(docs, cfg):
    docs[D.DON_VAY]["ho_ten"] = F("TRẦN VĂN AN")
    docs[D.SAO_KE]["chu_tk"] = F("NGUYEN VAN AN", conf="low")
    assert status(BundleView(docs), cfg, "R1") == "fail"


def test_r0(docs, cfg):
    assert r0_complete(BundleView(docs), cfg).status == "pass"
    del docs[D.HDLD]
    assert r0_complete(BundleView(docs), cfg).status == "fail"
    assert r0_complete(BundleView(docs, unreadable=[D.HDLD]), cfg).evidence[0]["missing"] is False


# --- near-miss: hợp lệ, không được gắn cờ ------------------------------------------

def test_name_near_miss(docs, cfg):
    docs[D.DON_VAY]["ho_ten"] = F("NGUYEN VAN AN")  # đơn viết không dấu
    assert status(BundleView(docs), cfg, "R1") == "pass"


def test_income_within_tolerance(docs, cfg):
    docs[D.DON_VAY]["thu_nhap_thang"] = F(21_000_000)  # +5%
    assert status(BundleView(docs), cfg, "R4") == "pass"


def test_two_salaries_in_one_month_is_unknown(docs, cfg):
    """Gặp thật (dev_0037): model đọc ngày lương 07/04 thành 30/03, hai lượt cùng sai nên confidence high.
    Không chặn thì lương TB = 60tr/2 tháng = 30tr và một bộ khai khống 30tr (thật: 20tr) sẽ pass."""
    txs = [g if g.ngay != date(2026, 4, 7) else g.model_copy(update={"ngay": date(2026, 3, 30)})
           for g in docs[D.SAO_KE]["giao_dich"].value]
    docs[D.SAO_KE]["giao_dich"] = F(txs)
    docs[D.DON_VAY]["thu_nhap_thang"] = F(30_000_000)
    assert salary_avg(txs, cfg) == 30_000_000  # lương TB bị đội lên đúng như lo
    assert status(BundleView(docs), cfg, "R4") == "unknown"


def test_salary_regex_ignores_person_named_luong(docs, cfg):
    txs = docs[D.SAO_KE]["giao_dich"].value + [
        GiaoDich(ngay=date(2026, 3, 20), mo_ta="NHAN CK TU LUONG VAN TUNG", so_tien=30_000_000, loai="ghi_co"),
        GiaoDich(ngay=date(2026, 3, 21), mo_ta="HOAN TIEN BAO HIEM", so_tien=9_000_000, loai="ghi_co")]
    assert salary_avg(txs, cfg) == 20_000_000


def test_salary_late_averages_months_present(docs, cfg):
    txs = docs[D.SAO_KE]["giao_dich"].value[:2]  # chỉ 2 kỳ lương
    assert salary_avg(txs, cfg) == 20_000_000
    assert salary_avg([t for t in txs if "LUONG" not in t.mo_ta], cfg) is None


def test_salary_debit_not_counted(cfg):
    txs = [GiaoDich(ngay=date(2026, 3, 7), mo_ta="TRA LUONG NHAN VIEN", so_tien=5_000_000, loai="ghi_no")]
    assert salary_avg(txs, cfg) is None


def test_r7_indefinite_contract(docs, cfg):
    docs[D.HDLD]["loai_hd"] = F(LoaiHd.KHONG_XAC_DINH_THOI_HAN)
    docs[D.HDLD]["ngay_ket_thuc"] = F(None)
    assert status(BundleView(docs), cfg, "R7") == "pass"


def test_r7_fixed_term_without_end_is_unknown(docs, cfg):
    docs[D.HDLD]["ngay_ket_thuc"] = F(None)
    assert status(BundleView(docs), cfg, "R7") == "unknown"


def test_r5_expires_same_day_passes(docs, cfg):
    docs[D.CCCD]["ngay_het_han"] = F(date(2026, 4, 20))
    assert status(BundleView(docs), cfg, "R5") == "pass"


def test_r8_short_statement_fails(docs, cfg):
    docs[D.SAO_KE]["ky_tu"] = F(date(2026, 2, 1))
    assert status(BundleView(docs), cfg, "R8") == "fail"
