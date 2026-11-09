import pytest

from loanpipe import review as rv


def test_close_item_rejects_unknown_bundle(tmp_path):
    con = rv.connect(tmp_path / "review.sqlite")

    with pytest.raises(LookupError, match="review item not found"):
        rv.close_item(con, "missing", "reviewer", "valid", {})

    assert rv.items(con) == {}
    con.close()


def test_invalid_conclusion_does_not_close_item(tmp_path):
    con = rv.connect(tmp_path / "review.sqlite")
    rv.open_item(con, "bundle-1", "REVIEW", ["R1"])

    with pytest.raises(ValueError, match="kết luận không hợp lệ"):
        rv.close_item(con, "bundle-1", "reviewer", "unknown", {})

    row = rv.items(con)["bundle-1"]
    assert row["status"] == "open"
    assert row["closed_at"] is None
    con.close()
