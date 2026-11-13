"""So sánh biến thể: kiểm gộp trùng cấu hình, suy biến thể legacy và paired diff route."""

import csv
import json

import pytest

from loanpipe.compare import CSV_FIELDS, _csv_rows, build_comparison
from loanpipe.config import load_thresholds

FILTER = "augment=None limit=None"


def write_run(out, run_id, model, routes, *, extra=None):
    d = out / run_id
    (d / "traces").mkdir(parents=True)
    meta = {"run_id": run_id, "split": "dev", "filter": FILTER, "n_bundles": len(routes),
            "model": model, "prompt_version": "v4", "rules_version": "rules-v2",
            "thresholds_version": load_thresholds().version, "git_commit": "abc1234"}
    meta.update(extra or {})
    for bundle, route in routes.items():
        (d / "traces" / f"{bundle}.json").write_text(json.dumps({"decision": {"route": route}}), "utf-8")
    metrics = {
        "meta": meta,
        "end_to_end": {"escape_rate": 0.0, "escape_rate_upper95": 0.1, "automation_rate": 0.5,
                       "false_review_rate": 0.0, "escaped": 0, "n_with_errors": 2, "n_clean": 1},
        "extraction": {"field_accuracy": {"n": 10, "acc": 0.9},
                       "critical_field_accuracy": {"n": 5, "acc": 0.8},
                       "by_augment": {"clean": {"n": 5, "acc": 0.95}, "photo": {"n": 5, "acc": 0.85}}},
        "ops": {"calls_per_bundle": 9.0, "cost_per_bundle_usd": 0.01, "latency_p95_ms": 1000.0},
    }
    (d / "metrics.json").write_text(json.dumps(metrics), "utf-8")


def write_manifest(data, expected):
    d = data / "dev"
    d.mkdir(parents=True)
    (d / "manifest.jsonl").write_text(
        "\n".join(json.dumps({"bundle_id": b, "expected_route": r}) for b, r in expected.items()), "utf-8")


def test_dedupe_paired_diff_and_ladder(tmp_path):
    out, data = tmp_path / "reports", tmp_path / "data"
    expected = {"b1": "AUTO_PASS", "b2": "REVIEW", "b3": "AUTO_PASS"}
    write_manifest(data, expected)
    base_routes = {"b1": "AUTO_PASS", "b2": "REVIEW", "b3": "REVIEW"}
    write_run(out, "20260101-000000_dev_qwen3", "Qwen/Qwen3-VL-8B-Instruct", base_routes, extra={
        "orchestration": "workflow", "self_consistency": True, "preprocess": "off"})
    write_run(out, "20260202-000000_dev_oracle", "oracle", expected)
    write_run(out, "20260203-000000_dev_qwen25", "Qwen/Qwen2.5-VL-7B-Instruct", {
        "b1": "REVIEW", "b2": "AUTO_PASS", "b3": "AUTO_PASS"})
    write_run(out, "20260204-000000_dev_qwen3", "Qwen/Qwen3-VL-8B-Instruct", base_routes, extra={
        "orchestration": "workflow", "self_consistency": True, "preprocess": "off"})

    result = build_comparison(out, "dev", data)
    rows = {r.run_id: (r, grouped) for r, grouped in result["rows"]}
    assert result["baseline"].run_id == "20260204-000000_dev_qwen3"
    assert rows["20260204-000000_dev_qwen3"][1] == 2 and "20260101-000000_dev_qwen3" not in rows

    paired = {r.run_id: p for r, p in result["paired"]}
    p = paired["20260203-000000_dev_qwen25"]
    assert (p["n"], p["fixes"], p["breaks"]) == (3, 1, 2)
    assert p["escape"] == [0, 1] and p["false_review"] == [1, 1]
    assert "B0" in result["markdown"] and "B3" in result["markdown"]

    csv_rows = _csv_rows(result, load_thresholds())
    assert set(csv_rows[0]) == set(CSV_FIELDS)
    assert {r["run_id"] for r in csv_rows} == set(rows)


