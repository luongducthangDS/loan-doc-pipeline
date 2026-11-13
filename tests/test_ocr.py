import hashlib
import json

import pytest
from pydantic import ValidationError

from loanpipe.validate import parse_transactions
from loanpipe.extract.ocr import (Line, OCRReader, extract_doc, extract_period, find_money, find_text,
                                  fold, ordered, parse_statement_page, repair, text_after_label,
                                  value_from)
from loanpipe.schemas import DocType


def boxed(text, x0, y0, x1, y1):
    return Line(text, (x0, y0, x1, y1))


def plain(lines):
    return [Line(x) for x in lines]


# --- Chuỗi -----------------------------------------------------------------------

def test_fold_and_repair_ocr_digits():
    assert fold("Số CCCD: 0310818") == "so cccd 0310818"
    assert repair("21.200.0o0đ") == "21.200.000đ"  # o -> 0, đ giữ nguyên
    assert find_money("26.000.0O00") is None       # nhóm nghìn hỏng: không đoán
    assert find_money("thu nhập 32.800.000 VNĐ") == "32.800.000"


def test_value_from_only_strips_real_label_prefix():
    # Nhãn tiếng Anh dính giá trị
    assert value_from("ÔngIBà: Hoàng Đức Trung", find_text) == "Hoàng Đức Trung"
    # Dấu ':' nằm trong giá trị (TP. bị OCR thành TP:) thì không cắt
    addr = "Phường 12, Quận Tân Bình, TP: Hổ Chí Minh"
    assert value_from(addr, find_text) == addr


# --- Neo nhãn ---------------------------------------------------------------------

CCCD_LINES = [
    "CĂN CƯỚC CÔNG DÂN", "Số", "No.:", "031081826581",
    "Họ và tên", "Full name:", "HOÀNG ĐỨC TRUNG",
    "Ngày sinh", "Date of birth:", "25/07/1981",
    "Giới tính", "Sex:", "Nam",
    "Quê quán", "Place of origin:", "Phường Dịch Vọng, Quận Cầu Giấy, Hà Nội",
    "Nơi thường trú", "Place of residence:", "Phường Máy Tơ, Quận Ngô Quyền, Hải Phòng",
    "Có giá trị đến", "Date of expiry: 25/07/2041",
]

CCCD_BACK = ["Đặc điểm nhân dạng", "Ngày, tháng, năm", "Date, month, year: 29/07/2026"]


def test_cccd_anchors_and_pages():
    out = extract_doc(DocType.CCCD, [plain(CCCD_LINES), plain(CCCD_BACK)])
    assert out["so_cccd"] == ("031081826581", 1)
    assert out["ho_ten"] == ("HOÀNG ĐỨC TRUNG", 1)
    assert out["ngay_sinh"] == ("25/07/1981", 1)
    assert out["gioi_tinh"] == ("Nam", 1)
    assert out["ngay_het_han"] == ("25/07/2041", 1)
    assert out["ngay_cap"] == ("29/07/2026", 2)


def test_don_vay_layout_a_inline_and_wrapped_labels():
    lines = [
        "Họ và tên: Bùi Kim Lan", "Ngày sinh: 05/12/2000", "Số CCCD: 079300551897",
        "Điện thoại: 0377492281",
        "Địa chỉ thường trú: Phường 12, Quận Tân Bình, TP: Hổ Chí Minh",
        "Nơi công tác: CÔNG TY CỔ PHẦN THƯƠNG MẠI BẮC NAM",
        "Thu nhập thực nhận", "tháng: 32.800.000 VNĐ",
        "Số tài khoản nhận lương: 5411066449133",
        "Số tiền đề nghị vay: 395.000.000",
        "Thời hạn vay: 12 tháng",
        "Mục đích vay: Sửa chữa nhà ở",
        "Hà Nội, ngày 15 tháng 09 năm 2026",
    ]
    out = extract_doc(DocType.DON_VAY, [plain(lines)])
    assert out["ho_ten"][0] == "Bùi Kim Lan"
    assert out["so_cccd"][0] == "079300551897"
    assert out["so_dien_thoai"][0] == "0377492281"
    assert out["dia_chi"][0].endswith("Hổ Chí Minh")
    assert out["thu_nhap_thang"][0] == "32.800.000"
    assert out["so_tk_nhan_luong"][0] == "5411066449133"
    assert out["so_tien_vay"][0] == "395.000.000"
    assert out["thoi_han_thang"][0] == "12"
    assert out["muc_dich"][0] == "Sửa chữa nhà ở"
    assert out["ngay_ky"][0] == "15/09/2026"


