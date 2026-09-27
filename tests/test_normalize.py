from datetime import date

import pytest

from loanpipe.normalize import (
    names_match, normalize_name, parse_account, parse_cccd, parse_date, parse_money, parse_optional_date,
)
from loanpipe.validate import finalize_field, parse_loai_hd, parse_transactions
from loanpipe.schemas import LoaiHd


@pytest.mark.parametrize("s,v", [
    ("15.000.000đ", 15_000_000), ("15.000.000 VNĐ", 15_000_000), ("15,000,000 VND", 15_000_000),
    ("15.000.000 đồng", 15_000_000), ("15 triệu", 15_000_000), ("15,5 triệu đồng", 15_500_000),
    ("1.500 triệu", 1_500_000_000), ("2 tỷ", 2_000_000_000), ("850", 850),
])
def test_parse_money(s, v):
    assert parse_money(s) == v


@pytest.mark.parametrize("s", ["26/09/2026", "26-09-2026", "26.09.2026", "2026-09-26", "ngày 26 tháng 09 năm 2026"])
def test_parse_date(s):
    assert parse_date(s) == date(2026, 9, 26)


def test_parse_errors():
    for fn, s in [(parse_date, "không rõ"), (parse_date, "31/02/2026"), (parse_cccd, "00109012345"),
                  (parse_money, "abc"), (parse_account, "12")]:
        with pytest.raises(ValueError):
            fn(s)
    assert parse_optional_date("Không xác định") is None
    assert parse_cccd("0010 9012 3456") == "001090123456"


def test_normalize_name_keeps_diacritics():
    assert normalize_name("Nguyễn  văn Đức") == "NGUYỄN VĂN ĐỨC"


@pytest.mark.parametrize("a,b,ok", [
    ("Nguyễn Văn An", "NGUYỄN  VĂN AN", True),     # hoa/thường, khoảng trắng (N1)
    ("Nguyen Van An", "Nguyễn Văn An", True),      # một bên hoàn toàn không dấu (N2, sao kê)
    ("NGUYEN VAN AN", "NGUYEN VAN AN", True),
    ("Nguyễn Văn Án", "Nguyễn Văn An", False),     # sai 1 dấu, cả hai có dấu (E1)
    ("Nguyễn Văn Ăn", "NGUYEN VAN AN", True),      # vs sao kê không dấu: không phân biệt được (giới hạn)
    ("Nguyễn An", "Nguyễn Văn An", False),         # bỏ chữ đệm (E1)
    ("Nguyễn An Văn", "Nguyễn Văn An", False),     # đảo thứ tự (E1)
    ("Nguyen An", "Nguyễn Văn An", False),
])
def test_names_match(a, b, ok):
    assert names_match(a, b) is ok


def test_loai_hd_and_transactions():
    assert parse_loai_hd("Không xác định thời hạn") is LoaiHd.KHONG_XAC_DINH_THOI_HAN
    assert parse_loai_hd("Xác định thời hạn 12 tháng") is LoaiHd.XAC_DINH_THOI_HAN
    rows = '[{"ngay": "07/03/2026", "mo_ta": "CT  LUONG", "so_tien": "1,000", "loai": "Ghi có"},' \
           ' {"ngay": "08-03-2026", "mo_ta": "ATM", "so_tien": "2.000", "loai": "D"}]'
    txs = parse_transactions(rows)
    assert [(t.so_tien, t.loai, t.mo_ta) for t in txs] == [(1000, "ghi_co", "CT LUONG"), (2000, "ghi_no", "ATM")]


def test_confidence_signals():
    assert finalize_field("date", "01/02/2026").confidence == "high"
    assert finalize_field("date", None).confidence == "low"                      # không trả lời
    f = finalize_field("cccd", "12345")                                           # sai định dạng
    assert (f.value, f.confidence, bool(f.error)) == (None, "low", True)
    assert finalize_field("money", "1.000đ", second_raw="1000", check_consistency=True).confidence == "high"
    assert finalize_field("money", "1.000đ", second_raw="7.000", check_consistency=True).confidence == "low"
    assert finalize_field("money", "1.000đ", second_raw=None, check_consistency=True).confidence == "low"
    end = finalize_field("opt_date", "Không xác định")
    assert (end.value, end.confidence) == (None, "high")                          # null có chủ đích
