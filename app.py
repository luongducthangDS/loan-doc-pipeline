"""Review UI (spec mục 8): hàng đợi REVIEW / REQUEST_MORE, ảnh gốc cạnh field đã trích, field bị gắn cờ
tô sáng kèm evidence, reviewer sửa field rồi chốt 1 trong 3 kết luận.

Demo public: chỉ bộ mẫu synthetic có sẵn, KHÔNG upload, KHÔNG gọi model (spec mục 10).
    streamlit run app.py
"""

from __future__ import annotations

import json
import re
import time

import streamlit as st

from loanpipe import review as rv
from loanpipe.extract.vlm import FIELD_HINT

DOC_NAMES = {"cccd": "CCCD", "don_vay": "Đơn vay", "hdld": "HĐLĐ", "sao_ke": "Sao kê"}
ROUTE_STYLE = {"AUTO_PASS": ("✅", st.success, "Tự duyệt"), "REVIEW": ("🟠", st.warning, "Cần rà soát"),
               "REQUEST_MORE": ("🔴", st.error, "Cần bổ sung giấy tờ")}
STATUS_ICON = {"pass": "✅", "fail": "❌", "unknown": "❓"}
# Mã trong trace -> câu người rà soát đọc được. Mã gốc vẫn nằm trong trace/SQLite.
RULE_FAIL = {"R0": "Thiếu hoặc không đọc được giấy tờ", "R1": "Họ tên lệch giữa các giấy tờ",
             "R2": "Số CCCD lệch", "R3": "Ngày sinh lệch", "R4": "Thu nhập khai cao hơn sao kê",
             "R5": "CCCD hết hạn", "R6": "Số TK nhận lương lệch", "R7": "HĐLĐ hết hiệu lực",
             "R8": "Sao kê quá cũ hoặc thiếu tháng"}
RULE_NAME = {"R0": "đủ giấy tờ", "R1": "họ tên", "R2": "số CCCD", "R3": "ngày sinh", "R4": "thu nhập",
             "R5": "hạn CCCD", "R6": "số TK nhận lương", "R7": "hiệu lực HĐLĐ", "R8": "sao kê"}
REASON_KIND = {"LOW_CONF": "Đọc chưa chắc", "GARBLED": "Chữ đọc bị lỗi", "FORMAT": "Sai định dạng"}
REF = re.compile(r"\b(cccd|don_vay|hdld|sao_ke)(?:\.(\w+))?(=?)")

st.set_page_config(page_title="Rà soát hồ sơ vay", page_icon="📄", layout="wide")
meta, entries, traces = st.cache_data(rv.load_samples)()
con = st.cache_resource(rv.connect)()
by_id = {e["bundle_id"]: e for e in entries}


def field_label(name: str) -> str:
    h = "giao dịch" if name == "giao_dich" else FIELD_HINT.get(name, name).split(" (")[0]
    return h[0].upper() + h[1:]


def readable(text: str) -> str:
    """'cccd.ngay_het_han=2028-01-01' -> 'CCCD › Có giá trị đến / ngày hết hạn = 2028-01-01'."""
    return REF.sub(lambda m: DOC_NAMES[m[1]] + (f" › {field_label(m[2])}" if m[2] else "")
                   + (" = " if m[3] else ""), text)


def reason_text(r: str) -> str:
    kind, _, ref = r.partition(":")
    if not ref:
        return RULE_FAIL.get(r, r)
    if kind == "UNKNOWN":
        return f"Chưa kiểm được {RULE_NAME.get(ref, ref)}"
    return f"{REASON_KIND.get(kind, kind)}: {readable(ref)}"


def check_text(c: dict) -> str:
    """Một dòng mô tả kết quả rule. Message gốc mở đầu bằng tên phép kiểm ('HĐLĐ còn hiệu lực: ...') cả khi
    fail, nên khi fail thay phần đó bằng câu nói rõ lỗi."""
    if c["status"] == "fail":
        return f"{RULE_FAIL[c['rule_id']]} — " + readable(re.sub(r"^[^:=\d]+: ", "", c["message"]))
    msg = readable(c["message"])
    return f"Chưa kiểm được {RULE_NAME[c['rule_id']]} — {msg}" if c["status"] == "unknown" else msg


def dur(seconds: float) -> str:
    return f"{seconds / 60:.1f} phút" if seconds >= 60 else f"{seconds:.0f} giây"


def flagged_fields(trace: dict) -> dict[tuple[str, str], list[str]]:
    """(doc_type, field) -> lý do: evidence của rule fail/unknown + field confidence thấp / lỗi / chữ rác."""
    out: dict[tuple[str, str], list[str]] = {}
    for c in trace["checks"]:
        if c["status"] != "pass":
            for ev in c["evidence"]:  # rule unknown: chỉ tô field chưa biết, không tô field đã chắc
                if "field" in ev and (c["status"] == "fail" or not ev.get("known", True)):
                    out.setdefault((ev["doc_type"], ev["field"]), []).append(
                        f"{c['rule_id']} · {check_text(c)}")
    for r in trace["decision"]["reasons"]:
        if ":" in r and "." in r:
            kind, ref = r.split(":", 1)
            out.setdefault(tuple(ref.split(".", 1)), []).append(REASON_KIND.get(kind, kind))
    return out


def show(v) -> str:
    return "" if v is None else v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