def test_don_vay_layout_b_table_rows():
    lines = [
        "Họ tên", "vay", "Hoàng Đức Trung",
        "CCCD số", "031081826581",
        "Ngày tháng năm sinh", "25-07-1981",
        "Số điện thoại di động", "0989 810 798",
        "Thu nhập bình quân/tháng", "21.200.0o0đ",
        "Tài khoản nhận lương số", "8791 8142 0345",
        "Số tiển vay", "375.000.0o0đ",
        "Thời hạn vay", "tháng)", "60",
        "đích sử dụng vốn", "Tiêu dùng cá nhân",
        "Ngày ký: 25/03/2026",
    ]
    out = extract_doc(DocType.DON_VAY, [plain(lines)])
    assert out["ho_ten"][0] == "Hoàng Đức Trung"
    assert out["thu_nhap_thang"][0] == "21.200.000"
    assert out["so_tien_vay"][0] == "375.000.000"
    assert out["thoi_han_thang"][0] == "60"
    assert out["muc_dich"][0] == "Tiêu dùng cá nhân"
    assert out["so_tk_nhan_luong"][0] == "8791 8142 0345"


def test_don_vay_account_fallback_never_copies_cccd():
    lines = ["Số CCCD: 079300551897", "Số tiền đề nghị vay: 395.000.000"]
    out = extract_doc(DocType.DON_VAY, [plain(lines)])
    assert "so_tk_nhan_luong" not in out


def test_hdld_layout_b_wrapped_labels():
    lines = [
        "Chúng tôi , một bên là: CÔNG TY CỔ PHẦN SAO MAI",
        "Và một bên là", "ÔngIBà: Hoàng Đức Trung",
        "Điểu 1. Thời hạn và công việc hợp đổng",
        "Loại hợp đổng lao động: Xác định thời hạn 36 tháng",
        "Thời", "bắt đẩu: ngày 05 tháng 12 năm 2023",
        "Thời gian kết thúc: ngày 05 tháng 12 năm 2026",
        "Chức vụ: Nhân viên hành chính",
        "Mức lương chính hoặc tiển", "26.000.000đ",
    ]
    out = extract_doc(DocType.HDLD, [plain(lines)])
    assert out["ten_cong_ty"][0] == "CÔNG TY CỔ PHẦN SAO MAI"
    assert out["ho_ten_nld"][0] == "Hoàng Đức Trung"
    assert out["loai_hd"][0] == "Xác định thời hạn 36 tháng"
    assert out["ngay_bat_dau"][0] == "05/12/2023"
    assert out["ngay_ket_thuc"][0] == "05/12/2026"
    assert out["muc_luong"][0] == "26.000.000"


def test_sao_ke_period_two_dates():
    pages = [[Line("SAO KÊ TÀI KHOẢN"), Line("Từ ngày 21/12/2025 đến ngày 20/03/2026")]]
    assert extract_period(pages) == ("21/12/2025", "20/03/2026", 1)


# --- Bảng sao kê --------------------------------------------------------------------

@pytest.mark.parametrize("debit_header", ["Ghi nợ", "Ghi ng"])
def test_statement_layout_a_uses_column_x_for_direction(debit_header):
    lines = [
        boxed("Ngày", 0, 0, 60, 20), boxed("Nội dung", 100, 0, 300, 20),
        boxed("Ghi có", 700, 0, 780, 20), boxed(debit_header, 900, 0, 980, 20),
        boxed("21/12/2025", 0, 40, 90, 60), boxed("NAP TIEN", 100, 40, 300, 60),
        boxed("955,000", 900, 42, 980, 62),
        boxed("07/01/2026", 0, 80, 90, 100), boxed("LUONG T12", 100, 80, 300, 100),
        boxed("23,964,000", 700, 82, 780, 102),
    ]
    rows = parse_statement_page(lines)
    assert [(r["ngay"], r["so_tien"], r["loai"]) for r in rows] == [
        ("21/12/2025", "955,000", "Ghi nợ"), ("07/01/2026", "23,964,000", "Ghi có")]


