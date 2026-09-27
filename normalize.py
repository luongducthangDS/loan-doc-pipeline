"""Chuẩn hóa giá trị đọc từ tài liệu về kiểu trong schema."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

_UNITS = {"ty": 10**9, "trieu": 10**6, "nghin": 10**3, "ngan": 10**3, "k": 10**3}


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def name_key(s: str) -> str:
    """Khóa so khớp tên: bỏ dấu, viết hoa, gộp khoảng trắng. 'Nguyễn  văn Đức' -> 'NGUYEN VAN DUC'."""
    return " ".join(strip_accents(s).upper().split())


def parse_money(s: str) -> int:
    """'15.000.000đ' | '15.000.000 VNĐ' | '15 triệu' | '15,5 triệu' | '1.500 triệu' -> int VND.

    ponytail: không xử lý dạng ghép '15 triệu 500 nghìn'; thêm khi dữ liệu thật có.
    """
    t = strip_accents(s).lower()
    m = re.match(r"\s*([\d.,]+)\s*(ty|trieu|nghin|ngan|k)?", t)
    if not m:
        raise ValueError(f"không đọc được số tiền: {s!r}")
    num, unit = m.groups()
    if unit is None or re.fullmatch(r"\d{1,3}([.,]\d{3})+", num):
        value = int(re.sub(r"[.,]", "", num))  # dấu . , là phân tách hàng nghìn
    else:
        value = float(num.replace(",", "."))  # '15,5 triệu'
    return round(value * _UNITS.get(unit, 1))


def parse_date(s: str) -> date:
    """'26/09/2026' | '26-09-2026' | '2026-09-26' | 'ngày 26 tháng 9 năm 2026' -> date."""
    nums = re.findall(r"\d+", s)
    if len(nums) != 3:
        raise ValueError(f"không đọc được ngày: {s!r}")
    a, b, c = map(int, nums)
    return date(a, b, c) if len(nums[0]) == 4 else date(c, b, a)
