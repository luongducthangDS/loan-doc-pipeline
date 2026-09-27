import random
from collections import Counter

import pytest
from PIL import Image, ImageDraw, ImageFont

from datagen.augment import LEVELS, augment
from datagen.build import build_split
from datagen.render import _FONT_SETS, font_paths, render_bundle
from datagen.truth import DOC_IDS, generate_bundle, plan
from loanpipe.config import load_rules, load_thresholds
from loanpipe.evaluate import gt_value
from loanpipe.router import route
from loanpipe.rules import BundleView, run_rules
from loanpipe.schemas import DOC_MODELS, ERROR_RULE, ErrorCode, Field, NearMiss, field_kinds
from loanpipe.validate import finalize_field

N = 600


@pytest.fixture(scope="module")
def bundles():
    rng = random.Random(7)
    return [generate_bundle(rng, f"b{i}", e, nm) for i, (e, nm) in enumerate(plan(N, rng))]


def test_deterministic():
    a = build_split("dev", 8, 1, None, images=False)
    b = build_split("dev", 8, 1, None, images=False)
    assert a == b


def test_distribution(bundles):
    err = [b for b in bundles if b.errors]
    assert len(err) == N // 2
    two = sum(len(b.errors) == 2 for b in err)
    assert 0.08 <= two / len(err) <= 0.12
    primary = Counter(b.errors[0] for b in err)
    assert max(primary.values()) - min(primary.values()) <= 1, "mã lỗi chia đều"
    nm = [b for b in bundles if b.near_miss]
    assert len(nm) == round(N / 2 / 3) and set(Counter(b.near_miss[0] for b in nm)) == set(NearMiss)
    assert all(ErrorCode.E8_MISSING_DOC not in b.errors or len(b.errors) == 1 for b in bundles)


def test_labels_agree_with_rules_on_ground_truth(bundles):
    """Chạy rule trên GIÁ TRỊ ĐÚNG: mọi lỗi cài phải bị đúng rule bắt, bộ sạch/near-miss không bị gắn cờ."""
    cfg, thr = load_rules(), load_thresholds()
    for b in bundles:
        view = BundleView({dt: {k: Field(value=getattr(doc, k), raw="x", confidence="high")
                                for k in type(doc).model_fields} for dt, doc in b.docs.items()})
        checks = {c.rule_id: c.status for c in run_rules(view, cfg)}
        for e in b.errors:
            assert checks[ERROR_RULE[e]] == "fail", (b.bundle_id, e)
        if not b.errors:
            assert "fail" not in checks.values(), (b.bundle_id, b.near_miss, checks)
        assert route(b.bundle_id, view, list(map(_cr, checks.items())), cfg, thr).route == b.expected_route


def _cr(item):
    from loanpipe.schemas import CheckResult
    return CheckResult(rule_id=item[0], status=item[1])


@pytest.mark.parametrize("layout", "ABC")
def test_render_raw_roundtrips_to_ground_truth(bundles, layout):
    """Mọi field đều được in, và chuẩn hóa chuỗi đã in cho lại đúng giá trị ground truth."""
    rng = random.Random(layout)
    for b in bundles[:12]:
        for rd in render_bundle(b, {"don_vay": layout, "hdld": layout, "sao_ke": layout}, "NGÂN HÀNG X", rng):
            assert set(rd.raw) == set(DOC_MODELS[rd.doc_type].model_fields)
            gt = b.docs[rd.doc_type].model_dump(mode="json")
            for name, kind in field_kinds(rd.doc_type).items():
                f = finalize_field(kind, rd.raw[name][0])
                assert f.error is None, (layout, name, rd.raw[name])
                assert Field(value=f.value).model_dump(mode="json")["value"] == \
                    Field(value=gt_value(kind, gt[name])).model_dump(mode="json")["value"], (layout, name)


def test_augment_levels_run():
    img = Image.new("RGB", (300, 400), "white")
    for level in LEVELS:
        out = augment(img, level, random.Random(0))
        assert out.mode == "RGB" and min(out.size) >= 300


def test_doc_ids_stable():
    assert [DOC_IDS[k] for k in DOC_IDS] == ["d1", "d2", "d3", "d4"]


def test_fonts_have_vietnamese_glyphs():
    def draw(font, ch):
        img = Image.new("L", (40, 40))
        ImageDraw.Draw(img).text((5, 5), ch, fill=255, font=font)
        return img.tobytes()

    for family in _FONT_SETS:
        for path in font_paths(family):
            f = ImageFont.truetype(path, 24)
            tofu = draw(f, chr(0xFFFF))
            for ch in "ựộờẫđƯốỐ":
                assert draw(f, ch) != tofu, f"{path} thiếu glyph {ch!r}"