def test_legacy_meta_is_inferred_and_broken_dir_skipped(tmp_path):
    out, data = tmp_path / "reports", tmp_path / "data"
    write_manifest(data, {"b1": "AUTO_PASS"})
    write_run(out, "20260101-000000_dev_old", "Qwen/Qwen2.5-VL-7B-Instruct", {"b1": "AUTO_PASS"})
    broken = out / "20260102-000000_dev_broken"
    broken.mkdir(parents=True)
    (broken / "metrics.json").write_text("{không phải json", "utf-8")

    result = build_comparison(out, "dev", data)
    assert result["skipped"] == 1
    label = next(iter(result["rows"]))[0].run_id
    assert label == "20260101-000000_dev_old"
    assert "2 lượt≈" in result["markdown"] and "B3" in result["markdown"]
    assert "self_consistency" in result["markdown"]


def test_ocr_run_is_ranked_as_b1(tmp_path):
    out, data = tmp_path / "reports", tmp_path / "data"
    write_manifest(data, {"b1": "AUTO_PASS"})
    write_run(out, "20260101-000000_dev_ocr", "ocr", {"b1": "AUTO_PASS"},
              extra={"orchestration": "workflow", "self_consistency": False, "preprocess": "n/a"})
    result = build_comparison(out, "dev", data)
    assert "| B1 |" in result["markdown"] and "B1 ocr" in result["markdown"]
    assert "chưa cấu hình giá" not in result["markdown"]  # OCR chạy local: $0 là thật


def test_newer_ocr_does_not_replace_vlm_reference(tmp_path):
    out, data = tmp_path / "reports", tmp_path / "data"
    routes = {"b1": "AUTO_PASS"}
    write_manifest(data, routes)
    write_run(out, "20260101_dev_vlm", "qwen", routes)
    write_run(out, "20260201_dev_ocr", "ocr", routes)
    assert build_comparison(out, "dev", data)["baseline"].run_id == "20260101_dev_vlm"


def test_explicit_baseline_can_reference_older_deduplicated_run(tmp_path):
    out, data = tmp_path / "reports", tmp_path / "data"
    routes = {"b1": "AUTO_PASS"}
    write_manifest(data, routes)
    write_run(out, "20260101_dev_vlm", "qwen", routes)
    write_run(out, "20260201_dev_vlm", "qwen", routes)
    result = build_comparison(out, "dev", data, baseline_id="20260101_dev_vlm")
    assert result["baseline"].run_id == "20260101_dev_vlm"
    assert len(result["rows"]) == 1 and result["paired"][0][1]["n"] == 1
    for wanted in ("missing", "2026"):
        with pytest.raises(ValueError):
            build_comparison(out, "dev", data, baseline_id=wanted)


def test_ocr_agent_is_not_classified_as_traditional_workflow(tmp_path):
    out, data = tmp_path / "reports", tmp_path / "data"
    routes = {"b1": "AUTO_PASS"}
    write_manifest(data, routes)
    write_run(out, "20260101_dev_ocr_agent", "ocr", routes, extra={"orchestration": "agent"})
    result = build_comparison(out, "dev", data)
    assert _csv_rows(result, load_thresholds())[0]["code"] == "B5"
    assert "ocr · agent" in result["markdown"]


def test_filter_all_and_empty_split(tmp_path):
    out, data = tmp_path / "reports", tmp_path / "data"
    write_manifest(data, {"b1": "AUTO_PASS"})
    write_run(out, "20260101-000000_dev_clean", "oracle", {"b1": "AUTO_PASS"},
              extra={"filter": "augment=clean limit=None"})
    assert build_comparison(out, "dev", data)["rows"] == []
    assert len(build_comparison(out, "dev", data, filter_="all")["rows"]) == 1
