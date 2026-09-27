"""Sinh ground truth cho bộ hồ sơ vay tổng hợp (chưa render ảnh).

Sinh truth TRƯỚC, render SAU -> nhãn đúng 100%, không có PII thật.
Mọi tên công ty / ngân hàng đều hư cấu.
"""

from __future__ import annotations

import calendar
import random
from datetime import date, timedelta

from normalize import name_key
from schemas import (
    CCCD,
    Application,
    BenignCode,
    CaseType,
    DeNghiVay,
    ErrorCode,
    GiaoDich,
    HopDongLaoDong,
    LoaiHDLD,
    SaoKe,
)

INCOME_THRESHOLD = 1.15  # khai báo / lương thực nhận TB; > ngưỡng = INCOME_INFLATED
EMPLOYEE_INSURANCE = 0.105  # BHXH 8% + BHYT 1.5% + BHTN 1% (ponytail: bỏ qua thuế TNCN)

_HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Ngô", "Dương", "Lý"]
_DEM = {"Nam": ["Văn", "Đức", "Minh", "Quang", "Hữu", "Thành", "Tiến"],
        "Nữ": ["Thị", "Thu", "Ngọc", "Thanh", "Minh", "Phương"]}
_TEN = {"Nam": ["Nam", "Hùng", "Dũng", "Tuấn", "Long", "Thắng", "Phong", "Khánh", "Đạt", "Sơn"],
        "Nữ": ["Lan", "Hương", "Linh", "Trang", "Mai", "Hà", "Thảo", "Yến", "Ngân", "Vy"]}
# (mã tỉnh CCCD, địa chỉ mẫu)
_TINH = [("001", "Phường Dịch Vọng, Quận Cầu Giấy, Hà Nội"),
         ("001", "Phường Bạch Mai, Quận Hai Bà Trưng, Hà Nội"),
         ("079", "Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh"),
         ("079", "Phường 12, Quận Tân Bình, TP. Hồ Chí Minh"),
         ("031", "Phường Máy Tơ, Quận Ngô Quyền, Hải Phòng"),
         ("048", "Phường Hòa Cường Bắc, Quận Hải Châu, Đà Nẵng")]
_CONG_TY = ["CÔNG TY TNHH AN PHÁT", "CÔNG TY CỔ PHẦN MINH LONG", "CÔNG TY TNHH THÀNH ĐẠT",
            "CÔNG TY CỔ PHẦN SAO MAI", "CÔNG TY TNHH PHÚ THỊNH", "CÔNG TY CỔ PHẦN VẠN XUÂN"]
_CHUC_DANH = ["Nhân viên kinh doanh", "Kế toán viên", "Kỹ sư phần mềm", "Nhân viên hành chính",
              "Chuyên viên marketing", "Kỹ thuật viên", "Trưởng nhóm bán hàng"]
_NGAN_HANG = ["NGÂN HÀNG TMCP SAO VIỆT (GIẢ LẬP)", "NGÂN HÀNG TMCP HỒNG LẠC (GIẢ LẬP)"]
_MUC_DICH = ["Mua sắm đồ dùng gia đình", "Sửa chữa nhà ở", "Mua xe máy", "Chi phí học tập",
             "Chi phí y tế", "Tiêu dùng cá nhân"]
_CHI_TIEU = ["THANH TOAN QR CUA HANG TIEN LOI", "RUT TIEN ATM", "THANH TOAN HOA DON DIEN",
             "THANH TOAN HOA DON INTERNET", "THANH TOAN QR SIEU THI", "CHUYEN KHOAN TIEN NHA"]


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _round_to(x: float, step: int) -> int:
    return int(round(x / step)) * step


