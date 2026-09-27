from datetime import date

from conftest import F

from loanpipe.router import route
from loanpipe.rules import BundleView, run_rules
from loanpipe.schemas import DocType

D = DocType


def decide(docs, cfg, thr, **kw):
    view = BundleView(docs, **kw)
    return route("b", view, run_rules(view, cfg), cfg, thr)


def test_clean_auto_pass(docs, cfg, thr):
    d = decide(docs, cfg, thr)
    assert (d.route, d.reasons, d.rules_version, d.thresholds_version) == ("AUTO_PASS", [], cfg.version, thr.version)


def test_missing_doc_request_more_wins_over_fail(docs, cfg, thr):
    del docs[D.CCCD]
    docs[D.DON_VAY]["thu_nhap_thang"] = F(90_000_000)
    assert decide(docs, cfg, thr).route == "REQUEST_MORE"


def test_many_format_errors_request_more(docs, cfg, thr):
    for f in ("so_cccd", "ngay_sinh", "ngay_ky"):
        docs[D.DON_VAY][f] = F(None, conf="low", error="x")
    d = decide(docs, cfg, thr)
    assert d.route == "REQUEST_MORE" and len(d.reasons) == 3


def test_fail_goes_to_review_with_rule_ids(docs, cfg, thr):
    docs[D.DON_VAY]["ngay_sinh"] = F(date(1991, 5, 1))
    docs[D.SAO_KE]["so_tk"] = F("999999999")
    d = decide(docs, cfg, thr)
    assert (d.route, d.reasons) == ("REVIEW", ["R3", "R6"])


def test_low_conf_critical_field_goes_to_review(docs, cfg, thr):
    docs[D.CCCD]["ngay_het_han"] = F(date(2030, 5, 1), conf="low")
    d = decide(docs, cfg, thr)
    assert d.route == "REVIEW" and "LOW_CONF:cccd.ngay_het_han" in d.reasons and "UNKNOWN:R5" in d.reasons


def test_low_conf_non_critical_does_not_block(docs, cfg, thr):
    docs[D.DON_VAY]["muc_dich"] = F("Mua xe", conf="low")
    assert decide(docs, cfg, thr).route == "AUTO_PASS"