# --- Sidebar: hàng đợi --------------------------------------------------------------------------
with st.sidebar:
    st.header("Hàng đợi rà soát")
    show_auto = st.toggle("Hiện cả bộ tự duyệt", value=False)
    done = rv.items(con)
    need = [b for b, t in traces.items() if t["decision"]["route"] != "AUTO_PASS"]
    queue = list(traces) if show_auto else need
    closed = [d for d in done.values() if d["status"] == "closed"]
    avg = f" · TB {dur(sum(d['closed_at'] - d['opened_at'] for d in closed) / len(closed))}/bộ" if closed else ""
    st.progress(min(len(closed) / len(need), 1.0), text=f"Đã chốt {len(closed)}/{len(need)}{avg}")

    def label(b: str) -> str:
        d = traces[b]["decision"]
        mark = "☑️ " if done.get(b, {}).get("status") == "closed" else ""
        rs = [reason_text(r) for r in d["reasons"]]
        why = rs[0] + (f" (+{len(rs) - 1})" if len(rs) > 1 else "") if rs else "tự duyệt"
        return f"{mark}{ROUTE_STYLE[d['route']][0]} {b} · {why}"

    bid = st.radio("Bộ hồ sơ", queue, format_func=label, label_visibility="collapsed", key="bundle")
    st.caption(f"Kết quả trích xuất chạy sẵn bằng `{meta['model']}`, prompt {meta['prompt_version']}, "
               f"{meta['rules_version']}.")

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
by_rule = {c["rule_id"]: c for c in t["checks"]}


def detail(r: str) -> str:
    c = by_rule.get(r.split(":")[-1])
    return check_text(c) if c else reason_text(r)


icon, box, route_name = ROUTE_STYLE[dec["route"]]
box(f"**{bid} · {route_name}**" + "".join(f"\n- {detail(r)}" for r in dec["reasons"]))

n_pass = sum(c["status"] == "pass" for c in t["checks"])
with st.expander(f"Chi tiết {len(t['checks'])} rule · {n_pass} đạt"):
    for c in t["checks"]:
        st.markdown(f"{STATUS_ICON[c['status']]} **{c['rule_id']}** {check_text(c)}")

flags = flagged_fields(t)
edits: dict[str, dict] = {}
ext = {x["doc_type"]: x for x in t["extractions"]}
tab_names = [DOC_NAMES[d["type"]] + (" ⚠️" if any(k[0] == d["type"] for k in flags) else "") for d in e["docs"]]
# Mở sẵn giấy tờ đầu tiên bị gắn cờ: người rà soát không phải đi tìm
tabs = st.tabs(tab_names, default=next((n for n in tab_names if n.endswith("⚠️")), None), key=f"tabs/{bid}")
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
                if name == "giao_dich":  # ponytail: bảng giao dịch chỉ xem, sửa từng dòng khi có nhu cầu thật
                    rows = fld["value"]
                    if rows is None and fld["raw"]:  # đọc ra nhưng không hợp lệ: vẫn cho xem model đã chép gì
                        try:
                            rows = json.loads(fld["raw"])
                        except ValueError:
                            rows = None
                    st.markdown(f"{'⚠️ ' if why else ''}**{field_label(name)}**")
                    st.dataframe(rows or [], width="stretch", height=220)
                    if fld["error"]:
                        st.caption(f"Lỗi: {fld['error']}")
                else:
                    new = st.text_input(f"{'⚠️ ' if why else ''}{field_label(name)}", show(fld["value"]),
                                        key=f"{bid}/{d['type']}/{name}",
                                        help=f"Chép từ ảnh: {fld['raw']!r} · confidence {fld['confidence']}"
                                             + (f" · lỗi: {fld['error']}" if fld["error"] else ""))
                    if new != show(fld["value"]):
                        edits[f"{d['type']}.{name}"] = {"from": show(fld["value"]), "to": new}
                if why:
                    st.caption("🟠 " + "; ".join(why))

st.divider()
if dec["route"] == "AUTO_PASS":
    st.info("Bộ này đã tự duyệt: qua hết 9 rule, mọi field quan trọng confidence cao. Không vào hàng đợi.")
else:
    row = rv.items(con).get(bid, {})
    if row.get("status") == "closed":
        st.success(f"Đã chốt: **{rv.CONCLUSIONS[row['conclusion']]}** bởi {row['reviewer']} sau "
                   f"{dur(row['closed_at'] - row['opened_at'])}. Sửa: {row['edits']}")
    with st.form(f"close/{bid}"):
        st.subheader("Kết luận")
        if edits:
            st.write("Field đã sửa:", edits)
        reviewer = st.text_input("Người rà soát", value=row.get("reviewer") or st.session_state.get("reviewer", ""))
        options = list(rv.CONCLUSIONS)
        conclusion = st.radio("Kết luận", options, format_func=rv.CONCLUSIONS.get, horizontal=True,
                              index=options.index(row["conclusion"]) if row.get("conclusion") else None)
        note = st.text_area("Ghi chú", value=row.get("note") or "")
        if st.form_submit_button("Chốt hồ sơ", type="primary"):
            if not reviewer.strip():
                st.error("Nhập tên người rà soát.")
            elif conclusion is None:  # không chọn sẵn: duyệt hồ sơ phải là một thao tác có chủ đích
                st.error("Chọn kết luận.")
            else:
                st.session_state["reviewer"] = reviewer.strip()
                rv.close_item(con, bid, reviewer.strip(), conclusion, edits, note)
                st.rerun()
    if row.get("opened_at"):
        st.caption(f"Mở lúc {time.strftime('%H:%M:%S', time.localtime(row['opened_at']))}")

with st.expander("Nhãn thật (chỉ có vì dữ liệu tổng hợp)"):
    st.write({"route đúng": e["expected_route"], "lỗi cài vào": e["injected_errors"],
              "near-miss": e["near_miss"], "mức ảnh": e["augment"], "layout": e["layout_ids"]})
