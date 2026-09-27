"""Schema dữ liệu dùng chung cho ground truth, output extractor và rule engine.

Quy ước (đã chốt tuần 1):
- Ngày: `date` (ISO). Tiền: `int` VND, không float.
- Tên: giữ nguyên bản gốc; so khớp qua `normalize.name_key`.
- Confidence/evidence KHÔNG nằm trong model tài liệu -> ground truth và
  prediction cùng một kiểu, chấm điểm so trực tiếp từng field.
  Wrapper `Extraction(doc_type, data, confidence, evidence)` thêm ở tuần 2.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class DocType(str, Enum):
    CCCD = "cccd"
    HDLD = "hdld"
    SAO_KE = "sao_ke"
    DE_NGHI_VAY = "de_nghi_vay"


class CCCD(BaseModel):
    so_cccd: str = Field(pattern=r"^\d{12}$")
    ho_ten: str
    ngay_sinh: date
    gioi_tinh: str  # "Nam" | "Nữ"
    noi_thuong_tru: str
    ngay_het_han: date


class LoaiHDLD(str, Enum):
    XAC_DINH_THOI_HAN = "xac_dinh_thoi_han"
    KHONG_XAC_DINH_THOI_HAN = "khong_xac_dinh_thoi_han"


class HopDongLaoDong(BaseModel):
    ten_don_vi: str
    ten_nguoi_lao_dong: str
    so_cccd: str = Field(pattern=r"^\d{12}$")
    chuc_danh: str
    loai_hop_dong: LoaiHDLD
    ngay_bat_dau: date
    ngay_ket_thuc: date | None  # None khi không xác định thời hạn
    muc_luong: int = Field(gt=0)  # lương gross / tháng


class GiaoDich(BaseModel):
    ngay: date
    mo_ta: str
    so_tien: int  # dương = ghi có, âm = ghi nợ


class SaoKe(BaseModel):
    ngan_hang: str
    chu_tai_khoan: str
    so_tai_khoan: str
    tu_ngay: date
    den_ngay: date
    giao_dich: list[GiaoDich]


class DeNghiVay(BaseModel):
    ho_ten: str
    so_cccd: str = Field(pattern=r"^\d{12}$")
    ngay_nop: date
    so_tien_vay: int = Field(gt=0)
    thoi_han_thang: int = Field(gt=0)
    muc_dich: str
    thu_nhap_khai_bao: int = Field(gt=0)  # thu nhập thực nhận / tháng
    no_hien_tai_hang_thang: int = Field(ge=0)


# --- Nhãn cho bộ dữ liệu tổng hợp ------------------------------------------

class CaseType(str, Enum):
    CLEAN = "clean"
    ERROR = "error"      # hệ thống PHẢI gắn cờ
    BENIGN = "benign"    # biến thể vô hại, hệ thống KHÔNG được gắn cờ


class ErrorCode(str, Enum):
    NAME_MISMATCH = "name_mismatch"          # tên trên HĐLĐ là người khác
    ID_MISMATCH = "id_mismatch"              # số CCCD trên đơn khác CCCD
    INCOME_INFLATED = "income_inflated"      # khai thu nhập > lương sao kê quá 15%
    CONTRACT_EXPIRED = "contract_expired"    # HĐLĐ hết hạn trước ngày nộp
    CCCD_EXPIRED = "cccd_expired"
    MISSING_DOC = "missing_doc"              # thiếu 1 trong CCCD / HĐLĐ / sao kê


class BenignCode(str, Enum):
    NAME_NO_DIACRITICS = "name_no_diacritics"      # đơn ghi "Nguyen Van Nam"
    NEAR_THRESHOLD_INCOME = "near_threshold_income"  # khai cao hơn 8–12%, dưới ngưỡng
    CCCD_EXPIRES_SOON = "cccd_expires_soon"        # còn hạn < 30 ngày
    SALARY_PAID_LATE = "salary_paid_late"          # lương tháng cuối về sau kỳ sao kê


class Application(BaseModel):
    """Một bộ hồ sơ vay + nhãn. Đơn đề nghị vay luôn có; 3 giấy tờ còn lại có thể thiếu."""

    app_id: str
    de_nghi_vay: DeNghiVay
    cccd: CCCD | None
    hdld: HopDongLaoDong | None
    sao_ke: SaoKe | None
    case: CaseType
    errors: list[ErrorCode] = []
    benign: list[BenignCode] = []
