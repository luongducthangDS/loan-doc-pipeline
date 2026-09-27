"""Render Application -> ảnh từng giấy tờ, kèm nhiễu scan 3 mức.

ponytail: vẽ text thẳng bằng PIL, không dùng HTML/Playwright/Augraphy.
Nâng cấp khi layout đơn giản làm extractor đạt ~100% (tức là test quá dễ).
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from schemas import Application, LoaiHDLD

WATERMARK = "MẪU – DỮ LIỆU TỔNG HỢP – KHÔNG CÓ GIÁ TRỊ PHÁP LÝ"
NOISE_LEVELS = ("clean", "light", "heavy")
_FONTS = [
    "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/tahoma.ttf",
    # Linux: chỉ font có đủ dấu tiếng Việt (Liberation thiếu glyph ư/ơ/ộ -> ô vuông)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]


def _fonts() -> list[str]:
    found = [f for f in _FONTS if Path(f).exists()]
    if not found:
        raise RuntimeError("Không tìm thấy font có dấu tiếng Việt; thêm đường dẫn vào _FONTS")
    return found


# --- Định dạng: cố ý đa dạng để kiểm tra bước chuẩn hóa ----------------------

def _money(rng: random.Random, v: int) -> str:
    dotted = f"{v:,}".replace(",", ".")
    styles = [f"{dotted} đồng", f"{dotted} VNĐ", f"{dotted}đ"]
    if v % 500_000 == 0:
        tr = f"{v / 1e6:g}".replace(".", ",")
        styles.append(f"{tr} triệu")
    return rng.choice(styles)


def _date(rng: random.Random, d: date | None, long_ok: bool = False) -> str:
    if d is None:
        return "Không xác định"
    styles = [f"{d:%d/%m/%Y}", f"{d:%d-%m-%Y}"]
    if long_ok:
        styles.append(f"ngày {d.day:02d} tháng {d.month:02d} năm {d.year}")
    return rng.choice(styles)


# --- Nội dung: list[(text, style)]; style True=đậm, False=thường, "mono"=bảng ---

def _lines(app: Application, rng: random.Random) -> dict[str, list[tuple[str, bool | str]]]:
    out: dict[str, list[tuple[str, bool | str]]] = {}
    if c := app.cccd:
        out["cccd"] = [
            ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", True), ("CĂN CƯỚC CÔNG DÂN", True), ("", False),
            (f"Số / No.: {c.so_cccd}", True),
            (f"Họ và tên / Full name: {c.ho_ten.upper()}", False),
            (f"Ngày sinh / Date of birth: {c.ngay_sinh:%d/%m/%Y}", False),
            (f"Giới tính / Sex: {c.gioi_tinh}      Quốc tịch: Việt Nam", False),
            (f"Nơi thường trú: {c.noi_thuong_tru}", False),
            (f"Có giá trị đến / Date of expiry: {c.ngay_het_han:%d/%m/%Y}", False),
        ]
    if h := app.hdld:
        loai = ("Xác định thời hạn" if h.loai_hop_dong is LoaiHDLD.XAC_DINH_THOI_HAN
                else "Không xác định thời hạn")
        out["hdld"] = [
            ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", True), ("Độc lập - Tự do - Hạnh phúc", False),
            ("", False), ("HỢP ĐỒNG LAO ĐỘNG", True), ("", False),
            (f"Bên A (Người sử dụng lao động): {h.ten_don_vi}", False),
            (f"Bên B (Người lao động): {h.ten_nguoi_lao_dong}", False),
            (f"Số CCCD: {h.so_cccd}", False),
            (f"Chức danh chuyên môn: {h.chuc_danh}", False),
            (f"Loại hợp đồng: {loai}", False),
            (f"Thời hạn: từ {_date(rng, h.ngay_bat_dau, True)} đến {_date(rng, h.ngay_ket_thuc, True)}", False),
            (f"Mức lương chính: {_money(rng, h.muc_luong)}/tháng", False),
            ("Hình thức trả lương: Chuyển khoản, trước ngày 10 hằng tháng.", False),
        ]
    if s := app.sao_ke:
        rows = [(f"{g.ngay:%d/%m/%Y}  {g.mo_ta[:52]:<52} "
                 f"{(f'{g.so_tien:,}' if g.so_tien > 0 else ''):>12} "
                 f"{(f'{-g.so_tien:,}' if g.so_tien < 0 else ''):>12}", "mono")
                for g in s.giao_dich]
        out["sao_ke"] = [
            (s.ngan_hang, True), ("SAO KÊ TÀI KHOẢN", True),
            (f"Chủ tài khoản: {s.chu_tai_khoan}    Số TK: {s.so_tai_khoan}", False),
            (f"Từ ngày {s.tu_ngay:%d/%m/%Y} đến ngày {s.den_ngay:%d/%m/%Y}", False), ("", False),
            (f"{'Ngày':<10}  {'Nội dung':<52} {'Ghi có':>12} {'Ghi nợ':>12}", "mono"),
            *rows,
        ]
    d = app.de_nghi_vay
    out["de_nghi_vay"] = [
        ("GIẤY ĐỀ NGHỊ VAY VỐN KIÊM PHƯƠNG ÁN TRẢ NỢ", True), ("", False),
        (f"Họ và tên khách hàng: {d.ho_ten}", False),
        (f"Số CCCD: {d.so_cccd}", False),
        (f"Số tiền đề nghị vay: {_money(rng, d.so_tien_vay)}", False),
        (f"Thời hạn vay: {d.thoi_han_thang} tháng", False),
        (f"Mục đích vay: {d.muc_dich}", False),
        (f"Thu nhập thực nhận hằng tháng: {_money(rng, d.thu_nhap_khai_bao)}", False),
        (f"Nghĩa vụ trả nợ hiện tại hằng tháng: {_money(rng, d.no_hien_tai_hang_thang)}", False),
        ("", False), (f"Hà Nội, {_date(rng, d.ngay_nop, True)}", False),
    ]
    return out


def _draw(lines: list[tuple[str, bool | str]], font_path: str, size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, "white")
    dr = ImageDraw.Draw(img)
    fs = 26 if size[0] < 1200 else 22
    font = ImageFont.truetype(font_path, fs)
    mono = ImageFont.truetype(_mono(), fs - 6)
    y = 60
    for text, bold in lines:
        f = mono if bold == "mono" else font
        dr.text((50, y), text, fill="black", font=f, stroke_width=1 if bold is True else 0)
        y += fs + 12
    small = ImageFont.truetype(font_path, 16)
    dr.text((50, 15), WATERMARK, fill=(170, 170, 170), font=small)
    dr.text((50, size[1] - 35), WATERMARK, fill=(170, 170, 170), font=small)
    return img


def _mono() -> str:
    for f in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if Path(f).exists():
            return f
    return _fonts()[0]


def degrade(img: Image.Image, level: str, rng: random.Random) -> Image.Image:
    if level == "clean":
        return img
    heavy = level == "heavy"
    img = img.rotate(rng.uniform(-3, 3) if heavy else rng.uniform(-1, 1),
                     expand=True, fillcolor=(235, 235, 230))
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.4) if heavy else 0.5))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.6, 0.8) if heavy else 0.9)
    noise = Image.effect_noise(img.size, 40 if heavy else 15).convert("RGB")
    return Image.blend(img, noise, 0.12 if heavy else 0.05)


def render(app: Application, out_dir: Path, rng: random.Random) -> dict[str, str]:
    """Ghi ảnh từng giấy tờ vào out_dir. Trả về {doc_type: noise_level}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    font = rng.choice(_fonts())
    levels = {}
    for doc, lines in _lines(app, rng).items():
        size = (1000, 630) if doc == "cccd" else (1240, 1754)
        level = rng.choice(NOISE_LEVELS)
        img = degrade(_draw(lines, font, size), level, rng)
        img.save(out_dir / f"{doc}.jpg", quality=95 if level == "clean" else 70)
        levels[doc] = level
    return levels
