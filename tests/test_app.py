"""Review UI chạy headless (Streamlit AppTest): mở bộ, sửa field, chốt -> SQLite ghi đúng, vẫn ở bộ đó."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from loanpipe import review as rv  # noqa: E402


def test_review_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_DB", str(tmp_path / "r.sqlite"))
    at = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not at.exception
    queue = at.radio(key="bundle").options
    assert queue and not any("tự duyệt" in o for o in queue)  # mặc định không hiện bộ AUTO_PASS

    at.radio(key="bundle").set_value("dev_0025").run()  # tên công ty đọc ra chữ rác -> GARBLED
    at.text_input(key="dev_0025/don_vay/ten_cong_ty").input("CÔNG TY CỔ PHẦN THƯƠNG MẠI BẮC NAM").run()
    next(w for w in at.text_input if w.label == "Người rà soát").input("demo").run()
    next(w for w in at.radio if w.label == "Kết luận").set_value("valid").run()
    next(b for b in at.button if b.label == "Chốt hồ sơ").click().run()

    assert not at.exception and at.radio(key="bundle").value == "dev_0025"
    row = rv.items(rv.connect())["dev_0025"]
    assert (row["status"], row["reviewer"], row["conclusion"]) == ("closed", "demo", "valid")
    assert "don_vay.ten_cong_ty" in row["edits"] and row["closed_at"] >= row["opened_at"]