def _floor_to(x: float, step: int) -> int:
    return int(x // step) * step


def _ho_ten(rng: random.Random, gioi_tinh: str) -> str:
    return f"{rng.choice(_HO)} {rng.choice(_DEM[gioi_tinh])} {rng.choice(_TEN[gioi_tinh])}"


def _so_cccd(rng: random.Random, ma_tinh: str, gioi_tinh: str, ngay_sinh: date) -> str:
    # 3 số mã tỉnh + 1 số giới tính/thế kỷ + 2 số năm sinh + 6 số ngẫu nhiên
    the_ky = 0 if ngay_sinh.year < 2000 else 2
    gt = the_ky + (0 if gioi_tinh == "Nam" else 1)
    return f"{ma_tinh}{gt}{ngay_sinh.year % 100:02d}{rng.randrange(10**6):06d}"


def _cccd_het_han(ngay_sinh: date, ngay_nop: date) -> date:
    """CCCD hết hạn khi chủ thẻ đủ 25, 40, 60 tuổi -> mốc gần nhất sau ngày nộp."""
    for tuoi in (25, 40, 60):
        moc = add_months(ngay_sinh, 12 * tuoi)
        if moc > ngay_nop:
            return moc
    raise ValueError("chỉ sinh người 22–55 tuổi")


def _sao_ke(rng, ho_ten, cong_ty, luong_net, ngay_nop, paid_late: bool) -> SaoKe:
    thang_dau = add_months(ngay_nop.replace(day=1), -3)
    den_ngay = ngay_nop.replace(day=1) - timedelta(days=1)
    ten_cty = name_key(cong_ty)
    gd: list[GiaoDich] = []
    for i in range(3):
        thang = add_months(thang_dau, i)
        ky_luong = add_months(thang, -1)
        if not (paid_late and i == 2):  # lương tháng cuối về sau den_ngay
            gd.append(GiaoDich(
                ngay=thang.replace(day=rng.randint(5, 10)),
                mo_ta=f"CT LUONG T{ky_luong.month:02d}/{ky_luong.year} {ten_cty}",
                so_tien=_round_to(luong_net * rng.uniform(0.97, 1.03), 1000)))
        so_ngay = calendar.monthrange(thang.year, thang.month)[1]
        for _ in range(rng.randint(5, 10)):
            gd.append(GiaoDich(
                ngay=thang.replace(day=rng.randint(1, so_ngay)),
                mo_ta=rng.choice(_CHI_TIEU),
                so_tien=-_round_to(rng.uniform(50_000, 0.15 * luong_net), 1000)))
        if rng.random() < 0.5:
            gd.append(GiaoDich(
                ngay=thang.replace(day=rng.randint(1, so_ngay)),
                mo_ta=f"NHAN CK TU {name_key(_ho_ten(rng, rng.choice(['Nam', 'Nữ'])))}",
                so_tien=_round_to(rng.uniform(200_000, 3_000_000), 1000)))
    gd.sort(key=lambda g: g.ngay)
    return SaoKe(ngan_hang=rng.choice(_NGAN_HANG), chu_tai_khoan=name_key(ho_ten),
                 so_tai_khoan=str(rng.randrange(10**9, 10**13)),
                 tu_ngay=thang_dau, den_ngay=den_ngay, giao_dich=gd)


def generate_one(rng: random.Random, app_id: str,
                 err: ErrorCode | None = None, ben: BenignCode | None = None) -> Application:
    # ponytail: mỗi hồ sơ tối đa 1 mã -> dễ quy nguyên nhân khi phân tích lỗi
    case = CaseType.ERROR if err else CaseType.BENIGN if ben else CaseType.CLEAN

    ngay_nop = date(2026, 1, 1) + timedelta(days=rng.randint(0, 257))
    gioi_tinh = rng.choice(["Nam", "Nữ"])
    ho_ten = _ho_ten(rng, gioi_tinh)
    ngay_sinh = add_months(ngay_nop, -12 * rng.randint(22, 55)) - timedelta(days=rng.randint(0, 364))
    ma_tinh, dia_chi = rng.choice(_TINH)
    so_cccd = _so_cccd(rng, ma_tinh, gioi_tinh, ngay_sinh)

    het_han = _cccd_het_han(ngay_sinh, ngay_nop)
    if err is ErrorCode.CCCD_EXPIRED:
        het_han = ngay_nop - timedelta(days=rng.randint(10, 400))
    elif ben is BenignCode.CCCD_EXPIRES_SOON:
        het_han = ngay_nop + timedelta(days=rng.randint(1, 30))
    cccd = CCCD(so_cccd=so_cccd, ho_ten=ho_ten, ngay_sinh=ngay_sinh, gioi_tinh=gioi_tinh,
                noi_thuong_tru=dia_chi, ngay_het_han=het_han)

    cong_ty = rng.choice(_CONG_TY)
    muc_luong = _round_to(rng.uniform(8e6, 45e6), 500_000)
    if rng.random() < 0.4 and err is not ErrorCode.CONTRACT_EXPIRED:
        loai, so_thang = LoaiHDLD.KHONG_XAC_DINH_THOI_HAN, 0
        bat_dau, ket_thuc = ngay_nop - timedelta(days=rng.randint(180, 2500)), None
    else:
        loai, so_thang = LoaiHDLD.XAC_DINH_THOI_HAN, rng.choice([12, 24, 36])
        if err is ErrorCode.CONTRACT_EXPIRED:
            ket_thuc = ngay_nop - timedelta(days=rng.randint(5, 200))
        else:  # còn hạn >= 30 ngày, đã bắt đầu >= 4 tháng trước (đủ 3 kỳ lương)
            ket_thuc = ngay_nop + timedelta(days=rng.randint(30, so_thang * 30 - 130))
        bat_dau = add_months(ket_thuc, -so_thang)
    ten_hdld = _ho_ten(rng, gioi_tinh) if err is ErrorCode.NAME_MISMATCH else ho_ten
    while err is ErrorCode.NAME_MISMATCH and ten_hdld == ho_ten:
        ten_hdld = _ho_ten(rng, gioi_tinh)
    hdld = HopDongLaoDong(ten_don_vi=cong_ty, ten_nguoi_lao_dong=ten_hdld, so_cccd=so_cccd,
                          chuc_danh=rng.choice(_CHUC_DANH), loai_hop_dong=loai,
                          ngay_bat_dau=bat_dau, ngay_ket_thuc=ket_thuc, muc_luong=muc_luong)

    luong_net = muc_luong * (1 - EMPLOYEE_INSURANCE)
    sao_ke = _sao_ke(rng, ho_ten, cong_ty, luong_net, ngay_nop,
                     paid_late=ben is BenignCode.SALARY_PAID_LATE)
    luong_tb = salary_avg(sao_ke)

    if err is ErrorCode.INCOME_INFLATED:
        khai = _floor_to(luong_tb * rng.uniform(1.3, 2.0), 500_000)
    elif ben is BenignCode.NEAR_THRESHOLD_INCOME:
        khai = _floor_to(luong_tb * rng.uniform(1.08, 1.12), 500_000)
    else:
        khai = _floor_to(luong_tb * rng.uniform(0.9, 1.05), 500_000)

    so_cccd_don = so_cccd
    if err is ErrorCode.ID_MISMATCH:
        so_cccd_don = so_cccd[:6] + f"{(int(so_cccd[6:]) + rng.randint(1, 999_999)) % 10**6:06d}"
    ten_don = name_key(ho_ten).title() if ben is BenignCode.NAME_NO_DIACRITICS else ho_ten
    don = DeNghiVay(ho_ten=ten_don, so_cccd=so_cccd_don, ngay_nop=ngay_nop,
                    so_tien_vay=rng.randrange(20, 501, 5) * 1_000_000,
                    thoi_han_thang=rng.choice([12, 24, 36, 48, 60]),
                    muc_dich=rng.choice(_MUC_DICH), thu_nhap_khai_bao=khai,
                    no_hien_tai_hang_thang=0 if rng.random() < 0.5
                    else _round_to(rng.uniform(1e6, 8e6), 100_000))

    docs = {"cccd": cccd, "hdld": hdld, "sao_ke": sao_ke}
    if err is ErrorCode.MISSING_DOC:
        docs[rng.choice(list(docs))] = None
    return Application(app_id=app_id, de_nghi_vay=don, **docs, case=case,
                       errors=[err] if err else [], benign=[ben] if ben else [])


def salary_avg(sao_ke: SaoKe) -> float:
    """Lương thực nhận TB = trung bình các khoản 'CT LUONG' CÓ trong kỳ (không chia cứng cho 3)."""
    luong = [g.so_tien for g in sao_ke.giao_dich if g.mo_ta.startswith("CT LUONG")]
    return sum(luong) / len(luong)


def generate(n: int, seed: int = 42, clean_share: float = 0.6) -> list[Application]:
    """Phân tầng: mỗi mã lỗi/biến thể có SỐ LƯỢNG BẰNG NHAU (không bốc ngẫu nhiên),
    để recall theo từng mã không bị dựa trên 2–3 mẫu."""
    rng = random.Random(seed)
    codes: list = [*ErrorCode, *BenignCode]
    per_code = round(n * (1 - clean_share) / len(codes))
    plan = [c for c in codes for _ in range(per_code)]
    plan += [None] * (n - len(plan))
    rng.shuffle(plan)
    return [generate_one(rng, f"APP{seed:03d}-{i:04d}",
                         err=c if isinstance(c, ErrorCode) else None,
                         ben=c if isinstance(c, BenignCode) else None)
            for i, c in enumerate(plan)]
