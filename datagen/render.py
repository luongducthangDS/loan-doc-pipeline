"""Render ground truth -> ảnh từng trang giấy tờ, kèm chuỗi raw đúng như đã in (spec mục 5).

Mỗi loại giấy tờ có 3 layout A/B/C khác nhau về: thứ tự field, cách gọi nhãn, định dạng ngày/tiền,
bố cục (dòng, bảng 2 cột, form điền tay) và font. Layout C chỉ xuất hiện ở test (held-out).
CCCD chỉ có 1 mẫu thẻ (spec: thẻ căn cước mẫu mới để sau MVP) nên luôn là layout A.

Vẽ bằng PIL thay vì HTML + WeasyPrint/Playwright như spec đề xuất: không cần dependency hệ thống,
chạy được trên Windows, và đủ tạo khác biệt layout. Nâng cấp nếu extractor đạt ~100% (test quá dễ).
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from datagen.truth import BundleTruth
from loanpipe.schemas import Cccd, DocType, DonVay, Hdld, LoaiHd, SaoKe

WATERMARK = "MẪU – DỮ LIỆU TỔNG HỢP – KHÔNG CÓ GIÁ TRỊ PHÁP LÝ"
A4 = (1240, 1754)  # 150 dpi
CARD = (1300, 820)

_W = "C:/Windows/Fonts/"
_DJ = "/usr/share/fonts/truetype/dejavu/"
# family -> các cặp (thường, đậm, nghiêng) theo thứ tự ưu tiên; chỉ font có đủ dấu tiếng Việt
_FONT_SETS = {
    "sans": [(_W + "arial.ttf", _W + "arialbd.ttf", _W + "ariali.ttf"),
             (_DJ + "DejaVuSans.ttf", _DJ + "DejaVuSans-Bold.ttf", _DJ + "DejaVuSans-Oblique.ttf")],
    "serif": [(_W + "times.ttf", _W + "timesbd.ttf", _W + "timesi.ttf"),
              (_DJ + "DejaVuSerif.ttf", _DJ + "DejaVuSerif-Bold.ttf", _DJ + "DejaVuSerif-Italic.ttf")],
    "cond": [(_W + "tahoma.ttf", _W + "tahomabd.ttf", _W + "ariali.ttf"),
             (_DJ + "DejaVuSansCondensed.ttf", _DJ + "DejaVuSansCondensed-Bold.ttf",
              _DJ + "DejaVuSansCondensed-Oblique.ttf")],
}


@lru_cache
def font_paths(family: str) -> tuple[str, str, str]:
    for fam in [family, *_FONT_SETS]:
        for trio in _FONT_SETS[fam]:
            if Path(trio[0]).exists():
                return tuple(p if Path(p).exists() else trio[0] for p in trio)
    raise RuntimeError("Không tìm thấy font có dấu tiếng Việt; thêm đường dẫn vào _FONT_SETS")


@lru_cache
def _font(family: str, size: int, style: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_paths(family)[style], size)


# --- Định dạng giá trị ----------------------------------------------------------

def fmt_date(d: date, style: str) -> str:
    return {"slash": f"{d:%d/%m/%Y}", "dash": f"{d:%d-%m-%Y}", "dot": f"{d:%d.%m.%Y}",
            "long": f"ngày {d.day:02d} tháng {d.month:02d} năm {d.year}"}[style]


def fmt_money(v: int, style: str) -> str:
    dotted, comma = f"{v:,}".replace(",", "."), f"{v:,}"
    if style == "trieu" and v % 100_000 == 0 and v >= 1_000_000:
        return f"{v / 1e6:g}".replace(".", ",") + " triệu đồng"
    return {"dong": f"{dotted} đồng", "vnd": f"{dotted} VNĐ", "d": f"{dotted}đ",
            "comma": f"{comma} VND", "trieu": f"{dotted} đồng"}[style]


def fmt_account(s: str, grouped: bool) -> str:
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4)) if grouped else s


def fmt_phone(s: str, grouped: bool) -> str:
    return f"{s[:4]} {s[4:7]} {s[7:]}" if grouped else s


# --- Canvas nhiều trang ------------------------------------------------------------

@dataclass
class Style:
    family: str = "sans"
    size: int = 24
    margin: int = 90
    line_gap: int = 12
    value_style: int = 0  # 0 thường, 2 nghiêng (giả lập chữ điền tay)


@dataclass
class Canvas:
    style: Style
    size: tuple[int, int] = A4
    bg: str = "white"
    pages: list[Image.Image] = field(default_factory=list)
    raw: dict[str, tuple[str, int]] = field(default_factory=dict)  # field -> (raw, page 1-based)
    y: int = 0
    left: int | None = None  # lề trái riêng (vd cột chữ bên phải ảnh trên thẻ CCCD)

    @property
    def x0(self) -> int:
        return self.style.margin if self.left is None else self.left

    def __post_init__(self) -> None:
        self.new_page()

    # tiện ích
    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(self.pages[-1])

    @property
    def page_no(self) -> int:
        return len(self.pages)

    def f(self, scale: float = 1.0, style: int = 0) -> ImageFont.FreeTypeFont:
        return _font(self.style.family, round(self.style.size * scale), style)

    def lh(self, scale: float = 1.0) -> int:
        return round(self.style.size * scale) + self.style.line_gap

    def new_page(self) -> None:
        self.pages.append(Image.new("RGB", self.size, self.bg))
        self.y = self.style.margin

    def ensure(self, h: int) -> None:
        if self.y + h > self.size[1] - self.style.margin:
            self.new_page()

    def record(self, name: str | None, raw: str) -> None:
        if name:
            self.raw[name] = (raw, self.page_no)

    def wrap(self, text: str, font, width: int) -> list[str]:
        lines, cur = [], ""
        for w in text.split(" "):
            t = f"{cur} {w}" if cur else w
            if self.draw.textlength(t, font=font) <= width or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        return lines + [cur]

    # khối nội dung
    def gap(self, h: int = 20) -> None:
        self.y += h

    def text(self, text: str, scale: float = 1.0, bold: bool = False, align: str = "left",
             x: int | None = None, color: str = "black") -> None:
        font = self.f(scale, 1 if bold else 0)
        width = self.size[0] - self.style.margin - self.x0
        for line in self.wrap(text, font, width):
            self.ensure(self.lh(scale))
            tw = self.draw.textlength(line, font=font)
            xx = x if x is not None else {"left": self.x0, "right": self.size[0] - self.style.margin - tw,
                                          "center": (self.size[0] - tw) / 2}[align]
            self.draw.text((xx, self.y), line, fill=color, font=font)
            self.y += self.lh(scale)

    def kv(self, label: str, value: str, name: str | None = None, sep: str = ": ",
           leader: bool = False, indent: int = 0) -> None:
        """'Nhãn: giá trị' trên cùng dòng, giá trị dài thì xuống dòng thẳng cột."""
        m = self.x0 + indent
        lf, vf = self.f(), self.f(1.0, self.style.value_style)
        label_t = label + sep
        lw = self.draw.textlength(label_t, font=lf)
        width = self.size[0] - self.style.margin - m - lw
        lines = self.wrap(value, vf, width)
        self.ensure(self.lh() * len(lines))
        self.record(name, value)
        self.draw.text((m, self.y), label_t, fill="black", font=lf)
        for i, line in enumerate(lines):
            if leader and i == 0:  # dòng chấm của form điền tay
                self.draw.text((m + lw, self.y + 4), "." * int(width / self.draw.textlength(".", font=lf)),
                               fill=(150, 150, 150), font=lf)
            self.draw.text((m + lw + (12 if leader else 0), self.y - (3 if leader else 0)), line,
                           fill=(20, 30, 120) if leader else "black", font=vf)
            self.y += self.lh()

    def kv_table(self, rows: list[tuple[str, str, str | None]], label_frac: float = 0.38) -> None:
        """Bảng 2 cột có kẻ viền: nhãn | giá trị."""
        m, W = self.style.margin, self.size[0] - 2 * self.style.margin
        lw = int(W * label_frac)
        f = self.f()
        for label, value, name in rows:
            ll, vl = self.wrap(label, f, lw - 20), self.wrap(value, f, W - lw - 20)
            h = self.lh() * max(len(ll), len(vl)) + 12
            self.ensure(h)
            self.record(name, value)
            d = self.draw
            d.rectangle([m, self.y, m + lw, self.y + h], outline="black", fill=(242, 242, 242))
            d.rectangle([m + lw, self.y, m + W, self.y + h], outline="black")
            for i, t in enumerate(ll):
                d.text((m + 10, self.y + 6 + i * self.lh()), t, fill="black", font=f)
            for i, t in enumerate(vl):
                d.text((m + lw + 10, self.y + 6 + i * self.lh()), t, fill="black", font=f)
            self.y += h

    def table(self, headers: list[str], widths: list[float], rows: list[list[str]],
              aligns: list[str], scale: float = 0.8) -> None:
        """Bảng giao dịch; tràn trang thì sang trang mới và lặp lại header."""
        m, W = self.style.margin, self.size[0] - 2 * self.style.margin
        xs = [m + int(W * sum(widths[:i])) for i in range(len(widths) + 1)]
        f, fb = self.f(scale), self.f(scale, 1)
        h = self.lh(scale) + 8

        def header() -> None:
            self.draw.rectangle([m, self.y, m + W, self.y + h], fill=(225, 225, 225), outline="black")
            for i, t in enumerate(headers):
                self.draw.text((xs[i] + 6, self.y + 4), t, fill="black", font=fb)
            self.y += h

        self.ensure(2 * h)
        header()
        for row in rows:
            # ô chữ dài thì xuống dòng (không cắt: raw phải khớp đúng chữ in trên ảnh)
            cells = [self.wrap(t, f, xs[i + 1] - xs[i] - 12) if aligns[i] == "l" else [t]
                     for i, t in enumerate(row)]
            rh = self.lh(scale) * max(map(len, cells)) + 8
            if self.y + rh > self.size[1] - self.style.margin - 40:
                self.new_page()
                header()
            self.draw.line([m, self.y + rh, m + W, self.y + rh], fill=(190, 190, 190))
            for i, lines in enumerate(cells):
                for k, t in enumerate(lines):
                    tx = xs[i] + 6 if aligns[i] == "l" else xs[i + 1] - 6 - self.draw.textlength(t, font=f)
                    self.draw.text((tx, self.y + 4 + k * self.lh(scale)), t, fill="black", font=f)
            self.y += rh

    def finish(self, footer: Callable[[int, int], str] | None = None) -> list[Image.Image]:
        wf = _font("sans", 16)
        for i, pg in enumerate(self.pages, 1):
            d = ImageDraw.Draw(pg)
            d.text((self.style.margin, 22), WATERMARK, fill=(165, 165, 165), font=wf)
            d.text((self.style.margin, self.size[1] - 40), WATERMARK, fill=(165, 165, 165), font=wf)
            if footer:
                t = footer(i, len(self.pages))
                d.text((self.size[0] - self.style.margin - d.textlength(t, font=wf), self.size[1] - 40),
                       t, fill="black", font=wf)
        return self.pages


def _letterhead(c: Canvas, bank: str, rng: random.Random) -> None:
    m = c.style.margin
    initials = "".join(w[0] for w in bank.replace("(GIẢ LẬP)", "").split()[-2:])
    c.draw.ellipse([m, c.y, m + 70, c.y + 70], outline=(20, 60, 140), width=4)
    c.draw.text((m + 12, c.y + 18), initials, fill=(20, 60, 140), font=c.f(1.1, 1))
    c.draw.text((m + 90, c.y + 18), bank, fill=(20, 60, 140), font=c.f(0.95, 1))
    c.y += 95
    c.draw.line([m, c.y, c.size[0] - m, c.y], fill=(20, 60, 140), width=2)
    c.gap(20)


def _quoc_hieu(c: Canvas) -> None:
    c.text("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 1.0, bold=True, align="center")
    c.text("Độc lập - Tự do - Hạnh phúc", 0.95, align="center")
    c.text("―――――――――――", 0.8, align="center")


# --- CCCD (1 mẫu thẻ, 2 mặt) ------------------------------------------------------------

def render_cccd(doc: Cccd, rng: random.Random) -> tuple[list[Image.Image], dict]:
    st = Style(family="sans", size=26, margin=40, line_gap=10)
    raw: dict[str, tuple[str, int]] = {}
    pages = []
    for side in ("front", "back"):
        c = Canvas(st, CARD, bg=(236, 244, 238))
        d = c.draw
        d.rounded_rectangle([8, 8, CARD[0] - 8, CARD[1] - 8], radius=36, outline=(90, 120, 100), width=4)
        if side == "front":
            c.y = 36
            c.text("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 0.85, bold=True, align="center")
            c.text("Độc lập - Tự do - Hạnh phúc", 0.8, align="center")
            c.text("CĂN CƯỚC CÔNG DÂN", 1.25, bold=True, align="center", color=(170, 20, 20))
            c.text("Citizen Identity Card", 0.7, align="center")
            d.rectangle([50, 230, 330, 580], fill=(205, 212, 208), outline=(120, 120, 120))
            d.text((140, 390), "ẢNH", fill=(120, 120, 120), font=c.f(1.2, 1))
            c.left = 360
            c.y = 225
            rows = [("Số / No.", doc.so_cccd, "so_cccd"),
                    ("Họ và tên / Full name", doc.ho_ten.upper(), "ho_ten"),
                    ("Ngày sinh / Date of birth", fmt_date(doc.ngay_sinh, "slash"), "ngay_sinh"),
                    ("Giới tính / Sex", doc.gioi_tinh, "gioi_tinh"),
                    ("Quê quán / Place of origin", doc.que_quan, "que_quan"),
                    ("Nơi thường trú / Place of residence", doc.noi_thuong_tru, "noi_thuong_tru")]
            for label, value, name in rows:
                c.text(label + ":", 0.62)
                c.y -= 6
                c.kv("", value, name, sep="")
            c.left = None
            c.y = max(c.y + 5, 700)
            c.kv("Có giá trị đến / Date of expiry", fmt_date(doc.ngay_het_han, "slash"), "ngay_het_han")
        else:
            c.y = 60
            c.text("Đặc điểm nhân dạng / Personal identification:", 0.8)
            c.text("Nốt ruồi C:1cm trên sau đuôi mắt trái", 0.8)
            c.gap(30)
            c.kv("Ngày, tháng, năm / Date, month, year", fmt_date(doc.ngay_cap, "slash"), "ngay_cap")
            c.text("CỤC TRƯỞNG CỤC CẢNH SÁT", 0.8, bold=True, align="right")
            c.text("QUẢN LÝ HÀNH CHÍNH VỀ TRẬT TỰ XÃ HỘI", 0.8, bold=True, align="right")
            c.gap(80)
            c.text("(Đã ký – dữ liệu giả lập)", 0.7, align="right")
            d.rectangle([60, 540, 320, 760], outline=(120, 120, 120))
            d.text((90, 640), "Vân tay", fill=(120, 120, 120), font=c.f(0.8))
        if len(c.pages) != 1:
            raise RuntimeError(f"nội dung CCCD tràn khỏi thẻ ({side})")
        page = len(pages) + 1
        raw.update({k: (v, page) for k, (v, _) in c.raw.items()})
        pages += c.finish()
    return pages, raw


# --- Giấy đề nghị vay vốn -------------------------------------------------------------------

def render_don_vay(doc: DonVay, layout: str, bank: str, rng: random.Random) -> tuple[list[Image.Image], dict]:
    if layout == "A":
        c = Canvas(Style("sans", 24))
        _letterhead(c, bank, rng)
        c.text("GIẤY ĐỀ NGHỊ VAY VỐN KIÊM PHƯƠNG ÁN TRẢ NỢ", 1.2, bold=True, align="center")
        c.gap(15)
        c.text("I. THÔNG TIN KHÁCH HÀNG", bold=True)
        c.kv("Họ và tên", doc.ho_ten, "ho_ten")
        c.kv("Ngày sinh", fmt_date(doc.ngay_sinh, "slash"), "ngay_sinh")
        c.kv("Số CCCD", doc.so_cccd, "so_cccd")
        c.kv("Điện thoại", fmt_phone(doc.so_dien_thoai, False), "so_dien_thoai")
        c.kv("Địa chỉ thường trú", doc.dia_chi, "dia_chi")
        c.kv("Nơi công tác", doc.ten_cong_ty, "ten_cong_ty")
        c.kv("Thu nhập thực nhận hằng tháng", fmt_money(doc.thu_nhap_thang, rng.choice(["dong", "vnd"])),
             "thu_nhap_thang")
        c.kv("Số tài khoản nhận lương", fmt_account(doc.so_tk_nhan_luong, False), "so_tk_nhan_luong")
        c.gap(15)
        c.text("II. THÔNG TIN KHOẢN VAY", bold=True)
        c.kv("Số tiền đề nghị vay", fmt_money(doc.so_tien_vay, "dong"), "so_tien_vay")
        c.kv("Thời hạn vay", f"{doc.thoi_han_thang} tháng", "thoi_han_thang")
        c.kv("Mục đích vay", doc.muc_dich, "muc_dich")
        c.gap(30)
        ky = fmt_date(doc.ngay_ky, "long")
        c.text(f"Hà Nội, {ky}", align="right")
        c.record("ngay_ky", ky)
        c.text("NGƯỜI ĐỀ NGHỊ VAY", bold=True, align="right")
        c.text("(Ký, ghi rõ họ tên)", 0.85, align="right")
    elif layout == "B":
        c = Canvas(Style("serif", 25))
        c.text(bank, 0.9, bold=True)
        c.gap(20)
        c.text("ĐƠN ĐỀ NGHỊ VAY TIÊU DÙNG", 1.3, bold=True, align="center")
        c.text("(Dành cho khách hàng cá nhân)", 0.85, align="center")
        c.gap(20)
        rows = [("Họ tên người vay", doc.ho_ten, "ho_ten"),
                ("CCCD số", doc.so_cccd, "so_cccd"),
                ("Ngày tháng năm sinh", fmt_date(doc.ngay_sinh, "dash"), "ngay_sinh"),
                ("Số điện thoại di động", fmt_phone(doc.so_dien_thoai, True), "so_dien_thoai"),
                ("Địa chỉ liên hệ", doc.dia_chi, "dia_chi"),
                ("Đơn vị công tác", doc.ten_cong_ty, "ten_cong_ty"),
                ("Thu nhập bình quân/tháng", fmt_money(doc.thu_nhap_thang, rng.choice(["d", "trieu"])),
                 "thu_nhap_thang"),
                ("Tài khoản nhận lương số", fmt_account(doc.so_tk_nhan_luong, True), "so_tk_nhan_luong"),
                ("Số tiền vay", fmt_money(doc.so_tien_vay, "d"), "so_tien_vay"),
                ("Thời hạn vay (tháng)", str(doc.thoi_han_thang), "thoi_han_thang"),
                ("Mục đích sử dụng vốn", doc.muc_dich, "muc_dich")]
        c.kv_table(rows)
        c.gap(40)
        ky = fmt_date(doc.ngay_ky, "slash")
        c.kv("Ngày ký", ky, "ngay_ky", indent=650)
        c.text("Khách hàng ký tên", bold=True, align="right")
    else:  # C: form điền tay, chữ nghiêng màu mực, nhãn và thứ tự khác hẳn (held-out)
        c = Canvas(Style("cond", 23, value_style=2))
        _quoc_hieu(c)
        c.gap(10)
        c.text("PHIẾU ĐĂNG KÝ KHOẢN VAY CÁ NHÂN", 1.25, bold=True, align="center")
        c.text(f"Kính gửi: {bank}", 0.9, align="center")
        c.gap(20)
        c.kv("Tôi tên là", doc.ho_ten, "ho_ten", leader=True)
        c.kv("Sinh ngày", fmt_date(doc.ngay_sinh, rng.choice(["long", "dot"])), "ngay_sinh", leader=True)
        c.kv("Số định danh cá nhân", doc.so_cccd, "so_cccd", leader=True)
        c.kv("Hiện làm việc tại", doc.ten_cong_ty, "ten_cong_ty", leader=True)
        c.kv("Lương/thu nhập mỗi tháng", fmt_money(doc.thu_nhap_thang, "comma"), "thu_nhap_thang", leader=True)
        c.kv("Lương chuyển về tài khoản", fmt_account(doc.so_tk_nhan_luong, False), "so_tk_nhan_luong",
             leader=True)
        c.kv("Chỗ ở hiện nay", doc.dia_chi, "dia_chi", leader=True)
        c.kv("Liên lạc qua số", fmt_phone(doc.so_dien_thoai, True), "so_dien_thoai", leader=True)
        c.gap(10)
        c.text("Đề nghị Ngân hàng cho vay với nội dung sau:", bold=True)
        c.kv("Khoản tiền", fmt_money(doc.so_tien_vay, "comma"), "so_tien_vay", leader=True)
        c.kv("Để dùng vào việc", doc.muc_dich, "muc_dich", leader=True)
        c.kv("Trả dần trong", f"{doc.thoi_han_thang} tháng", "thoi_han_thang", leader=True)
        c.gap(30)
        ky = fmt_date(doc.ngay_ky, "long")
        c.text(f"Làm tại ..................., {ky}", align="right")
        c.record("ngay_ky", ky)
        c.text("Người làm đơn", bold=True, align="right")
    c.gap(40)
    c.text(doc.ho_ten, 1.0, align="right")  # chữ ký ghi rõ họ tên
    return c.finish(), c.raw


# --- Hợp đồng lao động -----------------------------------------------------------------------

def _loai_hd(doc: Hdld) -> str:
    if doc.loai_hd is LoaiHd.KHONG_XAC_DINH_THOI_HAN:
        return "Không xác định thời hạn"
    months = round((doc.ngay_ket_thuc - doc.ngay_bat_dau).days / 30.4)
    return f"Xác định thời hạn {months} tháng"


def _end(doc: Hdld, style: str) -> str:
    return "Không xác định" if doc.ngay_ket_thuc is None else fmt_date(doc.ngay_ket_thuc, style)


def render_hdld(doc: Hdld, layout: str, rng: random.Random) -> tuple[list[Image.Image], dict]:
    if layout == "A":
        c = Canvas(Style("serif", 25))
        _quoc_hieu(c)
        c.gap(10)
        c.text("HỢP ĐỒNG LAO ĐỘNG", 1.3, bold=True, align="center")
        c.gap(10)
        c.kv("Bên A (Người sử dụng lao động)", doc.ten_cong_ty, "ten_cong_ty")
        c.kv("Bên B (Người lao động)", doc.ho_ten_nld, "ho_ten_nld")
        c.kv("Chức danh chuyên môn", doc.chuc_danh, "chuc_danh")
        c.kv("Loại hợp đồng", _loai_hd(doc), "loai_hd")
        c.kv("Từ ngày", fmt_date(doc.ngay_bat_dau, "slash"), "ngay_bat_dau")
        c.kv("Đến ngày", _end(doc, "slash"), "ngay_ket_thuc")
        c.kv("Mức lương chính", fmt_money(doc.muc_luong, "dong") + "/tháng", "muc_luong")
        c.text("Hình thức trả lương: Chuyển khoản, trước ngày 10 hằng tháng.")
    elif layout == "B":
        c = Canvas(Style("sans", 23))
        _quoc_hieu(c)
        c.text(f"Số: {rng.randint(1, 250):03d}/{doc.ngay_bat_dau.year}/HĐLĐ", 0.9)
        c.text("HỢP ĐỒNG LAO ĐỘNG", 1.3, bold=True, align="center")
        c.gap(10)
        c.kv("Chúng tôi, một bên là", doc.ten_cong_ty, "ten_cong_ty")
        c.kv("Và một bên là Ông/Bà", doc.ho_ten_nld, "ho_ten_nld")
        c.text("Thỏa thuận ký kết hợp đồng lao động và cam kết làm đúng những điều khoản sau đây:")
        c.text("Điều 1. Thời hạn và công việc hợp đồng", bold=True)
        c.kv("- Loại hợp đồng lao động", _loai_hd(doc), "loai_hd", indent=20)
        c.kv("- Thời gian bắt đầu", fmt_date(doc.ngay_bat_dau, "long"), "ngay_bat_dau", indent=20)
        c.kv("- Thời gian kết thúc", _end(doc, "long"), "ngay_ket_thuc", indent=20)
        c.kv("- Chức vụ", doc.chuc_danh, "chuc_danh", indent=20)
        c.text("Điều 2. Chế độ làm việc", bold=True)
        c.text("- Thời giờ làm việc: 8 giờ/ngày, 5 ngày/tuần.")
        c.text("Điều 3. Quyền lợi của người lao động", bold=True)
        c.kv("- Mức lương chính hoặc tiền công", fmt_money(doc.muc_luong, "d"), "muc_luong", indent=20)
    else:  # C: song ngữ, bảng kẻ viền (held-out)
        c = Canvas(Style("cond", 23))
        c.text(doc.ten_cong_ty, 1.0, bold=True)
        c.gap(10)
        c.text("HỢP ĐỒNG LAO ĐỘNG / LABOUR CONTRACT", 1.2, bold=True, align="center")
        c.gap(15)
        c.kv_table([
            ("Người lao động / Employee", doc.ho_ten_nld, "ho_ten_nld"),
            ("Người sử dụng lao động / Employer", doc.ten_cong_ty, "ten_cong_ty"),
            ("Vị trí / Position", doc.chuc_danh, "chuc_danh"),
            ("Loại HĐ / Contract type", _loai_hd(doc), "loai_hd"),
            ("Ngày hiệu lực / Effective date", fmt_date(doc.ngay_bat_dau, "dot"), "ngay_bat_dau"),
            ("Ngày hết hạn / Expiry date", _end(doc, "dot"), "ngay_ket_thuc"),
            ("Lương cơ bản / Basic salary", fmt_money(doc.muc_luong, "comma"), "muc_luong"),
        ], label_frac=0.45)
    c.gap(60)
    c.text("NGƯỜI LAO ĐỘNG                                   NGƯỜI SỬ DỤNG LAO ĐỘNG", bold=True,
           align="center")
    return c.finish(), c.raw


# --- Sao kê tài khoản ---------------------------------------------------------------------------

def render_sao_ke(doc: SaoKe, layout: str, bank: str, rng: random.Random) -> tuple[list[Image.Image], dict]:
    date_style = {"A": "slash", "B": "slash", "C": "dash"}[layout]
    c = Canvas(Style({"A": "sans", "B": "serif", "C": "cond"}[layout], 22))
    if layout == "B":
        c.text(bank, 0.95, bold=True)
    else:
        _letterhead(c, bank, rng)
    c.text("SAO KÊ TÀI KHOẢN" if layout != "C" else "SAO KÊ CHI TIẾT GIAO DỊCH / ACCOUNT STATEMENT",
           1.15, bold=True, align="center")
    c.gap(10)
    labels = {"A": ("Chủ tài khoản", "Số tài khoản"), "B": ("Tên tài khoản", "Số TK"),
              "C": ("Account name / Tên TK", "Account no. / Số TK")}[layout]
    c.kv(labels[0], doc.chu_tk, "chu_tk")
    c.kv(labels[1], fmt_account(doc.so_tk, layout == "C"), "so_tk")
    tu, den = fmt_date(doc.ky_tu, date_style), fmt_date(doc.ky_den, date_style)
    c.text(f"Từ ngày {tu} đến ngày {den}" if layout != "C" else f"Kỳ sao kê / Period: {tu} - {den}")
    c.record("ky_tu", tu)
    c.record("ky_den", den)
    c.gap(10)

    raw_rows, rows = [], []
    bal = rng.randrange(5, 60) * 1_000_000
    for g in doc.giao_dich:
        ngay = fmt_date(g.ngay, date_style)
        amt = f"{g.so_tien:,}" if layout != "C" else f"{g.so_tien:,}".replace(",", ".")
        if layout == "A":
            loai = "Ghi có" if g.loai == "ghi_co" else "Ghi nợ"
            rows.append([ngay, g.mo_ta, amt if g.loai == "ghi_co" else "", amt if g.loai == "ghi_no" else ""])
        elif layout == "B":
            loai = "+" if g.loai == "ghi_co" else "-"
            rows.append([ngay, f"{loai}{amt}", g.mo_ta])
        else:
            loai = "C" if g.loai == "ghi_co" else "D"
            bal += g.so_tien if g.loai == "ghi_co" else -g.so_tien
            rows.append([ngay, g.mo_ta, amt, loai, f"{bal:,}".replace(",", ".")])
        raw_rows.append({"ngay": ngay, "mo_ta": g.mo_ta, "so_tien": amt, "loai": loai})
    page = c.page_no
    if layout == "A":
        c.table(["Ngày", "Nội dung", "Ghi có", "Ghi nợ"], [0.14, 0.54, 0.16, 0.16], rows, "llrr")
    elif layout == "B":
        c.table(["Ngày GD", "Số tiền", "Diễn giải"], [0.17, 0.2, 0.63], rows, "lrl")
    else:
        c.table(["Ngày", "Mô tả / Description", "Phát sinh", "C/D", "Số dư"],
                [0.13, 0.47, 0.15, 0.07, 0.18], rows, "llrlr")
    c.raw["giao_dich"] = (json.dumps(raw_rows, ensure_ascii=False), page)
    pages = c.finish(lambda i, n: f"Trang {i}/{n}")
    return pages, c.raw


# --- Cả bộ ----------------------------------------------------------------------------------

@dataclass
class RenderedDoc:
    doc_type: DocType
    pages: list[Image.Image]
    raw: dict[str, tuple[str, int]]


def render_bundle(b: BundleTruth, layouts: dict[str, str], bank: str,
                  rng: random.Random) -> list[RenderedDoc]:
    out = []
    for dt, doc in b.docs.items():
        if dt is DocType.CCCD:
            pages, raw = render_cccd(doc, rng)
        elif dt is DocType.DON_VAY:
            pages, raw = render_don_vay(doc, layouts[dt.value], bank, rng)
        elif dt is DocType.HDLD:
            pages, raw = render_hdld(doc, layouts[dt.value], rng)
        else:
            pages, raw = render_sao_ke(doc, layouts[dt.value], bank, rng)
        out.append(RenderedDoc(dt, pages, raw))
    return out
