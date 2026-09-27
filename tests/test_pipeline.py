"""End-to-end với oracle (cận trên) + chứng minh harness BẮT ĐƯỢC failure mode của model."""

from pathlib import Path

import pytest

from datagen.build import build_split
from loanpipe.config import load_rules, load_thresholds
from loanpipe.evaluate import compute_metrics, upper_bound_95
from loanpipe.extract import RawExtraction
from loanpipe.extract.oracle import OracleExtractor
from loanpipe.pipeline import bundle_input_from_manifest, run_bundle
from loanpipe.schemas import DocType


@pytest.fixture(scope="module")
def manifest():
    return build_split("test", 60, 3, None, images=False)


def run(manifest, extractor):
    cfg, thr = load_rules(), load_thresholds()
    traces = {e["bundle_id"]: run_bundle(bundle_input_from_manifest(e, Path('.')), extractor, cfg, thr,
                                         check_files=False) for e in manifest}
    return compute_metrics(manifest, traces, thr)[0], traces


def test_oracle_is_upper_bound(manifest):
    m, traces = run(manifest, OracleExtractor(manifest))
    e2e = m["end_to_end"]
    assert e2e["escape_rate"] == 0 and e2e["false_review_rate"] == 0
    assert m["extraction"]["field_accuracy"]["acc"] == 1.0
    assert all(r["recall"] in (1.0, None) for r in m["rules"]["recall_by_error"].values())
    t = next(iter(traces.values()))
    assert t["n_calls"] == 2 * len(t["extractions"])  # tự nhất quán: 2 lượt mỗi giấy tờ


class NameFixingExtractor(OracleExtractor):
    """Giả lập failure mode nguy hiểm nhất: model 'sửa' tên trên đơn cho giống tên trên CCCD."""

    name = "name-fixing"

    def extract(self, bundle_id, doc_id, doc_type, files, variant=0):
        r = super().extract(bundle_id, doc_id, doc_type, files, variant)
        if doc_type is DocType.DON_VAY and (bundle_id, "d1") in self._raw:
            fixed = dict(r.fields)
            fixed["ho_ten"] = (self._raw[(bundle_id, "d1")]["ho_ten"]["raw"], 1)
            return RawExtraction(fields=fixed)
        return r


def test_harness_detects_name_fixing_model(manifest):
    m, _ = run(manifest, NameFixingExtractor(manifest))
    assert m["rules"]["recall_by_error"]["E1"]["recall"] < 1.0
    assert m["end_to_end"]["escaped"] > 0  # bộ chỉ có lỗi E1 bị auto-pass sai


class FlakyExtractor(OracleExtractor):
    """Lượt 2 đọc khác lượt 1 ở số CCCD -> confidence low -> không được auto-pass."""

    name = "flaky"

    def extract(self, bundle_id, doc_id, doc_type, files, variant=0):
        r = super().extract(bundle_id, doc_id, doc_type, files, variant)
        if variant == 1 and doc_type is DocType.CCCD:
            f = dict(r.fields)
            f["so_cccd"] = ("000000000000", 1)
            return RawExtraction(fields=f)
        return r


def test_self_consistency_blocks_auto_pass(manifest):
    m, traces = run(manifest, FlakyExtractor(manifest))
    assert m["end_to_end"]["automation_rate"] == 0 and m["end_to_end"]["escaped"] == 0
    assert any("LOW_CONF:cccd.so_cccd" in t["decision"]["reasons"] for t in traces.values())


def test_rule_of_three():
    assert abs(upper_bound_95(0, 150) - 0.0198) < 1e-3
    assert abs(upper_bound_95(0, 300) - 0.00994) < 1e-4
    assert 0.02 < upper_bound_95(1, 150) < 0.04
