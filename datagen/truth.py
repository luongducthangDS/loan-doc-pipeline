"""Profile -> bộ hồ sơ ground truth (chưa render ảnh). Spec mục 5.

Mỗi bộ sinh từ MỘT profile duy nhất -> các giấy tờ nhất quán với nhau, ground truth có sẵn.
Lỗi được cài có chủ đích lên một giấy tờ và ghi vào nhãn.

Nhãn KHÔNG được tính bằng code của rule (vd lương TB lấy từ chính các khoản lương đã sinh,
không gọi `rules.salary_avg`) -> nếu rule sai, eval sẽ bắt được thay vì nhãn "sai theo".
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from datagen import profiles as P
from loanpipe.normalize import strip_accents
from loanpipe.rules import add_months
from loanpipe.schemas import (
    Cccd, DocType, DonVay, ErrorCode, GiaoDich, Hdld, LoaiHd, NearMiss, SaoKe,
)

E, N = ErrorCode, NearMiss
DOC_IDS = {DocType.CCCD: "d1", DocType.DON_VAY: "d2", DocType.HDLD: "d3", DocType.SAO_KE: "d4"}
EMPLOYEE_INSURANCE = 0.105  # BHXH 8% + BHYT 1.5% + BHTN 1%; bỏ qua thuế TNCN
INCOME_INFLATE = (1.25, 1.8)  # E4: khai > lương TB x 1,2 (spec) -> chọn >= 1,25 để có biên
INCOME_NEAR = (1.02, 1.07)    # N3: lệch 2–7%, dưới tolerance 10%

# Trường bị tác động bởi từng nhãn -> ghi vào manifest
_ERR_TARGET = {
    E.E1_NAME_MISMATCH: (DocType.DON_VAY, "ho_ten"), E.E2_ID_MISMATCH: (DocType.DON_VAY, "so_cccd"),
    E.E3_DOB_MISMATCH: (DocType.DON_VAY, "ngay_sinh"),
    E.E4_INCOME_INFLATED: (DocType.DON_VAY, "thu_nhap_thang"),
    E.E5_ID_EXPIRED: (DocType.CCCD, "ngay_het_han"),
    E.E6_ACCOUNT_MISMATCH: (DocType.DON_VAY, "so_tk_nhan_luong"),
    E.E7_CONTRACT_ENDED: (DocType.HDLD, "ngay_ket_thuc"),
}
_NM_TARGET = {
    N.N1_NAME_CASE_SPACE: (DocType.DON_VAY, "ho_ten"), N.N2_NAME_NO_DIACRITICS: (DocType.DON_VAY, "ho_ten"),
    N.N3_INCOME_NEAR: (DocType.DON_VAY, "thu_nhap_thang"), N.N4_EXTRA_CREDIT: (DocType.SAO_KE, "giao_dich"),
    N.N5_ID_EXPIRES_SOON: (DocType.CCCD, "ngay_het_han"), N.N6_SALARY_PAID_LATE: (DocType.SAO_KE, "giao_dich"),
}

# Họ nguyên âm tiếng Việt theo cùng chữ cái gốc (để "sai 1 dấu" mà vẫn còn dấu)
_VOWEL_FAMILIES = ["aàáảãạăằắẳẵặâầấẩẫậ", "eèéẻẽẹêềếểễệ", "iìíỉĩị", "oòóỏõọôồốổỗộơờớởỡợ",
                   "uùúủũụưừứửữự", "yỳýỷỹỵ"]


@dataclass
class BundleTruth:
    bundle_id: str
    docs: dict[DocType, object]  # DocType -> Cccd | DonVay | Hdld | SaoKe; giấy tờ thiếu thì không có
    errors: list[ErrorCode] = field(default_factory=list)
    near_miss: list[NearMiss] = field(default_factory=list)
    missing: list[DocType] = field(default_factory=list)

    @property
    def expected_route(self) -> str:
        if E.E8_MISSING_DOC in self.errors:
            return "REQUEST_MORE"
        return "REVIEW" if self.errors else "AUTO_PASS"

    def labels(self) -> tuple[list[dict], list[dict]]:
        errs = []
        for c in self.errors:
            if c is E.E8_MISSING_DOC:
                errs += [{"code": c.value, "doc_id": DOC_IDS[d], "field": None} for d in self.missing]
            else:
                d, f = _ERR_TARGET[c]
                errs.append({"code": c.value, "doc_id": DOC_IDS[d], "field": f})
        nms = [{"code": c.value, "doc_id": DOC_IDS[_NM_TARGET[c][0]], "field": _NM_TARGET[c][1]}
               for c in self.near_miss]
        return errs, nms


# --- Tiện ích -----------------------------------------------------------------

def _rand_date(rng: random.Random, lo: date, hi: date) -> date:
    return lo + timedelta(days=rng.randint(0, max(0, (hi - lo).days)))


def _floor_to(x: float, step: int) -> int:
    return int(x // step) * step


def _unaccent_upper(s: str) -> str:
    return strip_accents(s).upper()


def _ho_ten(rng: random.Random, gt: str) -> str:
    dem = [rng.choice(P.DEM[gt])]
    if rng.random() < 0.3:  # tên 4 chữ, để E1 "bỏ chữ đệm" có nhiều dạng
        dem.append(rng.choice([d for d in P.DEM[gt] if d != dem[0]]))
    return " ".join([rng.choice(P.HO), *dem, rng.choice(P.TEN[gt])])


def _so_cccd(rng: random.Random, ma_tinh: str, gt: str, ngay_sinh: date) -> str:
    # 3 số mã tỉnh + 1 số giới tính/thế kỷ + 2 số năm sinh + 6 số ngẫu nhiên
    code = (0 if ngay_sinh.year < 2000 else 2) + (0 if gt == "Nam" else 1)
    return f"{ma_tinh}{code}{ngay_sinh.year % 100:02d}{rng.randrange(10**6):06d}"


def _cccd_het_han(ngay_sinh: date, after: date) -> date:
    """CCCD hết hạn khi chủ thẻ đủ 25, 40, 60 tuổi -> mốc gần nhất sau `after`."""
    for tuoi in (25, 40, 60):
        moc = add_months(ngay_sinh, 12 * tuoi)
        if moc > after:
            return moc
    raise ValueError("chỉ sinh người 22–55 tuổi")


def _change_digits(rng: random.Random, s: str, lo: int, k: int) -> str:
    """Đổi k chữ số trong s[lo:], đảm bảo kết quả khác s."""
    chars = list(s)
    for i in rng.sample(range(lo, len(s)), k):
        chars[i] = rng.choice([d for d in "0123456789" if d != chars[i]])
    return "".join(chars)


def _change_one_diacritic(rng: random.Random, name: str) -> str:
    """Đổi dấu của đúng 1 nguyên âm, kết quả VẪN có dấu và cùng chữ gốc (bỏ dấu thì y hệt)."""
    positions = [(i, fam) for i, ch in enumerate(name) for fam in _VOWEL_FAMILIES if ch.lower() in fam]
    i, fam = rng.choice(positions)
    old = name[i].lower()
    new = rng.choice([c for c in fam[1:] if c != old])  # fam[0] là chữ không dấu -> loại
    return name[:i] + (new.upper() if name[i].isupper() else new) + name[i + 1:]


def _e1_name(rng: random.Random, name: str) -> str:
    parts = name.split()
    # Tên gốc không dấu ("Phan Anh Nam") thì không cài lỗi dấu: rule hybrid coi bên không dấu là
    # "viết không dấu" nên không phân biệt được -> giới hạn đã biết, ghi trong data card.
    kinds = (["diacritic"] if strip_accents(name) != name else []) + ["swap"] + \
        (["drop_middle"] if len(parts) >= 3 else [])
    kind = rng.choice(kinds)
    if kind == "drop_middle":
        out = [parts[0], *parts[1:-1][:-1], parts[-1]] if len(parts) == 4 else [parts[0], parts[-1]]
    elif kind == "swap":
        out = parts[:-2] + [parts[-1], parts[-2]]
        if out == parts:  # chữ đệm trùng tên
            out = [parts[0], parts[-1]]
    else:
        return _change_one_diacritic(rng, name)
    return " ".join(out)


# --- Sinh một bộ --------------------------------------------------------------

def generate_bundle(rng: random.Random, bundle_id: str, errors: list[ErrorCode] = (),
                    near_miss: list[NearMiss] = ()) -> BundleTruth:
    errors, near_miss = list(errors), list(near_miss)
    has = errors.__contains__
    nm = near_miss.__contains__

    # Profile: nguồn sự thật của cả bộ
    ngay_ky = _rand_date(rng, date(2026, 1, 5), date(2026, 9, 15))
    gt = rng.choice(["Nam", "Nữ"])
    ho_ten = _ho_ten(rng, gt)
    ngay_sinh = add_months(ngay_ky, -12 * rng.randint(22, 55)) - timedelta(days=rng.randint(0, 364))
    ma_tinh, tinh, xa_list = rng.choice(P.TINH)
    noi_thuong_tru = f"{rng.choice(xa_list)}, {tinh}"
    _, tinh_qq, xa_qq = rng.choice(P.TINH)
    que_quan = f"{rng.choice(xa_qq)}, {tinh_qq}"
    so_cccd = _so_cccd(rng, ma_tinh, gt, ngay_sinh)
    cong_ty = rng.choice(P.CONG_TY)
    so_tk = str(rng.randrange(10**9, 10**13))

    # CCCD
    if has(E.E5_ID_EXPIRED):
        het_han = ngay_ky - timedelta(days=rng.randint(10, 400))
    elif nm(N.N5_ID_EXPIRES_SOON):
        het_han = ngay_ky + timedelta(days=rng.randint(1, 30))
    else:
        het_han = _cccd_het_han(ngay_sinh, ngay_ky + timedelta(days=30))
    cap_lo = max(date(2021, 1, 1), add_months(ngay_sinh, 12 * 14), het_han - timedelta(days=15 * 365))
    ngay_cap = _rand_date(rng, cap_lo, min(ngay_ky, het_han) - timedelta(days=30))
    cccd = Cccd(so_cccd=so_cccd, ho_ten=ho_ten, ngay_sinh=ngay_sinh, gioi_tinh=gt, que_quan=que_quan,
                noi_thuong_tru=noi_thuong_tru, ngay_cap=ngay_cap, ngay_het_han=het_han)

    # Sao kê: kỳ đúng 3 tháng, kết thúc 1–20 ngày trước ngày ký (qua R8)
    ky_den = ngay_ky - timedelta(days=rng.randint(1, 20))
    ky_tu = add_months(ky_den + timedelta(days=1), -3)
    muc_luong = _floor_to(rng.uniform(8e6, 45e6), 500_000)
    net = muc_luong * (1 - EMPLOYEE_INSURANCE)
    payday = rng.randint(5, 10)
    paydays = []
    d = ky_tu.replace(day=1)
    while d <= ky_den:
        p = d.replace(day=payday)
        if ky_tu <= p <= ky_den:
            paydays.append(p)
        d = add_months(d, 1)
    if nm(N.N6_SALARY_PAID_LATE):
        paydays = paydays[:-1]  # lương tháng cuối về sau ky_den
    cty_ascii = _unaccent_upper(cong_ty)
    mau = rng.choice(P.LUONG_MAU)
    txs: list[GiaoDich] = []
    salaries = []
    for p in paydays:
        ky_luong = add_months(p, -1)
        amt = round(net * rng.uniform(0.97, 1.03), -3)
        salaries.append(amt)
        txs.append(GiaoDich(ngay=p, mo_ta=mau.format(m=ky_luong.month, y=ky_luong.year, cty=cty_ascii),
                            so_tien=int(amt), loai="ghi_co"))
    d = ky_tu
    while d <= ky_den:  # chi tiêu rải đều
        if rng.random() < 0.25:
            txs.append(GiaoDich(ngay=d, mo_ta=rng.choice(P.CHI_TIEU), loai="ghi_no",
                                so_tien=int(round(rng.uniform(50_000, 0.12 * net), -3))))
        d += timedelta(days=1)
    if rng.random() < 0.3:  # chuyển khoản nhỏ từ người quen
        ten = _unaccent_upper(_ho_ten(rng, rng.choice(["Nam", "Nữ"])))
        txs.append(GiaoDich(ngay=_rand_date(rng, ky_tu, ky_den), mo_ta=f"NHAN CK TU {ten}",
                            so_tien=int(round(rng.uniform(200_000, 3_000_000), -3)), loai="ghi_co"))
    # N4: khoản ghi có lớn không phải lương, người gửi họ Lương để thử regex. Cũng cài vào một nửa
    # bộ E4 (không gắn nhãn): nếu rule đếm nhầm khoản này là lương, lương TB bị đội lên và E4 lọt.
    if nm(N.N4_EXTRA_CREDIT) or (has(E.E4_INCOME_INFLATED) and rng.random() < 0.5):
        ten = _unaccent_upper(f"Lương {rng.choice(P.DEM['Nam'])} {rng.choice(P.TEN['Nam'])}")
        for mo_ta in (f"NHAN CK TU {ten}", "HOAN TIEN BAO HIEM SUC KHOE"):
            txs.append(GiaoDich(ngay=_rand_date(rng, ky_tu, ky_den), mo_ta=mo_ta, loai="ghi_co",
                                so_tien=int(round(net * rng.uniform(0.6, 1.5), -3))))
    txs.sort(key=lambda g: (g.ngay, g.loai))
    sao_ke = SaoKe(chu_tk=_unaccent_upper(ho_ten), so_tk=so_tk, ky_tu=ky_tu, ky_den=ky_den, giao_dich=txs)
    luong_tb = sum(salaries) / len(salaries)

    # HĐLĐ: đã làm việc trước kỳ sao kê
    if has(E.E7_CONTRACT_ENDED) or rng.random() < 0.6:
        loai, term = LoaiHd.XAC_DINH_THOI_HAN, rng.choice([12, 24, 36])
        if has(E.E7_CONTRACT_ENDED):
            ket_thuc = ngay_ky - timedelta(days=rng.randint(5, 200))
            bat_dau = add_months(ket_thuc, -term)
        else:
            lo = add_months(ngay_ky + timedelta(days=30), -term)
            bat_dau = _rand_date(rng, lo, ky_tu - timedelta(days=30))
            ket_thuc = add_months(bat_dau, term)
    else:
        loai, ket_thuc = LoaiHd.KHONG_XAC_DINH_THOI_HAN, None
        bat_dau = ky_tu - timedelta(days=rng.randint(60, 2500))
    hdld = Hdld(ho_ten_nld=ho_ten, ten_cong_ty=cong_ty, chuc_danh=rng.choice(P.CHUC_DANH), loai_hd=loai,
                ngay_bat_dau=bat_dau, ngay_ket_thuc=ket_thuc, muc_luong=muc_luong)

    # Đơn đề nghị vay: nơi cài phần lớn lỗi
    if has(E.E4_INCOME_INFLATED):
        khai = _floor_to(luong_tb * rng.uniform(*INCOME_INFLATE), 100_000)
    elif nm(N.N3_INCOME_NEAR):
        khai = _floor_to(luong_tb * rng.uniform(*INCOME_NEAR), 10_000)
    else:
        khai = _floor_to(luong_tb * rng.uniform(0.85, 1.0), 100_000)
    ten_don = ho_ten
    if has(E.E1_NAME_MISMATCH):
        ten_don = _e1_name(rng, ho_ten)
    elif nm(N.N1_NAME_CASE_SPACE):
        ten_don = rng.choice([ho_ten.upper(), ho_ten.lower(), ho_ten.replace(" ", "  ", 1)])
    elif nm(N.N2_NAME_NO_DIACRITICS):
        ten_don = strip_accents(ho_ten)
    sinh_don = ngay_sinh
    if has(E.E3_DOB_MISMATCH):
        while sinh_don == ngay_sinh:
            sinh_don = (add_months(ngay_sinh, rng.choice([-1, 1])) if rng.random() < 0.5
                        else ngay_sinh + timedelta(days=rng.choice([-3, -2, -1, 1, 2, 3])))
    don = DonVay(
        ho_ten=ten_don,
        so_cccd=_change_digits(rng, so_cccd, 6, rng.randint(1, 2)) if has(E.E2_ID_MISMATCH) else so_cccd,
        ngay_sinh=sinh_don, so_dien_thoai="0" + rng.choice("35789") + f"{rng.randrange(10**8):08d}",
        dia_chi=noi_thuong_tru, ten_cong_ty=cong_ty, thu_nhap_thang=khai,
        so_tien_vay=rng.randrange(20, 501, 5) * 1_000_000, thoi_han_thang=rng.choice([12, 24, 36, 48, 60]),
        muc_dich=rng.choice(P.MUC_DICH),
        so_tk_nhan_luong=_change_digits(rng, so_tk, 0, rng.randint(1, 2)) if has(E.E6_ACCOUNT_MISMATCH) else so_tk,
        ngay_ky=ngay_ky)

    docs = {DocType.CCCD: cccd, DocType.DON_VAY: don, DocType.HDLD: hdld, DocType.SAO_KE: sao_ke}
    missing = []
    if has(E.E8_MISSING_DOC):
        missing = [rng.choice([DocType.CCCD, DocType.HDLD, DocType.SAO_KE])]
        del docs[missing[0]]
    return BundleTruth(bundle_id=bundle_id, docs=docs, errors=errors, near_miss=near_miss, missing=missing)


# --- Kế hoạch phân tầng -----------------------------------------------------------

def plan(n: int, rng: random.Random, error_share: float = 0.5, near_miss_share_of_clean: float = 1 / 3,
         two_error_share: float = 0.10) -> list[tuple[list[ErrorCode], list[NearMiss]]]:
    """Phân bố theo spec: ~50% bộ lỗi (mã chia ĐỀU, không bốc ngẫu nhiên), ~10% bộ lỗi có 2 lỗi;
    ~50% bộ sạch, trong đó 1/3 có near-miss (chia đều N1–N6)."""
    n_err = round(n * error_share)
    n_nm = round((n - n_err) * near_miss_share_of_clean)
    codes = list(ErrorCode)
    primary = [codes[i % len(codes)] for i in range(n_err)]
    rng.shuffle(primary)
    out: list[tuple[list[ErrorCode], list[NearMiss]]] = [([c], []) for c in primary]
    # ~10% bộ lỗi có thêm lỗi thứ 2 (không ghép với E8: thiếu giấy tờ làm rule khác thành unknown)
    eligible = [o for o in out if o[0][0] is not E.E8_MISSING_DOC]
    for errs, _ in rng.sample(eligible, min(len(eligible), round(n_err * two_error_share))):
        errs.append(rng.choice([x for x in codes if x not in (errs[0], E.E8_MISSING_DOC)]))
    nms = list(NearMiss)
    out += [([], [nms[i % len(nms)]]) for i in range(n_nm)]
    out += [([], [])] * (n - n_err - n_nm)
    rng.shuffle(out)
    return out
