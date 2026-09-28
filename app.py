"""Review UI (spec mục 8): hàng đợi REVIEW / REQUEST_MORE, ảnh gốc cạnh field đã trích, field bị gắn cờ
tô sáng kèm evidence, reviewer sửa field rồi chốt 1 trong 3 kết luận.

Demo public: chỉ bộ mẫu synthetic có sẵn, KHÔNG upload, KHÔNG gọi model (spec mục 10).
    streamlit run app.py
"""

from __future__ import annotations

import json
import time

import streamlit as st

from loanpipe import review as rv
from loanpipe.extract.vlm import FIELD_HINT

DOC_NAMES = {"cccd": "CCCD", "don_vay": "Đơn vay", "hdld": "HĐLĐ", "sao_ke": "Sao kê"}
ROUTE_STYLE = {"AUTO_PASS": ("✅", st.success), "REVIEW": ("🟠", st.warning), "REQUEST_MORE": ("🔴", st.error)}
STATUS_ICON = {"pass": "✅", "fail": "❌", "unknown": "❓"}

st.set_page_config(page_title="Rà soát hồ sơ vay", page_icon="📄", layout="wide")
meta, entries, traces = st.cache_data(rv.load_samples)()
con = st.cache_resource(rv.connect)()
by_id = {e["bundle_id"]: e for e in entries}


def flagged_fields(trace: dict) -> dict[tuple[str, str], list[str]]:
    """(doc_type, field) -> lý do: evidence của rule fail/unknown + field confidence thấp / lỗi / chữ rác."""
    out: dict[tuple[str, str], list[str]] = {}
    for c in trace["checks"]:
        if c["status"] != "pass":
            for ev in c["evidence"]:  # rule unknown: chỉ tô field chưa biết, không tô field đã chắc
                if "field" in ev and (c["status"] == "fail" or not ev.get("known", True)):
                    out.setdefault((ev["doc_type"], ev["field"]), []).append(f"{c['rule_id']}: {c['message']}")
    for r in trace["decision"]["reasons"]:
        if ":" in r and "." in r:
            kind, ref = r.split(":", 1)
            out.setdefault(tuple(ref.split(".", 1)), []).append(kind)
    return out


def show(v) -> str:
    return "" if v is None else v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


# --- Sidebar: hàng đợi --------------------------------------------------------------------------
with st.sidebar:
    st.header("Hàng đợi rà soát")
    st.caption(f"Kết quả trích xuất chạy sẵn: `{meta['model']}`, prompt {meta['prompt_version']}, "
               f"{meta['rules_version']}.")
    show_auto = st.toggle("Hiện cả bộ đã tự duyệt (AUTO_PASS)", value=False)
    done = rv.items(con)
    queue = [b for b, t in traces.items() if show_auto or t["decision"]["route"] != "AUTO_PASS"]
    closed = [d for d in done.values() if d["status"] == "closed"]
    c1, c2 = st.columns(2)
    c1.metric("Đã xử lý", f"{len(closed)}/{sum(t['decision']['route'] != 'AUTO_PASS' for t in traces.values())}")
    if closed:
        c2.metric("TB mỗi bộ", f"{sum(d['closed_at'] - d['opened_at'] for d in closed) / len(closed) / 60:.1f} phút")

    def label(b: str) -> str:
        d = traces[b]["decision"]
        mark = "☑️ " if done.get(b, {}).get("status") == "closed" else ""
        return f"{mark}{ROUTE_STYLE[d['route']][0]} {b} · {', '.join(d['reasons'][:2]) or 'tự duyệt'}"

    bid = st.radio("Bộ hồ sơ", queue, format_func=label, label_visibility="collapsed", key="bundle")

# --- Main -------------------------------------------------------------------------------------
st.title("Rà soát hồ sơ vay tiêu dùng")
st.caption("MẪU – DỮ LIỆU TỔNG HỢP. Tên người, công ty, ngân hàng đều hư cấu. Demo không có upload "
           "và không gọi model; ngưỡng rule là giả định cho demo, không phải chính sách tín dụng.")
if not bid:
    st.stop()