def test_statement_layout_b_sign_and_merged_cells():
    lines = [
        boxed("Ngày GD", 0, 0, 90, 20), boxed("Số tiền", 100, 0, 200, 20),
        boxed("Diễn giải", 300, 0, 500, 20),
        boxed("24/01/2026", 0, 40, 90, 60), boxed("-2,892,000", 100, 40, 200, 60),
        boxed("THANH TOAN QR", 300, 40, 500, 60),
        boxed("15/02/2026", 0, 80, 90, 100), boxed("-704,000 PHI QUAN LY", 100, 80, 340, 100),
    ]
    rows = parse_statement_page(lines)
    assert [(r["ngay"], r["so_tien"], r["loai"], r["mo_ta"]) for r in rows] == [
        ("24/01/2026", "2,892,000", "Ghi nợ", "THANH TOAN QR"),
        ("15/02/2026", "704,000", "Ghi nợ", "PHI QUAN LY")]


@pytest.mark.parametrize("amount", ["95,000", "26.000.0O00"])
def test_statement_small_amount_and_malformed_grouping(amount):
    rows = parse_statement_page(plain(["23/04/2026", f"-{amount}", "PHI QUAN LY"]))
    if amount == "95,000":
        assert parse_transactions(json.dumps(rows))[0].so_tien == 95000
    else:
        assert len(rows) == 1 and rows[0]["so_tien"] == ""
        with pytest.raises(ValueError):
            parse_transactions(json.dumps(rows))


@pytest.mark.parametrize("with_boxes", [False, True])
def test_missing_sign_stays_unknown_and_invalidates_statement(with_boxes):
    texts = ["Ngày GD", "Số tiền", "Diễn giải", "24/01/2026", "715,000", "TRA LUONG"]
    lines = ([boxed(t, x, y, x + 90, y + 20) for t, x, y in zip(
        texts, [0, 100, 300, 0, 100, 300], [0, 0, 0, 40, 40, 40])]
        if with_boxes else plain(texts))
    rows = parse_statement_page(lines)
    assert len(rows) == 1 and rows[0]["loai"] == ""
    with pytest.raises(ValidationError):
        parse_transactions(json.dumps(rows))


def test_statement_text_fallback_reads_signed_rows():
    lines = ["Ngày GD", "24/01/2026", "-2,892,000", "THANH TOAN QR",
             "05/02/2026", "+38,436,000", "TRA LUONG THANG 01/2026", "CONG TY MINH LONG"]
    rows = parse_statement_page([Line(x) for x in lines])
    assert rows[0]["loai"] == "Ghi nợ" and rows[1]["loai"] == "Ghi có"
    assert rows[1]["mo_ta"] == "TRA LUONG THANG 01/2026 CONG TY MINH LONG"


# --- Thứ tự đọc và nối dòng wrap ------------------------------------------------------

def test_ordered_fixes_scrambled_detector_order():
    # Ảnh photo: detector trả giá trị trước nhãn; cùng hàng thì xếp theo x
    lines = [boxed("Giá trị", 200, 42, 400, 60), boxed("Nhãn:", 40, 40, 140, 60),
             boxed("dòng dưới", 40, 100, 200, 120)]
    assert [ln.text for ln in ordered(lines)] == ["Nhãn:", "Giá trị", "dòng dưới"]


def test_don_vay_joins_wrapped_value_by_column():
    # Giá trị sau 'nhãn:' bị wrap xuống 2 dòng, thụt vào so với lề nhãn
    lines = [
        boxed("Nơi thường trú:", 40, 0, 180, 20), boxed("Phường Máy Tơ, Quận", 220, 0, 460, 20),
        boxed("Ngô Quyền,", 220, 24, 340, 44), boxed("Hải Phòng", 220, 48, 340, 68),
        boxed("Số CCCD: 031081826581", 40, 80, 300, 100),
    ]
    got = extract_doc(DocType.CCCD, [ordered(lines)])
    assert got["noi_thuong_tru"][0] == "Phường Máy Tơ, Quận Ngô Quyền, Hải Phòng"


