"""Review UI chạy headless (Streamlit AppTest): hàng đợi không có bộ AUTO_PASS; mở bộ qua ?bundle=, sửa field,
chốt -> SQLite ghi đúng, vẫn ở bộ đó."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from loanpipe import review as rv  # noqa: E402


def html(at: AppTest) -> str:
    return " ".join(el.proto.body for el in at.get("html"))


def test_review_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_DB", str(tmp_path / "r.sqlite"))
    at = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not at.exception
    page = html(at)
    assert "?bundle=dev_0025" in page and "?bundle=dev_0000" not in page  # dev_0000 AUTO_PASS: ngoài hàng đợi

    at.query_params["bundle"] = "dev_0025"  # tên công ty đọc ra chữ rác -> GARBLED
    at.run()
    at.text_input(key="dev_0025/don_vay/ten_cong_ty").input("CÔNG TY CỔ PHẦN THƯƠNG MẠI BẮC NAM").run()
    next(w for w in at.text_input if w.label == "Người rà soát").input("demo").run()
    next(w for w in at.radio if w.label == "Kết luận").set_value("valid").run()
    next(b for b in at.button if b.label == "Chốt hồ sơ").click().run()

    assert not at.exception and at.query_params["bundle"] == ["dev_0025"]
    row = rv.items(rv.connect())["dev_0025"]
    assert (row["status"], row["reviewer"], row["conclusion"]) == ("closed", "demo", "valid")
    assert "don_vay.ten_cong_ty" in row["edits"] and row["closed_at"] >= row["opened_at"]


def test_use_peer_value(tmp_path, monkeypatch):
    """R1 fail do model đọc nhầm tên trên HĐLĐ: nút 'Dùng giá trị ...' chép giá trị giấy tờ kia vào field."""
    monkeypatch.setenv("REVIEW_DB", str(tmp_path / "r.sqlite"))
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.query_params["bundle"] = "dev_0020"
    at.run()
    key = "dev_0020/hdld/ho_ten_nld"
    assert at.text_input(key=key).value == "HÓ HỮU VIỆT THỊNH"
    page = html(at)  # R7 fail: nói rõ lỗi, không lặp tên phép kiểm "HĐLĐ còn hiệu lực"
    assert "HĐLĐ hết hiệu lực" in page and "HĐLĐ còn hiệu lực:" not in page
    # chỉ gợi ý giá trị số đông (CCCD + đơn vay); tên đúng và tên không dấu ở sao kê không bị gợi ý đổi
    assert {b.key for b in at.button if b.key and b.key.startswith("use/")} == {f"use/{key}/don_vay"}
    next(b for b in at.button if b.key == f"use/{key}/don_vay").click().run()
    assert not at.exception and at.text_input(key=key).value == "HỒ HỮU VIỆT THỊNH"


def test_every_sample_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_DB", str(tmp_path / "r.sqlite"))
    for bid in rv.load_samples()[2]:
        at = AppTest.from_file("../app.py", default_timeout=60)
        at.query_params["bundle"] = bid
        assert not at.run().exception, bid
