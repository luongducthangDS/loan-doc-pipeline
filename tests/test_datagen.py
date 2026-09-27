import random
from datetime import date

import pytest

from datagen.render import render
from datagen.truth import INCOME_THRESHOLD, generate, salary_avg
from normalize import name_key, parse_date, parse_money
from schemas import BenignCode, CaseType, ErrorCode

APPS = generate(600, seed=7)


def by(code):
    return [a for a in APPS if code in a.errors + a.benign]


def test_normalize():
    assert name_key("Nguyễn  văn Đức") == "NGUYEN VAN DUC"
    for s, v in [("15.000.000đ", 15_000_000), ("15.000.000 VNĐ", 15_000_000),
                 ("15 triệu", 15_000_000), ("15,5 triệu", 15_500_000),
                 ("1.500 triệu", 1_500_000_000), ("2 tỷ", 2_000_000_000)]:
        assert parse_money(s) == v, s
    for s in ["26/09/2026", "26-09-2026", "2026-09-26", "ngày 26 tháng 09 năm 2026"]:
        assert parse_date(s) == date(2026, 9, 26), s
    with pytest.raises(ValueError):
        parse_date("không rõ")


def test_deterministic_and_distribution():
    assert generate(600, seed=7) == APPS
    share = {c: sum(a.case is c for a in APPS) / len(APPS) for c in CaseType}
    assert 0.5 < share[CaseType.CLEAN] < 0.7
    counts = {len(by(c)) for c in [*ErrorCode, *BenignCode]}
    assert counts == {24}, "phân tầng: mỗi mã đúng round(600*0.4/10) = 24 mẫu"


def test_labels_match_data():
    for a in by(ErrorCode.INCOME_INFLATED):
        assert a.de_nghi_vay.thu_nhap_khai_bao / salary_avg(a.sao_ke) > INCOME_THRESHOLD
    for a in by(BenignCode.NEAR_THRESHOLD_INCOME) + by(BenignCode.SALARY_PAID_LATE):
        assert a.de_nghi_vay.thu_nhap_khai_bao / salary_avg(a.sao_ke) <= INCOME_THRESHOLD
    for a in by(ErrorCode.CONTRACT_EXPIRED):
        assert a.hdld.ngay_ket_thuc < a.de_nghi_vay.ngay_nop
    for a in by(ErrorCode.CCCD_EXPIRED):
        assert a.cccd.ngay_het_han < a.de_nghi_vay.ngay_nop
    for a in by(BenignCode.CCCD_EXPIRES_SOON):
        assert a.cccd.ngay_het_han >= a.de_nghi_vay.ngay_nop
    for a in by(ErrorCode.NAME_MISMATCH):
        assert name_key(a.hdld.ten_nguoi_lao_dong) != name_key(a.cccd.ho_ten)
    for a in by(ErrorCode.ID_MISMATCH):
        assert a.de_nghi_vay.so_cccd != a.cccd.so_cccd
    for a in by(ErrorCode.MISSING_DOC):
        assert None in (a.cccd, a.hdld, a.sao_ke)
    for a in [a for a in APPS if a.case is CaseType.CLEAN]:
        assert None not in (a.cccd, a.hdld, a.sao_ke)
        assert a.hdld.ngay_ket_thuc is None or a.hdld.ngay_ket_thuc > a.de_nghi_vay.ngay_nop
        assert len({name_key(x) for x in (a.cccd.ho_ten, a.hdld.ten_nguoi_lao_dong,
                                          a.sao_ke.chu_tai_khoan, a.de_nghi_vay.ho_ten)}) == 1


def test_render_smoke(tmp_path):
    levels = render(APPS[0], tmp_path, random.Random(0))
    assert levels and all((tmp_path / f"{d}.jpg").exists() for d in levels)


def test_fonts_have_vietnamese_glyphs():
    from PIL import Image, ImageDraw, ImageFont

    from datagen.render import _fonts

    def draw(font, ch):
        img = Image.new("L", (40, 40))
        ImageDraw.Draw(img).text((5, 5), ch, fill=255, font=font)
        return img.tobytes()

    for path in _fonts():
        f = ImageFont.truetype(path, 24)
        tofu = draw(f, chr(0xFFFF))  # ký tự chắc chắn không có glyph
        for ch in "ựộờẫđƯ":
            assert draw(f, ch) != tofu, f"{path} thiếu glyph {ch!r}"