def test_short_inline_value_not_dropped():
    # Giá trị thật có thể chỉ 2 chữ cái; find_text chặn để tránh nuốt tiêu đề, sau 'nhãn:' thì không
    assert find_text("TA") is None and text_after_label("TA") == "TA"
    lines = [boxed("Tên tài khoản: TA", 40, 0, 240, 20), boxed("HUU NAM", 250, 24, 400, 44),
             boxed("Số TK: 2827586080915", 40, 60, 300, 80)]
    got = extract_doc(DocType.SAO_KE, [ordered(lines)])
    assert got["chu_tk"][0] == "TA HUU NAM"


def test_bilingual_label_is_not_taken_as_value():
    lines = [boxed("Họ và tên", 40, 0, 140, 20), boxed("Full nome:", 40, 24, 140, 44),
             boxed("LƯƠNG THÀNH HUY", 40, 48, 300, 68),
             boxed("Số", 40, 100, 80, 120), boxed("No.:", 40, 124, 100, 144),
             boxed("031081826581", 40, 148, 240, 168)]
    got = extract_doc(DocType.CCCD, [ordered(lines)])
    assert got["ho_ten"][0] == "LƯƠNG THÀNH HUY"
    assert got["so_cccd"][0] == "031081826581"


# --- Cache --------------------------------------------------------------------------


def test_ocr_evaluator_uses_one_pass_and_writes_consistent_metadata(tmp_path, monkeypatch):
    from datagen.build import build_split
    from loanpipe import evaluate
    from loanpipe.config import load_thresholds
    from loanpipe.extract.oracle import OracleExtractor

    entries = build_split("dev", 50, 3, None, images=False)
    data = tmp_path / "data"
    (data / "dev").mkdir(parents=True)
    (data / "dev" / "manifest.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries), "utf-8")
    calls = []

    class SinglePassOCR(OracleExtractor):
        name = "ocr"

        def extract(self, bundle_id, doc_id, doc_type, files, variant=0):
            calls.append(variant)
            return super().extract(bundle_id, doc_id, doc_type, files, variant)

    out = tmp_path / "reports"
    monkeypatch.setattr(evaluate, "get_extractor", lambda *a, **kw: SinglePassOCR(entries))
    monkeypatch.setattr(evaluate, "git_commit", lambda: "test")
    monkeypatch.setattr(evaluate.sys.stdout, "reconfigure", lambda **kw: None, raising=False)
    monkeypatch.setattr(evaluate.sys, "argv", ["evaluate", "--extractor", "ocr", "--data", str(data),
                                              "--out", str(out), "--limit", "1", "--no-file-check"])
    evaluate.main()
    metrics = json.loads(next(out.glob("*/metrics.json")).read_text("utf-8"))
    assert metrics["meta"]["self_consistency"] is False
    assert calls == [0] * len(entries[0]["docs"])
    assert metrics["ops"]["calls_per_bundle"] == len(calls)
    assert load_thresholds().use_self_consistency is True
    import csv
    with (out / "runs.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == evaluate.RUNS_FIELDS and len(rows[1]) == len(rows[0])


def test_reader_uses_text_cache_without_engine(tmp_path):
    class Boom:
        def readtext(self, *a, **k):
            raise AssertionError("không được gọi OCR khi đã có cache")

    f = tmp_path / "page.jpg"
    f.write_bytes(b"fake")
    key = hashlib.sha1(b"fake").hexdigest()[:24]
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / f"{key}.json").write_text(json.dumps(["Ngày", "21/12/2025"]), "utf-8")
    lines, ms = OCRReader(tmp_path / "text", tmp_path / "boxes", engine=Boom()).read(f)
    assert [x.text for x in lines] == ["Ngày", "21/12/2025"] and ms == 0
