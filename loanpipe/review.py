"""Hàng đợi rà soát (spec mục 8) và bộ mẫu cho demo public (spec mục 10).

Demo public KHÔNG gọi model và KHÔNG có upload: nó đọc kết quả pipeline đã chạy sẵn trên một bộ nhỏ
hồ sơ dev (ảnh + trace), commit trong data/synthetic/samples/. Test set không bao giờ vào đây.

    python -m loanpipe.review build --run reports/<run_id dev>   # chọn bộ phủ mọi nhánh, chép ảnh + trace
    streamlit run app.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

SAMPLES = Path("data/synthetic/samples")
DB = Path("data/review.sqlite")  # data/* bị gitignore: kết quả rà soát không vào repo. Đổi bằng $REVIEW_DB
CONCLUSIONS = {"valid": "Hồ sơ hợp lệ", "request_more": "Yêu cầu bổ sung giấy tờ",
               "discrepancy": "Sai lệch, cần làm rõ với khách"}


# --- Bộ mẫu -----------------------------------------------------------------------------

def pick_samples(entries: list[dict], traces: dict[str, dict], n_auto: int = 2) -> list[str]:
    """Bộ nhỏ nhưng phủ mọi nhánh: auto-pass đúng, mỗi mã lỗi E1–E8, mỗi near-miss, và mọi bộ sạch
    bị đẩy sang REVIEW (chỗ pipeline chưa hoàn hảo: nên cho người xem thấy, không giấu)."""
    route = {b: t["decision"]["route"] for b, t in traces.items()}
    picked: list[str] = []

    def add(b: str) -> None:
        if b in route and b not in picked:
            picked.append(b)

    for e in [e for e in entries if e["expected_route"] == route.get(e["bundle_id"]) == "AUTO_PASS"][:n_auto]:
        add(e["bundle_id"])
    for key in ("injected_errors", "near_miss"):
        seen: set[str] = set()
        for e in entries:
            for code in {x["code"] for x in e[key]} - seen:
                seen.add(code)
                add(e["bundle_id"])
    for e in entries:
        if e["expected_route"] == "AUTO_PASS" and route.get(e["bundle_id"]) != "AUTO_PASS":
            add(e["bundle_id"])
    return picked


def build_samples(run_dir: Path, split_dir: Path, out: Path = SAMPLES) -> list[str]:
    entries = [json.loads(line) for line in (split_dir / "manifest.jsonl").read_text("utf-8").splitlines()]
    traces = {p.stem: json.loads(p.read_text("utf-8")) for p in (run_dir / "traces").glob("*.json")}
    picked = pick_samples(entries, traces)
    if out.exists():
        shutil.rmtree(out)
    for e in (e for e in entries if e["bundle_id"] in picked):
        for f in (f for d in e["docs"] for f in d["files"]):
            (out / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(split_dir / f, out / f)
        (out / e["bundle_id"] / "trace.json").write_text(
            json.dumps(traces[e["bundle_id"]], ensure_ascii=False, indent=1), "utf-8")
    keep = [e for e in entries if e["bundle_id"] in picked]
    (out / "manifest.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep), "utf-8")
    meta = json.loads((run_dir / "metrics.json").read_text("utf-8"))["meta"]
    (out / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    return picked


def load_samples(root: Path = SAMPLES) -> tuple[dict, list[dict], dict[str, dict]]:
    """-> (meta của run, manifest, {bundle_id: trace})."""
    entries = [json.loads(line) for line in (root / "manifest.jsonl").read_text("utf-8").splitlines()]
    traces = {e["bundle_id"]: json.loads((root / e["bundle_id"] / "trace.json").read_text("utf-8"))
              for e in entries}
    return json.loads((root / "run.json").read_text("utf-8")), entries, traces


# --- Hàng đợi rà soát (SQLite) --------------------------------------------------------------

_SCHEMA = """create table if not exists review (
    bundle_id text primary key, route text, reasons text, status text not null default 'open',
    reviewer text, conclusion text, edits text, note text, opened_at real, closed_at real)"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or os.environ.get("REVIEW_DB") or DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)  # Streamlit gọi từ nhiều thread
    con.row_factory = sqlite3.Row
    con.execute(_SCHEMA)
    return con


def open_item(con: sqlite3.Connection, bundle_id: str, route: str, reasons: list[str]) -> None:
    """Lần đầu reviewer mở bộ: bắt đầu tính giờ. Mở lại không reset."""
    con.execute("insert or ignore into review (bundle_id, route, reasons, opened_at) values (?, ?, ?, ?)",
                (bundle_id, route, json.dumps(reasons), time.time()))
    con.commit()


def close_item(con: sqlite3.Connection, bundle_id: str, reviewer: str, conclusion: str,
               edits: dict[str, dict], note: str = "") -> None:
    if conclusion not in CONCLUSIONS:
        raise ValueError(f"kết luận không hợp lệ: {conclusion!r}")
    con.execute("update review set status='closed', reviewer=?, conclusion=?, edits=?, note=?, closed_at=? "
                "where bundle_id=?", (reviewer, conclusion, json.dumps(edits, ensure_ascii=False), note,
                                       time.time(), bundle_id))
    con.commit()


def items(con: sqlite3.Connection) -> dict[str, dict]:
    return {r["bundle_id"]: dict(r) for r in con.execute("select * from review")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--run", type=Path, required=True, help="reports/<run_id> của một run trên dev")
    ap.add_argument("--split-dir", type=Path, default=Path("data/synthetic/dev"))
    a = ap.parse_args()
    if json.loads((a.run / "metrics.json").read_text("utf-8"))["meta"]["split"] != "dev":
        raise SystemExit("Chỉ dùng run trên dev: test set đóng băng, không đưa ra demo public.")
    print(f"{len(build_samples(a.run, a.split_dir))} bộ -> {SAMPLES}")
