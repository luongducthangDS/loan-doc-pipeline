"""Chuẩn hóa tất định: chuỗi đọc từ ảnh (raw) -> giá trị có kiểu (value).

Mọi hàm ở đây là thuần, có unit test, và KHÔNG gọi model.
Hàm nào không đọc được thì raise ValueError; tầng validate bắt lỗi đó thành `value=None`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

_UNITS = {"ty": 10**9, "trieu": 10**6, "nghin": 10**3, "ngan": 10**3, "k": 10**3}
_NO_END_DATE = {"khong xac dinh", "khong thoi han", "none", "null", "-"}


# --- Tên ---------------------------------------------------------------------

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def normalize_name(s: str) -> str:
    """NFC, viết hoa, gộp khoảng trắng. GIỮ dấu. 'Nguyễn  văn Đức' -> 'NGUYỄN VĂN ĐỨC'."""
    return " ".join(unicodedata.normalize("NFC", s).upper().split())


def has_diacritics(s: str) -> bool:
    return strip_accents(s) != s


def names_match(a: str, b: str) -> bool:
    """So khớp tên kiểu hybrid.

    - Khớp tuyệt đối sau chuẩn hóa (giữ dấu) -> khớp.
    - Một bên HOÀN TOÀN không dấu (sao kê, đơn viết không dấu) -> so sau khi bỏ dấu.
    - Cả hai bên đều có dấu mà khác nhau -> KHÔNG khớp (bắt E1 'sai 1 dấu').
    """
    a, b = normalize_name(a), normalize_name(b)
    if a == b:
        return True
    if not has_diacritics(a) or not has_diacritics(b):
        return strip_accents(a) == strip_accents(b)
    return False


# --- Số, tiền, ngày ------------------------------------------------------------

def digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


def parse_cccd(s: str) -> str:
    d = digits_only(s)
    if len(d) != 12:
        raise ValueError(f"số CCCD phải có 12 chữ số: {s!r}")
    return d


def parse_phone(s: str) -> str:
    d = digits_only(s)
    if not 9 <= len(d) <= 11:
        raise ValueError(f"số điện thoại không hợp lệ: {s!r}")
    return d


def parse_account(s: str) -> str:
    d = digits_only(s)
    if not 6 <= len(d) <= 19:
        raise ValueError(f"số tài khoản không hợp lệ: {s!r}")
    return d


def parse_money(s: str) -> int:
    """'15.000.000đ' | '15.000.000 VNĐ' | '15,000,000' | '15 triệu' | '15,5 triệu' -> int VND.

    Không xử lý dạng ghép '15 triệu 500 nghìn'; thêm khi dữ liệu có.
    """
    t = strip_accents(str(s)).lower()
    m = re.match(r"\s*([\d.,]+)\s*(ty|trieu|nghin|ngan|k)?", t)
    if not m:
        raise ValueError(f"không đọc được số tiền: {s!r}")
    num, unit = m.groups()
    if unit is None or re.fullmatch(r"\d{1,3}([.,]\d{3})+", num):
        value = int(re.sub(r"[.,]", "", num))  # dấu . , là phân tách hàng nghìn
    else:
        value = float(num.replace(",", "."))  # '15,5 triệu'
    return round(value * _UNITS.get(unit, 1))


def parse_int(s: str) -> int:
    d = digits_only(str(s))
    if not d:
        raise ValueError(f"không đọc được số: {s!r}")
    return int(d)


def parse_date(s: str) -> date:
    """'26/09/2026' | '26-09-2026' | '2026-09-26' | 'ngày 26 tháng 9 năm 2026' -> date."""
    nums = re.findall(r"\d+", str(s))
    if len(nums) != 3:
        raise ValueError(f"không đọc được ngày: {s!r}")
    a, b, c = map(int, nums)
    return date(a, b, c) if len(nums[0]) == 4 else date(c, b, a)


def parse_optional_date(s: str) -> date | None:
    """Như parse_date, nhưng 'Không xác định' -> None hợp lệ (HĐLĐ không thời hạn)."""
    if strip_accents(str(s)).strip().lower() in _NO_END_DATE:
        return None
    return parse_date(s)


def clean_text(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(s)).split())
