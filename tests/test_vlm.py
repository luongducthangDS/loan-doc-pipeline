"""VLM extractor với API giả: đi qua đúng đường code thật (prompt, ảnh, parse, retry, cache)."""

import json
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

from datagen.build import build_split
from loanpipe.config import load_rules, load_thresholds
from loanpipe.evaluate import compute_metrics
from loanpipe.extract.vlm import VLMExtractor, build_prompt, encode_image, parse_output
from loanpipe.pipeline import bundle_input_from_manifest, run_bundle
from loanpipe.schemas import DocType, field_kinds


def reply(obj) -> dict:
    return {"choices": [{"message": {"content": obj if isinstance(obj, str) else json.dumps(obj)}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}


def test_prompt_lists_every_field():
    for dt in DocType:
        p = build_prompt(dt)
        assert all(f'"{k}"' in p for k in field_kinds(dt))


def test_parse_output():
    text = '```json\n{"ho_ten": {"raw": "NGUYỄN VĂN AN", "page": 1}, "so_cccd": "001090123456",' \
           ' "ngay_sinh": null, "extra": 1}\n```'
    out = parse_output(text, DocType.CCCD)
    assert out["ho_ten"] == ("NGUYỄN VĂN AN", 1) and out["so_cccd"] == ("001090123456", None)
    assert out["ngay_sinh"] == (None, None) and out["que_quan"] == (None, None) and "extra" not in out
    rows = parse_output('{"giao_dich": {"raw": [{"ngay": "01/01/2026"}], "page": 1}}', DocType.SAO_KE)
    assert json.loads(rows["giao_dich"][0]) == [{"ngay": "01/01/2026"}]
    with pytest.raises(ValueError):
        parse_output("xin lỗi, tôi không đọc được", DocType.CCCD)


@pytest.fixture
def img(tmp_path):
    p = tmp_path / "a.jpg"
    Image.new("RGB", (40, 30), "white").save(p)
    return p


def test_retry_then_give_up(tmp_path, img):
    calls = []

    def post(url, key, payload):
        calls.append(url)
        raise urllib.error.URLError("timeout")

    x = VLMExtractor("https://api.test/v1/", "k", "m", cache_dir=tmp_path / "c", post=post)
    r = x.extract("b", "d1", DocType.CCCD, [img])
    assert calls == ["https://api.test/v1/chat/completions"] * 2 and r.n_calls == 2 and len(r.errors) == 2
    assert all(v == (None, None) for v in r.fields.values())
    assert not (tmp_path / "c").exists(), "không cache kết quả lỗi"


def test_retry_recovers_and_caches(tmp_path, img):
    replies = [reply("không phải json"), reply({"ho_ten": {"raw": "AN", "page": 1}})]
    x = VLMExtractor("u", "k", "m", cache_dir=tmp_path / "c", price_in=1.0, price_out=2.0,
                     post=lambda *a: replies.pop(0))
    r = x.extract("b", "d1", DocType.CCCD, [img])
    assert r.fields["ho_ten"] == ("AN", 1) and r.n_calls == 2 and r.errors == []
    assert r.cost_usd == pytest.approx(2 * (1000 * 1.0 + 200 * 2.0) / 1e6)
    again = x.extract("b", "d1", DocType.CCCD, [img])  # cache hit: replies đã rỗng, gọi API sẽ lỗi
    assert again.fields["ho_ten"] == ("AN", 1)
    assert x.extract("b", "d1", DocType.CCCD, [img], variant=1).errors  # variant khác -> không dùng cache


def test_end_to_end_with_fake_api(tmp_path):
    """API giả trả đúng chuỗi đã in -> kết quả phải bằng oracle: escape 0, field acc 100%."""
    manifest = build_split("dev", 16, 5, None, images=False)
    by_image = {}
    i = 0
    for e in manifest:
        for d in e["docs"]:
            for f in d["files"]:
                p = tmp_path / f
                p.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (20 + i % 200, 20 + i // 200)).save(p)  # ảnh khác nhau để nhận diện
                i += 1
            first = tmp_path / d["files"][0]
            payload = {k: {"raw": json.loads(v["raw"]) if k == "giao_dich" else v["raw"], "page": v["page"]}
                       for k, v in d["fields_raw"].items()}
            for variant in (0, 1):
                by_image[encode_image(first, variant)] = payload

    def post(url, key, body):
        return reply(by_image[body["messages"][1]["content"][1]["image_url"]["url"]])

    x = VLMExtractor("u", "k", "fake-vlm", cache_dir=tmp_path / "cache", post=post)
    cfg, thr = load_rules(), load_thresholds()
    traces = {e["bundle_id"]: run_bundle(bundle_input_from_manifest(e, tmp_path), x, cfg, thr) for e in manifest}
    m, _ = compute_metrics(manifest, traces, thr)
    assert m["extraction"]["field_accuracy"]["acc"] == 1.0
    assert m["end_to_end"]["escape_rate"] == 0 and m["end_to_end"]["false_review_rate"] == 0
    assert m["ops"]["docs_extract_failed"] == 0
