"""Bước 4: raw -> value (chuẩn hóa) + confidence nhị phân từ tín hiệu kiểm chứng được (spec mục 8).

Không dùng confidence model tự khai. Field đạt `high` khi qua cả 3 tín hiệu:
  1. định dạng hợp lệ (chuẩn hóa không lỗi),
  2. trả lời rõ ràng (raw không null/rỗng),
  3. tự nhất quán (nếu có lần trích thứ 2: hai kết quả chuẩn hóa bằng nhau).
KHÔNG dùng việc khớp giữa các giấy tờ làm tín hiệu: rule đã kiểm tra điều đó, dùng lại là vòng tròn.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from loanpipe import normalize as n
from loanpipe.schemas import Field, GiaoDich, LoaiHd


def parse_loai_hd(s: str) -> LoaiHd:
    t = n.strip_accents(str(s)).lower()
    if "khong xac dinh" in t:
        return LoaiHd.KHONG_XAC_DINH_THOI_HAN
    if "xac dinh" in t:
        return LoaiHd.XAC_DINH_THOI_HAN
    raise ValueError(f"không nhận ra loại HĐLĐ: {s!r}")


def parse_transactions(s: str) -> list[GiaoDich]:
    """raw = JSON list các dòng {ngay, mo_ta, so_tien, loai} dạng chuỗi như trên ảnh."""
    rows = json.loads(s)
    out = []
    for r in rows:
        loai = n.strip_accents(str(r["loai"])).lower().replace(" ", "_")
        loai = "ghi_co" if loai in ("ghi_co", "co", "c", "cr", "credit", "+") else "ghi_no" if loai in (
            "ghi_no", "no", "d", "dr", "debit", "-") else loai
        out.append(GiaoDich(ngay=n.parse_date(r["ngay"]), mo_ta=n.clean_text(r["mo_ta"]),
                            so_tien=n.parse_money(r["so_tien"]), loai=loai))
    return out


NORMALIZERS: dict[str, Callable[[str], Any]] = {
    "name": n.normalize_name,
    "cccd": n.parse_cccd,
    "account": n.parse_account,
    "digits": n.parse_phone,
    "date": n.parse_date,
    "opt_date": n.parse_optional_date,
    "money": n.parse_money,
    "int": n.parse_int,
    "text": n.clean_text,
    "loai_hd": parse_loai_hd,
    "transactions": parse_transactions,
}


def finalize_field(kind: str, raw: str | None, page: int | None = None,
                   second_raw: str | None = None, check_consistency: bool = False) -> Field:
    if raw is None or not str(raw).strip():
        return Field(value=None, raw=raw, confidence="low", page=page)  # model không thấy field
    try:
        value = NORMALIZERS[kind](raw)
    except (ValueError, KeyError, TypeError) as e:  # json lỗi cũng là ValueError
        return Field(value=None, raw=raw, confidence="low", page=page, error=str(e))
    consistent = True
    if check_consistency:
        try:
            consistent = second_raw is not None and NORMALIZERS[kind](second_raw) == value
        except (ValueError, KeyError, TypeError):
            consistent = False
    return Field(value=value, raw=raw, confidence="high" if consistent else "low", page=page)
