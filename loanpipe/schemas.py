"""Schema là nguồn duy nhất cho: ground truth, prompt trích xuất, validate và eval (spec mục 4, 6).

Hai lớp model:
- Model giấy tờ (Cccd, DonVay, Hdld, SaoKe): giá trị ĐÚNG đã chuẩn hóa. Dùng cho ground truth.
  Mỗi field khai báo `kind` -> quyết định hàm chuẩn hóa và cách so khớp khi chấm điểm.
- Data contract giữa các bước (Field, Extraction, CheckResult, Decision): đúng như spec mục 6.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import Field as PField


def _k(kind: str, **kw: Any) -> Any:
    return PField(json_schema_extra={"kind": kind}, **kw)


class DocType(str, Enum):
    CCCD = "cccd"
    DON_VAY = "don_vay"
    HDLD = "hdld"
    SAO_KE = "sao_ke"


# --- Model giấy tờ (ground truth) ---------------------------------------------

class Cccd(BaseModel):
    so_cccd: str = _k("cccd", pattern=r"^\d{12}$")
    ho_ten: str = _k("name")
    ngay_sinh: date = _k("date")
    gioi_tinh: Literal["Nam", "Nữ"] = _k("text")
    que_quan: str = _k("text")
    noi_thuong_tru: str = _k("text")
    ngay_cap: date = _k("date")  # mặt sau
    ngay_het_han: date = _k("date")


class DonVay(BaseModel):
    ho_ten: str = _k("name")
    so_cccd: str = _k("cccd", pattern=r"^\d{12}$")
    ngay_sinh: date = _k("date")
    so_dien_thoai: str = _k("digits")
    dia_chi: str = _k("text")
    ten_cong_ty: str = _k("text")
    thu_nhap_thang: int = _k("money", gt=0)
    so_tien_vay: int = _k("money", gt=0)
    thoi_han_thang: int = _k("int", gt=0)
    muc_dich: str = _k("text")
    so_tk_nhan_luong: str = _k("account")
    ngay_ky: date = _k("date")


class LoaiHd(str, Enum):
    XAC_DINH_THOI_HAN = "xac_dinh_thoi_han"
    KHONG_XAC_DINH_THOI_HAN = "khong_xac_dinh_thoi_han"


class Hdld(BaseModel):
    ho_ten_nld: str = _k("name")
    ten_cong_ty: str = _k("text")
    chuc_danh: str = _k("text")
    loai_hd: LoaiHd = _k("loai_hd")
    ngay_bat_dau: date = _k("date")
    ngay_ket_thuc: date | None = _k("opt_date")  # None = không xác định thời hạn
    muc_luong: int = _k("money", gt=0)


class GiaoDich(BaseModel):
    ngay: date
    mo_ta: str
    so_tien: int = PField(gt=0)
    loai: Literal["ghi_co", "ghi_no"]


class SaoKe(BaseModel):
    chu_tk: str = _k("name")
    so_tk: str = _k("account")
    ky_tu: date = _k("date")
    ky_den: date = _k("date")
    giao_dich: list[GiaoDich] = _k("transactions")


DOC_MODELS: dict[DocType, type[BaseModel]] = {
    DocType.CCCD: Cccd, DocType.DON_VAY: DonVay, DocType.HDLD: Hdld, DocType.SAO_KE: SaoKe,
}


def field_kinds(doc_type: DocType) -> dict[str, str]:
    model = DOC_MODELS[doc_type]
    return {name: (f.json_schema_extra or {})["kind"] for name, f in model.model_fields.items()}


# --- Nhãn dữ liệu synthetic (spec mục 5) ----------------------------------------

class ErrorCode(str, Enum):
    E1_NAME_MISMATCH = "E1"
    E2_ID_MISMATCH = "E2"
    E3_DOB_MISMATCH = "E3"
    E4_INCOME_INFLATED = "E4"
    E5_ID_EXPIRED = "E5"
    E6_ACCOUNT_MISMATCH = "E6"
    E7_CONTRACT_ENDED = "E7"
    E8_MISSING_DOC = "E8"


ERROR_RULE: dict[ErrorCode, str] = {
    ErrorCode.E1_NAME_MISMATCH: "R1", ErrorCode.E2_ID_MISMATCH: "R2",
    ErrorCode.E3_DOB_MISMATCH: "R3", ErrorCode.E4_INCOME_INFLATED: "R4",
    ErrorCode.E5_ID_EXPIRED: "R5", ErrorCode.E6_ACCOUNT_MISMATCH: "R6",
    ErrorCode.E7_CONTRACT_ENDED: "R7", ErrorCode.E8_MISSING_DOC: "R0",
}


class NearMiss(str, Enum):
    """Biến thể hợp lệ: rule KHÔNG được gắn cờ. Thiếu nhóm này thì không đo được precision."""

    N1_NAME_CASE_SPACE = "N1"     # tên trên đơn chỉ khác hoa/thường, khoảng trắng
    N2_NAME_NO_DIACRITICS = "N2"  # đơn viết tên không dấu
    N3_INCOME_NEAR = "N3"         # khai cao hơn lương TB 2–7% (dưới tolerance 10%)
    N4_EXTRA_CREDIT = "N4"        # sao kê có khoản ghi có lớn không phải lương (kể cả người họ Lương)
    N5_ID_EXPIRES_SOON = "N5"     # CCCD hết hạn trong 1–30 ngày sau ngày ký
    N6_SALARY_PAID_LATE = "N6"    # lương tháng cuối về sau kỳ sao kê -> chỉ 2 khoản lương


# --- Data contract giữa các bước (spec mục 6) ----------------------------------------

Route = Literal["AUTO_PASS", "REVIEW", "REQUEST_MORE"]
Status = Literal["pass", "fail", "unknown"]


class Field(BaseModel):
    value: Any = None  # str | int | date | list[GiaoDich] | None, sau chuẩn hóa
    raw: str | None = None  # chép nguyên văn từ ảnh
    confidence: Literal["high", "low"] = "low"
    page: int | None = None
    error: str | None = None  # lỗi validate/định dạng, nếu có


class Extraction(BaseModel):
    bundle_id: str
    doc_id: str
    doc_type: DocType
    fields: dict[str, Field]
    model: str
    prompt_version: str
    latency_ms: int = 0
    n_calls: int = 1


class CheckResult(BaseModel):
    rule_id: str
    status: Status
    evidence: list[dict] = []  # [{doc_type, field, value}, ...]
    message: str = ""


class Decision(BaseModel):
    bundle_id: str
    route: Route
    reasons: list[str]  # rule_id | "LOW_CONF:<doc>.<field>" | "UNKNOWN:<rule>" | "FORMAT:<doc>.<field>"
    rules_version: str
    thresholds_version: str