t, e = traces[bid], by_id[bid]
dec = t["decision"]
if dec["route"] != "AUTO_PASS":
    rv.open_item(con, bid, dec["route"], dec["reasons"])
icon, box = ROUTE_STYLE[dec["route"]]
box(f"**{bid}** → **{dec['route']}**" + (f" · lý do: {', '.join(dec['reasons'])}" if dec["reasons"] else ""))

with st.expander("Kết quả 9 rule", expanded=dec["route"] != "AUTO_PASS"):
    for c in t["checks"]:
        st.markdown(f"{STATUS_ICON[c['status']]} **{c['rule_id']}** {c['message']}")

flags = flagged_fields(t)
edits: dict[str, dict] = {}
ext = {x["doc_type"]: x for x in t["extractions"]}
tabs = st.tabs([f"{DOC_NAMES[d['type']]}" + (" ⚠️" if any(k[0] == d["type"] for k in flags) else "")
                for d in e["docs"]])
for tab, d in zip(tabs, e["docs"]):
    with tab:
        left, right = st.columns([1, 1])
        with left:
            for f in d["files"]:
                st.image(str(rv.SAMPLES / f), width="stretch")
        with right:
            if d["type"] not in ext:
                st.error("Không đọc được giấy tờ này (thiếu hoặc ảnh hỏng).")
                continue
            for name, fld in ext[d["type"]]["fields"].items():
                why = flags.get((d["type"], name))
                hint = FIELD_HINT.get(name, name).split(";")[0]
                if name == "giao_dich":  # ponytail: bảng giao dịch chỉ xem, sửa từng dòng khi có nhu cầu thật
                    st.markdown(f"**{name}** · {'⚠️ ' + '; '.join(why) if why else ''}")
                    st.dataframe(fld["value"] or [], width="stretch", height=220)
                    continue
                new = st.text_input(f"{'⚠️ ' if why else ''}{name} ({hint})", show(fld["value"]),
                                    key=f"{bid}/{d['type']}/{name}",
                                    help=f"Chép từ ảnh: {fld['raw']!r} · confidence {fld['confidence']}"
                                         + (f" · lỗi: {fld['error']}" if fld["error"] else ""))
                if why:
                    st.caption("🟠 " + "; ".join(why))
                if new != show(fld["value"]):
                    edits[f"{d['type']}.{name}"] = {"from": show(fld["value"]), "to": new}

st.divider()
if dec["route"] == "AUTO_PASS":
    st.info("Bộ này đã tự duyệt: qua hết 9 rule, mọi field quan trọng confidence cao. Không vào hàng đợi.")
else:
    row = rv.items(con).get(bid, {})
    if row.get("status") == "closed":
        st.success(f"Đã chốt: **{rv.CONCLUSIONS[row['conclusion']]}** bởi {row['reviewer']} sau "
                   f"{(row['closed_at'] - row['opened_at']) / 60:.1f} phút. Sửa: {row['edits']}")
    with st.form(f"close/{bid}"):
        st.subheader("Kết luận")
        if edits:
            st.write("Field đã sửa:", edits)
        reviewer = st.text_input("Người rà soát", value=row.get("reviewer") or "")
        conclusion = st.radio("Kết luận", list(rv.CONCLUSIONS), format_func=rv.CONCLUSIONS.get, horizontal=True)
        note = st.text_area("Ghi chú", value=row.get("note") or "")
        if st.form_submit_button("Chốt hồ sơ", type="primary"):
            if not reviewer.strip():
                st.error("Nhập tên người rà soát.")
            else:
                rv.close_item(con, bid, reviewer.strip(), conclusion, edits, note)
                st.rerun()
    if row.get("opened_at"):
        st.caption(f"Mở lúc {time.strftime('%H:%M:%S', time.localtime(row['opened_at']))}")

with st.expander("Nhãn thật (chỉ có vì dữ liệu tổng hợp)"):
    st.write({"route đúng": e["expected_route"], "lỗi cài vào": e["injected_errors"],
              "near-miss": e["near_miss"], "mức ảnh": e["augment"], "layout": e["layout_ids"]})
