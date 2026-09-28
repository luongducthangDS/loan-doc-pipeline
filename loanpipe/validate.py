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
    """raw = JSON list các dòng {ngay, mo_ta, so_tien, loai} dạng chuỗi như trên ảnh.
    Sao kê tách hai cột: dòng {ngay, mo_ta, ghi_co, ghi_no}, code suy ra loai từ cột có số."""
    rows = json.loads(s)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError(f"dòng giao dịch không phải object: {r!r}")
        if "ghi_co" in r or "ghi_no" in r:
            cols = [(k, r.get(k)) for k in ("ghi_co", "ghi_no") if str(r.get(k) or "").strip()]
            if len(cols) != 1:
                raise ValueError(f"dòng cần đúng 1 cột có số tiền: {r}")
            r = {**r, "loai": cols[0][0], "so_tien": cols[0][1]}
        amt = str(r["so_tien"]).strip()
        if amt[:1] in "+-" and amt[:1]:
            # Dấu là ký tự chép nguyên văn từ ảnh, còn cột/loai là model tự diễn giải -> dấu quyết định.
            # Sao kê hai cột thật không in dấu, nên quy tắc này chỉ tác động lên kiểu "+1.000/-1.000".
            r = {**r, "loai": amt[0], "so_tien": amt[1:]}
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
