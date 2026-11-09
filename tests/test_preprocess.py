"""Deskew: tìm đúng góc, không đụng ảnh không đủ chắc, và không dùng nhầm cache của ảnh gốc."""

import json

import pytest
from PIL import Image, ImageDraw

from loanpipe.extract.vlm import VLMExtractor
from loanpipe.preprocess import deskew, estimate_skew
from loanpipe.schemas import DocType


def page() -> Image.Image:
    img = Image.new("RGB", (800, 1000), "white")
    d = ImageDraw.Draw(img)
    for y in range(60, 940, 40):
        d.rectangle((60, y, 740, y + 12), fill="black")
    return img


@pytest.mark.parametrize("angle", [-3.0, -1.5, 1.5, 3.0])
def test_recovers_known_rotation(angle):
    tilted = page().rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white")
    assert estimate_skew(tilted) == pytest.approx(-angle, abs=0.3)
    assert deskew(tilted).size != tilted.size


def test_leaves_straight_and_blank_pages_alone():
    assert estimate_skew(page()) == 0
    blank = Image.new("RGB", (400, 300), "white")
    assert deskew(blank) is blank


def test_cache_is_separate_per_preprocess_mode(tmp_path):
    f = tmp_path / "a.jpg"
    page().rotate(2, expand=True, fillcolor="white").save(f)
    images = []

    def post(url, key, payload):
        images.append(payload["messages"][1]["content"][1]["image_url"]["url"])
        return {"choices": [{"message": {"content": json.dumps({"ho_ten": "AN"})}}]}

    def run(on):
        x = VLMExtractor("https://api.test/v1", "k", "m", cache_dir=tmp_path / "c", post=post, preprocess=on)
        x.extract("b", "d", DocType.CCCD, [f])
        return x.prompt_version

    assert run(False) == "v4" and run(False) == "v4" and len(images) == 1  # lần 2 đọc cache
    assert run(True) == "v4+deskew" and len(images) == 2 and images[0] != images[1]
