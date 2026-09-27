from datetime import date

import pytest

from loanpipe.config import load_rules, load_thresholds
from loanpipe.rules import BundleView
from loanpipe.schemas import DocType, Field, GiaoDich, LoaiHd

D = DocType


def F(value, conf="high", error=None):
    return Field(value=value, raw=str(value), confidence=conf, error=error)


def clean_docs() -> dict:
    """Một bộ hồ sơ sạch tối thiểu, giá trị đã chuẩn hóa."""
    txs = [GiaoDich(ngay=date(2026, m, 7), mo_ta=f"CT LUONG T{m - 1:02d}/2026 CONG TY A", so_tien=20_000_000,
                    loai="ghi_co") for m in (2, 3, 4)]
    txs.append(GiaoDich(ngay=date(2026, 3, 1), mo_ta="RUT TIEN ATM", so_tien=500_000, loai="ghi_no"))
    return {
        D.CCCD: {"ho_ten": F("NGUYỄN VĂN AN"), "so_cccd": F("001090123456"), "ngay_sinh": F(date(1990, 5, 1)),
                 "ngay_het_han": F(date(2030, 5, 1))},
        D.DON_VAY: {"ho_ten": F("NGUYỄN VĂN AN"), "so_cccd": F("001090123456"), "ngay_sinh": F(date(1990, 5, 1)),
                    "thu_nhap_thang": F(20_000_000), "so_tk_nhan_luong": F("123456789"),
                    "ngay_ky": F(date(2026, 4, 20))},
        D.HDLD: {"ho_ten_nld": F("NGUYỄN VĂN AN"), "loai_hd": F(LoaiHd.XAC_DINH_THOI_HAN),
                 "ngay_ket_thuc": F(date(2027, 1, 1))},
        D.SAO_KE: {"chu_tk": F("NGUYEN VAN AN"), "so_tk": F("123456789"), "ky_tu": F(date(2026, 1, 15)),
                   "ky_den": F(date(2026, 4, 14)), "giao_dich": F(txs)},
    }


@pytest.fixture
def docs():
    return clean_docs()


@pytest.fixture
def view(docs):
    return BundleView(docs)


@pytest.fixture
def cfg():
    return load_rules()


@pytest.fixture
def thr():
    return load_thresholds()
