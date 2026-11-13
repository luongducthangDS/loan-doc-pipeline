"""Review UI (spec mục 8), giao diện back-office kiểu ngân hàng: hàng đợi -> chi tiết một bộ (ảnh gốc cạnh
field đã trích, field bị gắn cờ tô sáng kèm evidence) -> reviewer sửa field rồi chốt 1 trong 3 kết luận.
Điều hướng bằng query param `?bundle=<id>`, nên mỗi dòng trong bảng là link thường.

Demo public: chỉ bộ mẫu synthetic có sẵn, KHÔNG upload, KHÔNG gọi model (spec mục 10).
    streamlit run app.py
"""

from __future__ import annotations

import hmac
import json
import os
import re
import time
from collections import Counter
from html import escape as esc
from urllib.parse import quote

import streamlit as st

from loanpipe import review as rv
from loanpipe.normalize import names_match

DOC_NAMES = {"cccd": "CCCD", "don_vay": "Đơn vay", "hdld": "HĐLĐ", "sao_ke": "Sao kê"}
FIELD_LABEL = {
    "so_cccd": "Số CCCD", "ho_ten": "Họ và tên", "ngay_sinh": "Ngày sinh", "gioi_tinh": "Giới tính",
    "que_quan": "Quê quán", "noi_thuong_tru": "Nơi thường trú", "ngay_cap": "Ngày cấp",
    "ngay_het_han": "Có giá trị đến", "so_dien_thoai": "Số điện thoại", "dia_chi": "Địa chỉ",
    "ten_cong_ty": "Tên công ty", "thu_nhap_thang": "Thu nhập mỗi tháng", "so_tien_vay": "Số tiền đề nghị vay",
    "thoi_han_thang": "Thời hạn vay (tháng)", "muc_dich": "Mục đích vay", "so_tk_nhan_luong": "Số TK nhận lương",
    "ngay_ky": "Ngày ký đơn", "ho_ten_nld": "Họ tên người lao động", "chuc_danh": "Chức danh",
    "loai_hd": "Loại hợp đồng", "ngay_bat_dau": "Ngày bắt đầu", "ngay_ket_thuc": "Ngày kết thúc",
    "muc_luong": "Mức lương", "chu_tk": "Chủ tài khoản", "so_tk": "Số tài khoản", "ky_tu": "Sao kê từ ngày",
    "ky_den": "Sao kê đến ngày", "giao_dich": "Giao dịch",
}
RULES = {  # rule_id -> (điều kiện đạt, nhãn khi không đạt, tên ngắn); con số chi tiết lấy từ message trong trace
    "R0": ("Đủ 4 giấy tờ, đọc được", "Thiếu hoặc không đọc được giấy tờ", "đủ giấy tờ"),
    "R1": ("Họ tên khớp giữa các giấy tờ", "Họ tên lệch", "họ tên"),
    "R2": ("Số CCCD khớp", "Số CCCD lệch", "số CCCD"),
    "R3": ("Ngày sinh khớp", "Ngày sinh lệch", "ngày sinh"),
    "R4": ("Thu nhập khai khớp lương sao kê", "Thu nhập khai vượt lương sao kê", "thu nhập"),
    "R5": ("CCCD còn hạn tại ngày ký", "CCCD hết hạn", "hạn CCCD"),
    "R6": ("Số TK nhận lương khớp sao kê", "Số TK nhận lương lệch", "số TK nhận lương"),
    "R7": ("HĐLĐ còn hiệu lực tại ngày ký", "HĐLĐ hết hiệu lực", "hiệu lực HĐLĐ"),
    "R8": ("Sao kê đủ kỳ, gần ngày ký", "Sao kê thiếu kỳ hoặc quá cũ", "sao kê"),
}
REF = re.compile(r"\b(cccd|don_vay|hdld|sao_ke)\.(\w+)(=?)")
MATCH_RULES = {"R1", "R2", "R3", "R6"}  # rule so khớp: giá trị ở giấy tờ kia là gợi ý sửa hợp lệ
FIELD_REASON = {"LOW_CONF": (None, "tin cậy thấp"), "GARBLED": ("OCR", "đọc không rõ"),
                "FORMAT": ("ĐD", "sai định dạng")}  # kind -> (pill trong bảng, mô tả)
ROUTE = {"AUTO_PASS": ("auto", "Tự duyệt"), "REVIEW": ("review", "Cần rà soát"),
         "REQUEST_MORE": ("more", "Yêu cầu bổ sung")}
AUGMENT = {"clean": "Bản gốc", "scan": "Bản scan", "photo": "Ảnh chụp"}
CONF = {"high": "cao", "low": "thấp"}


ICONS = {  # icon nét, vẽ bằng CSS mask vì st.html lọc bỏ thẻ <svg>. name -> (paths, stroke-width)
    "warn": ('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
             '<path d="M12 9v4"/><path d="M12 17h.01"/>', 2),
    "check": ('<path d="M20 6 9 17l-5-5"/>', 3.5), "x": ('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>', 3.5),
    "left": ('<path d="m15 18-6-6 6-6"/>', 2), "right": ('<path d="m9 18 6-6-6-6"/>', 2),
    "queue": ('<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 '
              '2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M9 12h6"/><path d="M9 16h4"/>', 1.8),
    "more": ('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>'
             '<path d="M12 18v-6"/><path d="M9 15h6"/>', 1.8),
    "auto": ('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>', 1.8),
    "clock": ('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 1.8),
}
ICON_CSS = "".join(
    f'.i-{k}{{-webkit-mask-image:url("data:image/svg+xml,{u}");mask-image:url("data:image/svg+xml,{u}")}}'
    for k, (paths, w) in ICONS.items()
    for u in [quote(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" '
                    f'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')])


def ico(name: str) -> str:
    return f'<i class="ico i-{name}"></i>'


CSS = """<style>
.ico{display:inline-block;flex-shrink:0;width:16px;height:16px;background:currentColor;-webkit-mask-repeat:no-repeat;
  mask-repeat:no-repeat;-webkit-mask-size:contain;mask-size:contain}
.ic .ico{width:20px;height:20px}.rl .i .ico{width:12px;height:12px}
header[data-testid="stHeader"]{display:none}
.block-container,[data-testid="stMainBlockContainer"]{padding:0 2rem 2rem;max-width:none}
.stApp{font-variant-numeric:tabular-nums}
.stApp a{color:#1B4F9C;text-decoration:none}.stApp a:hover{color:#0E3470;text-decoration:underline}
.mono{font-family:'IBM Plex Mono',monospace}
.tb{display:flex;align-items:center;gap:40px;height:64px;margin:0 -2rem;padding:0 2rem;background:#0B1F3A;color:#fff}
.tb .brand{display:flex;align-items:center;gap:12px}
.tb .mark{width:36px;height:36px;box-sizing:border-box;border:1.5px solid #C9A45C;border-radius:8px;display:flex;
  align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#E9D5A7}
.tb .brand b{display:block;font-size:15px;font-weight:600}.tb .brand small{display:block;font-size:11.5px;color:#A9B8CF}
.tb nav{display:flex;align-self:stretch}
.stApp .tb nav a{display:flex;align-items:center;padding:0 14px;font-size:14px;font-weight:500;color:#C9D4E5;
  border-bottom:2px solid transparent;text-decoration:none;transition:color .15s,border-color .15s}
.stApp .tb nav a:hover{color:#fff;text-decoration:none}
.stApp .tb nav a.on{color:#fff;font-weight:600;border-bottom-color:#C9A45C}
.stApp a:focus-visible,.stApp .btn:focus-visible{outline:2px solid #C9A45C;outline-offset:2px;border-radius:4px}
.qt:not(.head){transition:background .12s}.qt:not(.head):hover{background:#F7F9FC}
.qwrap{overflow-x:auto;margin:0 -20px}.qwrap>.qt{min-width:1040px;margin:0}
/* Tổng quan */
.hero{margin:24px 0 8px;padding:32px 36px;border-radius:12px;color:#fff;
  background:linear-gradient(135deg,#0B1F3A 0%,#1B3A66 60%,#24508A 100%)}
.stApp .hero h1{margin:6px 0 10px;padding:0;font-size:30px;font-weight:700;letter-spacing:-.3px;color:#fff}
.hero p{max-width:760px;margin:0;font-size:15px;line-height:1.6;color:#D5DEEB}
.hero .eyebrow{font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#E9D5A7}
.hero .cta{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}
.stApp .hero .btn.primary{background:#C9A45C;color:#0B1F3A}.stApp .hero .btn.sec{background:transparent;color:#fff;border-color:#4D6588}
.sec-t{margin:28px 0 12px;font-size:17px;font-weight:600;color:#0B1F3A}
.flow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.step{position:relative;background:#fff;border:1px solid #DCE2EA;border-radius:10px;padding:18px 20px}
.step .n{display:inline-flex;width:26px;height:26px;border-radius:50%;align-items:center;justify-content:center;
  background:#E6EDF7;color:#1B3A66;font-size:12.5px;font-weight:700}
.step b{display:block;margin:10px 0 6px;font-size:15px;color:#0B1F3A}.step p{margin:0;font-size:13px;line-height:1.55;color:#4A5566}
.step:not(:last-child)::after{content:"→";position:absolute;right:-14px;top:50%;transform:translateY(-50%);
  color:#9AA5B4;font-weight:700}
.tbl{width:100%;border-collapse:collapse;background:#fff;border:1px solid #DCE2EA;border-radius:8px;overflow:hidden;font-size:13.5px}
.tbl th{background:#F6F8FA;text-align:left;font-size:12px;font-weight:600;color:#4A5566;padding:10px 14px;border-bottom:1px solid #DCE2EA}
.tbl td{padding:10px 14px;border-bottom:1px solid #EBEEF2}.tbl tr:last-child td{border-bottom:0}
.tbl td.n,.tbl th.n{text-align:right}.tbl tr.base td{background:#F3F7FD;font-weight:600}
.twrap{overflow-x:auto}.rgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.rgrid div{display:flex;gap:10px;align-items:center;background:#fff;border:1px solid #DCE2EA;border-radius:8px;
  padding:10px 14px;font-size:13px}
.foot{margin-top:28px;font-size:12.5px;color:#5A6678}
/* Màn hẹp: lưới co lại, bảng cuộn ngang thay vì vỡ cột */
/* .stApp tiền tố: Streamlit có thể chèn lại rule gốc sau media query, cần độ ưu tiên cao hơn */
@media (max-width:1100px){.stApp .kpis,.stApp .flow{grid-template-columns:repeat(2,minmax(0,1fr))}
  .stApp .step:not(:last-child)::after{display:none}.stApp .rgrid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .stApp .facts{flex-wrap:wrap;row-gap:10px}.stApp .ph{flex-wrap:wrap;align-items:flex-start}}
@media (max-width:640px){.stApp .block-container,.stApp [data-testid="stMainBlockContainer"]{padding:0 1rem 1.5rem}
  .stApp .tb,.stApp .note,.stApp .case,.stApp .st-key-decision{margin:0 -1rem;padding-left:1rem;padding-right:1rem}
  .stApp .tb{gap:12px}.stApp .tb .env,.stApp .tb .brand small,.stApp .tb .brand b{display:none}
  .stApp .tb nav a{padding:0 8px;font-size:13px}
  .stApp .kpis,.stApp .flow,.stApp .rgrid{grid-template-columns:minmax(0,1fr)}
  .stApp .hero{padding:24px 20px}.stApp .hero h1{font-size:24px}.stApp .case .row{flex-wrap:wrap}
  .stApp [data-testid="stLayoutWrapper"]:has(> .st-key-decision){position:static}}
.tb .env{margin-left:auto;padding:5px 10px;border:1px solid #4D6588;border-radius:4px;font-size:11px;font-weight:600;
  letter-spacing:.6px;color:#DCE4EF}
.note{display:flex;align-items:center;gap:10px;min-height:36px;margin:0 -2rem;padding:0 2rem;background:#FFF6E3;
  border-bottom:1px solid #EFD7A6;font-size:12.5px;color:#5E3B00}
.ph{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;margin-top:8px}
.crumb{font-size:12.5px;color:#5A6678}
.stApp .ph h1{margin:4px 0;padding:0;font-size:26px;font-weight:600;letter-spacing:-.2px;color:#0B1F3A}
.meta{font-size:13px;color:#4A5566}
.stApp .btn{height:44px;box-sizing:border-box;padding:0 18px;display:inline-flex;align-items:center;gap:6px;
  border-radius:6px;font-size:14px;text-decoration:none}
.stApp .btn.primary{background:#1B3A66;color:#fff;font-weight:600}
.stApp .btn.sec{background:#fff;border:1px solid #C3CCD8;color:#1B2A3F;font-weight:500}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-top:4px}
.kpi{background:#fff;border:1px solid #DCE2EA;border-radius:8px;padding:18px 20px;display:flex;justify-content:space-between}
.kpi span{display:block}.kpi .l{font-size:13px;font-weight:500;color:#4A5566}
.kpi .v{font-size:32px;font-weight:600;line-height:1.15;margin:6px 0;color:#0B1F3A}
.kpi .v small{font-size:18px;font-weight:500;color:#5A6678}.kpi .s{font-size:12.5px;color:#5A6678}
.ic{flex-shrink:0;width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center}
.ic.review{background:#FDF0D9;color:#8A4B00}.ic.more{background:#FBE7E7;color:#9B1C1C}
.ic.auto{background:#E3F1E8;color:#0E6B3A}.ic.done{background:#E6EDF7;color:#1B3A66}
[class*="st-key-card"]{background:#fff;border:1px solid #DCE2EA;border-radius:8px;padding:12px 20px}
.qt{display:grid;grid-template-columns:112px minmax(0,1fr) 150px 150px minmax(0,1.6fr) 104px 140px 72px;
  column-gap:12px;align-items:center;min-height:56px;margin:0 -20px;padding:0 20px;border-bottom:1px solid #EBEEF2;
  font-size:13.5px;color:#16202E}
.qt.head{min-height:40px;background:#F6F8FA;border-top:1px solid #DCE2EA;border-bottom-color:#DCE2EA;font-size:12px;
  font-weight:600;color:#4A5566}
.qt.open{background:#F3F7FD}
.qt .nm{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qt .amt{display:flex;flex-direction:column;align-items:flex-end}.qt .amt b{font-weight:600}
.qt .amt small,.qt .r{font-size:12px;color:#5A6678}.qt .r{text-align:right}
.qt .why{display:flex;align-items:center;gap:8px;min-width:0;font-size:13px;color:#3D4859}
.qt .why .t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qt .act{justify-self:end;font-size:13px;font-weight:600}
.qempty{padding:28px 0;text-align:center;color:#5A6678;font-size:13.5px}
.qfoot{display:flex;justify-content:space-between;align-items:center;min-height:40px;font-size:13px;color:#4A5566}
.chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:12.5px;
  font-weight:600;white-space:nowrap}
.chip::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--dot)}
.chip.review{background:#FDF0D9;color:#7A4300;--dot:#D98A1C}.chip.more{background:#FBE7E7;color:#9B1C1C;--dot:#C8322F}
.chip.auto{background:#E3F1E8;color:#0E6B3A;--dot:#2E7D4F}
.pill{flex-shrink:0;padding:2px 7px;border-radius:4px;border:1px solid;font-size:11.5px;font-weight:600;white-space:nowrap}
.pill.fail{background:#FBE9E9;color:#9B1C1C;border-color:#F2C4C4}
.pill.unknown{background:#F1F3F6;color:#3F4B5C;border-color:#C9D1DC}
.pill.field{background:#FFF3DC;color:#7A4A00;border-color:#EDCF94}
.sd{display:flex;align-items:center;gap:8px;font-size:13px;color:#3D4859}
.sd::before{content:"";width:8px;height:8px;border-radius:50%;background:#9AA5B4}
.sd.open::before{background:#1B4F9C}.sd.closed::before{background:#2E7D4F}
.case{display:flex;flex-direction:column;gap:14px;margin:0 -2rem;padding:16px 2rem 18px;background:#fff;
  border-bottom:1px solid #DCE2EA}
.case .row{display:flex;justify-content:space-between;align-items:center;gap:24px}
.case .who{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.stApp .case h1{margin:0;padding:0;font-size:24px;font-weight:600;color:#0B1F3A}
.idtag{padding:3px 8px;border-radius:4px;background:#EEF1F5;font-size:12.5px;color:#3D4859}
.failsum{font-size:13px;font-weight:500;color:#9B1C1C}.failsum.ok{color:#0E6B3A}
.case .nav{display:flex;gap:10px}
.facts{display:flex;border:1px solid #E3E8EF;border-radius:8px;padding:12px 0}
.facts div{flex:0 0 auto;padding:0 20px;border-left:1px solid #E3E8EF}.facts div:first-child{border-left:0}
.facts div.grow{flex:1 1 0;min-width:0}
.facts span{display:block;font-size:12px;color:#5A6678}
.facts b{display:block;font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rules{background:#fff;border:1px solid #DCE2EA;border-radius:8px;overflow:hidden}
.rules .h{padding:14px 16px 12px;border-bottom:1px solid #DCE2EA}
.rules .h .top{display:flex;justify-content:space-between;align-items:baseline}
.stApp .rules h3,.stApp .cardh h3{margin:0;padding:0;font-size:15px;font-weight:600;color:#0B1F3A}
.bar{display:flex;gap:2px;height:6px;border-radius:3px;overflow:hidden;margin:10px 0}
.bar .p{background:#2E7D4F}.bar .f{background:#C8322F}.bar .u{background:#9AA5B4}
.sum{font-size:12.5px;color:#3D4859}.sum b.p{color:#0E6B3A}.sum b.f{color:#9B1C1C}
.rl{padding:9px 16px;border-bottom:1px solid #EBEEF2}.rl:last-child{border-bottom:0}
.rl .t{display:flex;align-items:center;gap:10px;font-size:13px}
.rl .i{flex-shrink:0;width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:12px;font-weight:700}
.rl .id{flex-shrink:0;width:22px;font-size:12px;font-weight:600;color:#3D4859}
.rl.pass .i{background:#E3F1E8;color:#0E6B3A}
.rl.fail{background:#FDF6F6}.rl.fail .i{background:#C8322F;color:#fff}.rl.fail .t b{font-weight:600}
.rl.unknown{background:#F7F8FA}.rl.unknown .i{background:#E1E6ED;color:#3F4B5C}
.rl .msg{margin:6px 0 0 30px;padding:8px 10px;border-radius:6px;background:#fff;border:1px solid #F2C4C4;
  font-size:12.5px;line-height:1.45;color:#5C1414;overflow-wrap:anywhere}
.rl.unknown .msg{border-color:#C9D1DC;color:#3D4859}
[class*="st-key-viewer"]{background:#E4E8EE;border-radius:8px;padding:16px}
[class*="st-key-viewer"] img{border-radius:4px;box-shadow:0 1px 3px rgba(11,31,58,.18)}
.cardh{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 -20px;padding:2px 20px 12px;
  border-bottom:1px solid #DCE2EA}
.cardh small{display:block;font-size:12px;color:#5A6678}
[class*="st-key-flag-"]{background:#FFF8EC;border:1px solid #EDCF94;border-radius:8px;padding:12px;gap:8px}
[class*="st-key-flag-"] [data-baseweb="input"]{border:1.5px solid #D98A1C}
.fh{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;
  font-weight:600;color:#5C3A00}
.fh .pills{display:flex;gap:6px;flex-wrap:wrap}
.cmp{display:grid;grid-template-columns:auto minmax(0,1fr);column-gap:12px;row-gap:3px;font-size:12.5px;color:#16202E}
.cmp span:nth-child(odd){color:#5A6678}
[data-testid="stLayoutWrapper"]:has(> .st-key-decision){position:sticky;bottom:0;z-index:20}
.st-key-decision{margin:0 -2rem;padding:14px 2rem 16px;background:#fff;border-top:1px solid #DCE2EA;
  box-shadow:0 -4px 12px rgba(11,31,58,.06)}
.st-key-decision [role="radiogroup"]{gap:8px}
.st-key-decision [role="radiogroup"] label{min-height:44px;box-sizing:border-box;margin:0;padding:0 12px;
  border:1px solid #C3CCD8;border-radius:6px;align-items:center}
.st-key-decision [role="radiogroup"] label:has(input:checked){border:1.5px solid #1B3A66;background:#F2F5FA}
</style>"""


def fields(t: dict, doc: str) -> dict:
    return next((x["fields"] for x in t["extractions"] if x["doc_type"] == doc), {})


def val(t: dict, doc: str, name: str):
    return (fields(t, doc).get(name) or {}).get("value")


def show(v) -> str:
    return "" if v is None else v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def money(v) -> str:
    return f"{v:,.0f}".replace(",", ".") + " ₫" if isinstance(v, (int, float)) else "—"


def vdate(v) -> str:
    return "/".join(reversed(v.split("-"))) if isinstance(v, str) and len(v) == 10 and v[4] == "-" else show(v) or "—"


def dur(seconds: float) -> str:
    return f"{seconds / 60:.1f} phút" if seconds >= 60 else f"{seconds:.0f} giây"


def customer(t: dict) -> str:
    return val(t, "don_vay", "ho_ten") or val(t, "cccd", "ho_ten") or "—"


def chip(route: str) -> str:
    cls, label = ROUTE[route]
    return f'<span class="chip {cls}">{label}</span>'


def reason_html(reasons: list[str]) -> str:
    """Lý do route -> pill mã rule + một dòng mô tả cho bảng hàng đợi."""
    pills, texts = [], []
    for r in reasons:
        kind, _, ref = r.partition(":")
        if not ref:  # rule fail: "R1"
            pills.append(("fail", kind))
            texts.append(RULES.get(kind, ("", kind))[1])
        elif kind == "AGENT":  # agent chọn nhánh chặt hơn router
            pills.append(("unknown", "AI"))
            texts.append(f"Agent chuyển sang {ROUTE.get(ref, ('', ref))[1]}")
        elif kind == "UNKNOWN":
            pills.append(("unknown", f"{ref}?"))
            texts.append(f"Chưa kiểm được {RULES.get(ref, ('', '', ref))[2]}")
        else:  # LOW_CONF / GARBLED / FORMAT : doc.field
            doc, _, name = ref.partition(".")
            pill, what = FIELD_REASON.get(kind, (kind, ""))
            if pill:
                pills.append(("field", pill))
            texts.append(f"{FIELD_LABEL.get(name, name)} ({DOC_NAMES.get(doc, doc)}) {what}")
    text = "; ".join(texts) or ("Chưa đủ căn cứ để tự duyệt" if reasons else "Qua hết kiểm tra")
    return "".join(f'<span class="pill mono {k}">{esc(p)}</span>' for k, p in pills) + \
        f'<span class="t" title="{esc(text)}">{esc(text)}</span>'


def flagged_fields(trace: dict) -> dict[tuple[str, str], dict]:
    """(doc_type, field) -> {"why": [(loại pill, nhãn)], "peers": [(doc_type, field, value)], "suggest": {value: doc}}:
    evidence của rule fail/unknown + field confidence thấp / lỗi / chữ rác. peers = giá trị cùng rule ở giấy tờ khác
    để đối chiếu; suggest = giá trị nên lấy khi rule so khớp fail (bên kia nếu chỉ 2 giấy tờ, số đông nếu nhiều hơn)."""
    out: dict[tuple[str, str], dict] = {}

    def slot(key: tuple[str, str]) -> dict:
        return out.setdefault(key, {"why": [], "peers": [], "suggest": {}})

    for c in trace["checks"]:
        if c["status"] == "pass":
            continue
        refs = [ev for ev in c["evidence"] if "field" in ev]
        same = names_match if c["rule_id"] == "R1" else str.__eq__  # R1: tên không dấu ở sao kê vẫn là khớp
        top, n_top = (Counter(show(o.get("value")) for o in refs if o.get("value") is not None).most_common(1)
                      or [(None, 0)])[0]
        for ev in refs:  # rule unknown: chỉ tô field chưa biết, không tô field đã chắc
            if c["status"] == "fail" or not ev.get("known", True):
                f = slot((ev["doc_type"], ev["field"]))
                f["why"].append(("fail", f"{c['rule_id']} · {RULES[c['rule_id']][1]}") if c["status"] == "fail"
                                else ("unknown", f"{c['rule_id']} · chưa đủ căn cứ"))
                others = [o for o in refs if o is not ev]
                f["peers"] += [(o["doc_type"], o["field"], o.get("value")) for o in others]
                if c["status"] == "fail" and c["rule_id"] in MATCH_RULES and ev.get("value") is not None:
                    for o in others:
                        v = show(o.get("value"))
                        if (o.get("value") is not None and not same(show(ev["value"]), v)
                                and (len(refs) == 2 or (v == top and n_top >= 2))):
                            f["suggest"].setdefault(v, o["doc_type"])
    for r in trace["decision"]["reasons"]:
        kind, _, ref = r.partition(":")
        if "." in ref:
            f = slot(tuple(ref.split(".", 1)))
            f["why"].append(("field", FIELD_REASON.get(kind, (None, kind))[1].capitalize()))
    return out


# --- Khung trang --------------------------------------------------------------------------------
st.set_page_config(page_title="Thẩm định hồ sơ vay", page_icon="📄", layout="wide",
                   initial_sidebar_state="collapsed")
# ponytail: một mật khẩu chung cho cả demo; triển khai thật dùng SSO (st.login/OIDC) và phân quyền theo người duyệt
if (pw := os.environ.get("DEMO_PASSWORD")) and not st.session_state.get("authed"):
    entered = st.text_input("Mật khẩu", type="password")
    if entered and hmac.compare_digest(entered, pw):
        st.session_state["authed"] = True
        st.rerun()
    if entered:
        st.error("Sai mật khẩu")
    st.stop()
meta, entries, traces = st.cache_data(rv.load_samples)()
con = st.cache_resource(rv.connect)()
by_id = {e["bundle_id"]: e for e in entries}
model = meta["model"].split("/")[-1].split("@")[0]

page = "overview" if st.query_params.get("page") == "overview" else "queue"
on = {p: ' class="on" aria-current="page"' if p == page else "" for p in ("queue", "overview")}
st.html(f"<style>{ICON_CSS}</style>" + CSS + f"""
<div class="tb"><div class="brand"><div class="mark">TĐ</div><div><b>Thẩm định Hồ sơ Vay</b>
<small>Tín dụng tiêu dùng cá nhân</small></div></div><nav aria-label="Điều hướng chính"><a href="?"{on['queue']}>Hàng đợi</a>
<a href="?page=overview"{on['overview']}>Tổng quan pipeline</a></nav>
<span class="env">DEMO · DỮ LIỆU TỔNG HỢP</span></div>
<div class="note">{ico("warn")}<span><b>MẪU – DỮ LIỆU TỔNG HỢP.</b> Tên người, công ty, ngân hàng đều hư cấu. Demo không
upload, không gọi model; ngưỡng rule là giả định cho demo, không phải chính sách tín dụng.</span></div>""")


def queue_view() -> None:
    done = rv.items(con)
    routes = {b: t["decision"]["route"] for b, t in traces.items()}
    n = Counter(routes.values())
    in_queue = [b for b in traces if routes[b] != "AUTO_PASS"]
    closed = [d for d in done.values() if d["status"] == "closed"]
    avg = dur(sum(d["closed_at"] - d["opened_at"] for d in closed) / len(closed)) if closed else "—"
    nxt = next((b for b in in_queue if done.get(b, {}).get("status") != "closed"), None)
    kpi = [("Chờ rà soát", n["REVIEW"], "rule không đạt hoặc chưa đủ căn cứ", "review", ico("queue")),
           ("Yêu cầu bổ sung", n["REQUEST_MORE"], "thiếu hoặc không đọc được giấy tờ", "more", ico("more")),
           ("Tự duyệt", n["AUTO_PASS"], "qua mọi rule, field quan trọng tin cậy cao", "auto", ico("auto")),
           ("Đã chốt", f"{len(closed)}<small> / {len(in_queue)}</small>", f"thời gian TB mỗi hồ sơ: {avg}",
            "done", ico("clock"))]
    st.html(f"""<div class="ph"><div><div class="crumb">Tín dụng tiêu dùng / Hàng đợi rà soát</div>
<h1>Hàng đợi rà soát</h1><div class="meta">Lô {esc(meta['split'])} · {len(traces)} hồ sơ · trích xuất
<span class="mono">{esc(model)}</span> (prompt {esc(meta['prompt_version'])}) ·
<span class="mono">{esc(meta['rules_version'])}</span> · <span class="mono">{esc(meta['thresholds_version'])}</span>
</div></div>{f'<a class="btn primary" href="?bundle={nxt}">Nhận hồ sơ tiếp theo {ico("right")}</a>' if nxt else ''}</div>
<div class="kpis">{''.join(f'<div class="kpi"><div><span class="l">{l}</span><span class="v">{v}</span>'
                           f'<span class="s">{s}</span></div><div class="ic {c}">{i}</div></div>'
                           for l, v, s, c, i in kpi)}</div>""")

    with st.container(key="card-queue"):
        views = {"queue": ("Trong hàng đợi", len(in_queue)), "REVIEW": ("Cần rà soát", n["REVIEW"]),
                 "REQUEST_MORE": ("Yêu cầu bổ sung", n["REQUEST_MORE"]), "AUTO_PASS": ("Tự duyệt", n["AUTO_PASS"])}
        c1, c2, c3 = st.columns([2.4, 1.3, 0.7], vertical_alignment="center")
        view = c1.segmented_control("Lọc theo phân luồng", list(views), default="queue", key="view",
                                    format_func=lambda k: f"{views[k][0]} · {views[k][1]}",
                                    label_visibility="collapsed") or "queue"
        q = c2.text_input("Tìm hồ sơ", placeholder="Tìm mã hồ sơ, tên khách hàng", label_visibility="collapsed")
        aug = c3.selectbox("Chất lượng ảnh", ["Tất cả", *AUGMENT.values()], label_visibility="collapsed")
        rows = [b for b in traces
                if (routes[b] != "AUTO_PASS" if view == "queue" else routes[b] == view)
                and q.strip().casefold() in f"{b} {customer(traces[b])}".casefold()
                and aug in ("Tất cả", AUGMENT.get(by_id[b]["augment"]))]

        def row(b: str) -> str:
            t, s = traces[b], done.get(b, {}).get("status")
            cls, label = (("closed", "Đã chốt") if s == "closed" else ("open", "Đang rà soát") if s == "open"
                          else ("", "Không vào hàng đợi") if routes[b] == "AUTO_PASS" else ("", "Chưa mở"))
            term = val(t, "don_vay", "thoi_han_thang")
            return (f'<div class="qt{" open" if cls == "open" else ""}"><a class="mono" href="?bundle={b}">{b}</a>'
                    f'<span class="nm">{esc(customer(t))}</span><span class="amt"><b>{money(val(t, "don_vay", "so_tien_vay"))}'
                    f'</b><small>{f"{term} tháng" if term else "—"}</small></span><span>{chip(routes[b])}</span>'
                    f'<span class="why">{reason_html(t["decision"]["reasons"])}</span>'
                    f'<span>{AUGMENT.get(by_id[b]["augment"], "—")}</span><span class="sd {cls}">{label}</span>'
                    f'<a class="act" href="?bundle={b}">{"Xem" if cls == "closed" or routes[b] == "AUTO_PASS" else "Rà soát"}</a></div>')

        st.html('<div class="qwrap"><div class="qt head"><span>Mã hồ sơ</span><span>Khách hàng</span><span class="r">Khoản vay</span>'
                '<span>Phân luồng</span><span>Lý do gắn cờ</span><span>Chất lượng ảnh</span><span>Trạng thái</span>'
                '<span></span></div>' + ("".join(map(row, rows)) or '<div class="qempty">Không có hồ sơ khớp bộ lọc.</div>')
                + f'</div><div class="qfoot"><span>Hiển thị {len(rows)} / {len(traces)} hồ sơ · sắp xếp theo mã hồ sơ</span>'
                f'<span class="mono">run {esc(meta["run_id"][:15])} · commit {esc(meta["git_commit"])}</span></div>')


def agent_panel(ag: dict) -> None:
    """Chế độ --agent: ghi chú của agent cho người rà soát + nhật ký tool call."""
    if ag.get("note"):
        st.info(f"**Agent:** {ag['note']}")
    elif ag["finished_by"] == "fallback":
        st.warning("Agent không chốt được (hết lượt hoặc lỗi LLM); nhánh lấy theo rule.")
    with st.expander(f"Nhật ký agent · {ag['turns']} lượt · {len(ag['steps'])} bước"
                     + (f" · bị từ chối {ag['rejections']} lần" if ag["rejections"] else "")):
        for i, step in enumerate(ag["steps"], 1):
            if "thought" in step:
                st.caption(f"{i}. 💭 {step['thought']}")
                continue
            args = ", ".join(f"{k}={v}" for k, v in (step["args"] or {}).items())
            res = step["result"]
            brief = (res.get("error") or ("chấp nhận" if res.get("accepted") else None)
                     or (f"router: {res['router_route']}" if "router_route" in res else None)
                     or (f"nâng {res['upgraded']}" if res.get("upgraded") else None)
                     or ("đã đọc" if "fields" in res else "ok"))
            st.caption(f"{i}. `{step['tool']}({args})` → {brief}")


def detail_view(bid: str) -> None:
    t, e = traces[bid], by_id[bid]
    dec = t["decision"]
    if dec["route"] != "AUTO_PASS":
        rv.open_item(con, bid, dec["route"], dec["reasons"])
    order = [b for b in traces if (traces[b]["decision"]["route"] == "AUTO_PASS") == (dec["route"] == "AUTO_PASS")]
    i = order.index(bid)
    nav = (f'<a class="btn sec" href="?bundle={order[i - 1]}">{ico("left")}{order[i - 1]}</a>' if i else "") + \
        (f'<a class="btn sec" href="?bundle={order[i + 1]}">{order[i + 1]}{ico("right")}</a>' if i + 1 < len(order) else "")
    by_status = {s: [c["rule_id"] for c in t["checks"] if c["status"] == s] for s in ("pass", "fail", "unknown")}
    summary = (f'<span class="failsum">{len(by_status["fail"])} rule không đạt: {", ".join(by_status["fail"])}</span>'
               if by_status["fail"] else f'<span class="failsum">{len(by_status["unknown"])} rule chưa đủ căn cứ</span>'
               if by_status["unknown"] else f'<span class="failsum ok">Qua hết {len(t["checks"])} rule</span>')
    term, income = val(t, "don_vay", "thoi_han_thang"), val(t, "don_vay", "thu_nhap_thang")
    facts = [("Số tiền vay", money(val(t, "don_vay", "so_tien_vay")), ""),
             ("Kỳ hạn", f"{term} tháng" if term else "—", ""),
             ("Mục đích", show(val(t, "don_vay", "muc_dich")) or "—", ""),
             ("Thu nhập khai", money(income) + ("/tháng" if income else ""), ""),
             ("Nơi làm việc", show(val(t, "don_vay", "ten_cong_ty")) or "—", "grow"),
             ("Ngày ký đơn", vdate(val(t, "don_vay", "ngay_ky")), ""),
             ("Chất lượng ảnh", AUGMENT.get(e["augment"], "—"), "")]
    st.html(f"""<div class="case"><div class="crumb"><a href="?">Hàng đợi rà soát</a> / {bid}</div>
<div class="row"><div class="who"><h1>{esc(customer(t))}</h1><span class="idtag mono">{bid}</span>{chip(dec['route'])}
{summary}</div><div class="nav">{nav}</div></div>
<div class="facts">{''.join(f'<div class="{c}"><span>{k}</span><b title="{esc(v)}">{esc(v)}</b></div>' for k, v, c in facts)}
</div></div>""")

    left, main = st.columns([0.95, 3.05], gap="medium")
    with left:
        def rule(c: dict) -> str:
            icon = {"pass": ico("check"), "fail": ico("x")}.get(c["status"], "?")
            title, failed, _ = RULES.get(c["rule_id"], (c["rule_id"], c["rule_id"], ""))
            text = c["message"]
            if c["status"] == "fail":  # message mở đầu bằng tên phép kiểm ('HĐLĐ còn hiệu lực: ...') cả khi fail
                title, text = failed, re.sub(r"^[^:=\d]+: ", "", text)
            text = REF.sub(lambda m: f"{DOC_NAMES[m[1]]} · {FIELD_LABEL.get(m[2], m[2]).lower()}"
                           + (" = " if m[3] else ""), text)  # don_vay.ho_ten=X -> "Đơn vay · họ và tên = X"
            msg = "" if c["status"] == "pass" else f'<div class="msg">{esc(text)}</div>'
            return (f'<div class="rl {c["status"]}"><div class="t"><span class="i">{icon}</span>'
                    f'<span class="id mono">{c["rule_id"]}</span><b>{title}</b></div>{msg}</div>')

        k = {s: len(v) for s, v in by_status.items()}
        st.html(f"""<div class="rules"><div class="h"><div class="top"><h3>Đối chiếu chéo</h3>
<span class="mono meta">{esc(dec['rules_version'])}</span></div><div class="bar"><i class="p" style="flex:{k['pass']}"></i>
<i class="f" style="flex:{k['fail']}"></i><i class="u" style="flex:{k['unknown']}"></i></div>
<div class="sum"><b class="p">{k['pass']} đạt</b> · <b class="f">{k['fail']} không đạt</b> · {k['unknown']} chưa đủ căn cứ
</div></div>{''.join(map(rule, t['checks']))}</div>""")
        if ag := t.get("agent"):
            agent_panel(ag)
        with st.expander("Nhãn thật (chỉ có vì dữ liệu tổng hợp)"):
            st.write({"route đúng": e["expected_route"], "lỗi cài vào": e["injected_errors"],
                      "near-miss": e["near_miss"], "mức ảnh": e["augment"], "layout": e["layout_ids"]})

    flags = flagged_fields(t)
    edits: dict[str, dict] = {}
    ext = {x["doc_type"]: x for x in t["extractions"]}
    with main:
        def tab_label(doc: str) -> str:
            nf = sum(k[0] == doc for k in flags)
            return DOC_NAMES[doc] + (" (!)" if doc not in ext else f" ({nf})" if nf else "")

        labels = [tab_label(d["type"]) for d in e["docs"]]
        # Mở sẵn giấy tờ đầu tiên bị gắn cờ: người rà soát không phải đi tìm
        tabs = st.tabs(labels, default=next((x for x in labels if x.endswith(")")), None), key=f"tabs/{bid}")
        for tab, d in zip(tabs, e["docs"]):
            doc = d["type"]
            with tab:
                img_col, fld_col = st.columns([1.25, 1], gap="medium")
                with img_col, st.container(key=f"viewer-{doc}"):
                    for f in d["files"]:
                        st.image(str(rv.SAMPLES / f), width="stretch")
                with fld_col, st.container(key=f"card-fields-{doc}"):
                    x = ext.get(doc)
                    st.html(f'<div class="cardh"><div><h3>Trường đã trích · {DOC_NAMES[doc]}</h3><small>'
                            f'{esc(x["model"].split("/")[-1].split("@")[0]) if x else "—"} · prompt '
                            f'{esc(x["prompt_version"]) if x else "—"}</small></div></div>')
                    if not x:
                        st.error("Không đọc được giấy tờ này (thiếu hoặc ảnh hỏng).")
                        continue
                    for name, fld in x["fields"].items():
                        key, label, flag = f"{bid}/{doc}/{name}", FIELD_LABEL.get(name, name), flags.get((doc, name))
                        info = (f"Chép từ ảnh: {fld['raw']!r} · tin cậy {CONF.get(fld['confidence'], fld['confidence'])}"
                                + (f" · lỗi: {fld['error']}" if fld["error"] else ""))
                        with st.container(key=f"flag-{doc}-{name}") if flag else st.container():
                            if flag:
                                st.html(f'<div class="fh"><span>{label}</span><span class="pills">'
                                        + "".join(f'<span class="pill {c}">{esc(w)}</span>' for c, w in flag["why"])
                                        + "</span></div>")
                            if name == "giao_dich":  # ponytail: bảng giao dịch chỉ xem, sửa từng dòng khi có nhu cầu thật
                                if not flag:
                                    st.html(f'<div class="fh"><span>{label}</span></div>')
                                rows = fld["value"]
                                if rows is None and fld["raw"]:  # đọc ra nhưng không hợp lệ: vẫn cho xem model đã chép gì
                                    try:
                                        rows = json.loads(fld["raw"])
                                    except ValueError:
                                        rows = None
                                st.dataframe(rows or [], width="stretch", height=220)
                                if fld["error"]:
                                    st.caption(f"Lỗi: {fld['error']}")
                                continue
                            st.session_state.setdefault(key, show(fld["value"]))
                            new = st.text_input(label, key=key, help=info,
                                                label_visibility="collapsed" if flag else "visible")
                            if flag:
                                peers = {(pd, pf): pv for pd, pf, pv in flag["peers"]}
                                st.html('<div class="cmp"><span>Chép từ ảnh</span><span>'
                                        f'“{esc(show(fld["raw"]))}” · tin cậy {CONF.get(fld["confidence"], "?")}</span>'
                                        + "".join(f'<span>{DOC_NAMES.get(pd, pd)} · {FIELD_LABEL.get(pf, pf).lower()}'
                                                  f'</span><span>{esc(vdate(pv))}</span>' for (pd, pf), pv in peers.items())
                                        + "</div>")
                                for v, pd in flag["suggest"].items():  # 1 click lấy giá trị giấy tờ kia
                                    if v != new:
                                        st.button(f"Dùng giá trị {DOC_NAMES.get(pd, pd)}", key=f"use/{key}/{pd}",
                                                  on_click=st.session_state.__setitem__, args=(key, v))
                        if new != show(fld["value"]):
                            edits[f"{doc}.{name}"] = {"from": show(fld["value"]), "to": new}

    with st.container(key="decision"):
        if dec["route"] == "AUTO_PASS":
            st.info("Bộ này đã tự duyệt: qua hết các rule, mọi field quan trọng tin cậy cao. Không vào hàng đợi.")
            return
        done = rv.items(con)
        row = done.get(bid, {})
        # ponytail: mỗi link là một lần tải trang (session mới) nên nhớ tên qua SQLite = người chốt gần nhất;
        # demo dùng chung 1 DB nên có thể là tên người khác, cần đăng nhập nếu có nhiều người rà soát thật
        last = max((d for d in done.values() if d["status"] == "closed"), key=lambda d: d["closed_at"], default={})
        if row.get("status") == "closed":
            st.success(f"Đã chốt: **{rv.CONCLUSIONS[row['conclusion']]}** bởi {row['reviewer']} sau "
                       f"{dur(row['closed_at'] - row['opened_at'])}. Sửa: {row['edits']}")
        with st.form(f"close/{bid}", border=False):
            c1, c2, c3, c4 = st.columns([2.7, 0.8, 1.1, 0.6], vertical_alignment="bottom")
            keys = list(rv.CONCLUSIONS)
            conclusion = c1.radio("Kết luận", keys, format_func=rv.CONCLUSIONS.get, horizontal=True,
                                  index=keys.index(row["conclusion"]) if row.get("conclusion") else None)
            reviewer = c2.text_input("Người rà soát", value=row.get("reviewer") or last.get("reviewer") or "")
            note = c3.text_input("Ghi chú", value=row.get("note") or "",
                                 placeholder="VD: tên đọc nhầm, đã sửa; cần HĐLĐ còn hiệu lực")
            opened = time.strftime("%H:%M", time.localtime(row["opened_at"])) if row.get("opened_at") else "—"
            c4.caption(f"Mở lúc {opened} · đã sửa {len(edits)} trường")
            submitted = c4.form_submit_button("Chốt hồ sơ", type="primary", width="stretch")
        if submitted:
            if not reviewer.strip():
                st.error("Nhập tên người rà soát.")
            elif not conclusion:
                st.error("Chọn một kết luận.")
            else:
                rv.close_item(con, bid, reviewer.strip(), conclusion, edits, note)
                st.rerun()


# ponytail: số liệu chép tay từ README (test đóng băng chạy 1 lần) và reports/comparison.md (dev 50 bộ); reports/
# không vào image. Cập nhật tay khi chạy lại.
RESULTS = [  # (biến thể, escape, cận trên 95 %, automation, false review, field acc, dòng mốc)
    ("Oracle — đọc đúng 100 % (trần tầng rule)", "0,0 %", "11,3 %", "50,0 %", "0,0 %", "100 %", False),
    ("Qwen3-VL-8B · 2 lượt tự nhất quán (chọn)", "0,0 %", "11,3 %", "44,0 %", "12,0 %", "99,4 %", True),
    ("Qwen2.5-VL-7B · 2 lượt", "0,0 %", "11,3 %", "46,0 %", "8,0 %", "98,5 %", False),
    ("EasyOCR + anchor (CPU, không VLM)", "0,0 %", "11,3 %", "8,0 %", "84,0 %", "72,3 %", False),
]


def overview_view() -> None:
    n = Counter(t["decision"]["route"] for t in traces.values())
    steps = [("Trích xuất", "VLM đọc 4 giấy tờ (CCCD, đơn vay, HĐLĐ, sao kê) ra JSON có cấu trúc; mỗi field kèm "
              "chép nguyên văn và độ tin cậy, đọc 2 lượt để tự kiểm."),
             ("Chuẩn hoá", "Ngày, tiền, tên có/không dấu đưa về một dạng để so khớp; field sai định dạng bị gắn cờ."),
             ("Đối chiếu R0–R8", "9 rule tất định so chéo giữa các giấy tờ: họ tên, CCCD, thu nhập, hạn hiệu lực…"
              " Rule không có LLM, cùng đầu vào luôn ra cùng kết quả."),
             ("Phân luồng", "Router chọn 1 trong 3 nhánh: tự duyệt, cần rà soát, yêu cầu bổ sung. Nghi ngờ thì đẩy "
              "sang người, không bao giờ đoán.")]
    kpi = [("Escape rate (test)", "2,0 %", "3/150 bộ sai lọt tự duyệt · cận trên 95 % 5,1 %", "more", ico("warn")),
           ("Automation (test)", "41,3 %", "trần lý thuyết 50 % (oracle)", "auto", ico("auto")),
           ("Recall lỗi cài vào", "100 %", "mọi mã lỗi E1–E8 với oracle", "done", ico("check")),
           ("Bộ mẫu trong demo", str(len(traces)), f"{n['AUTO_PASS']} tự duyệt · {n['REVIEW']} rà soát · "
            f"{n['REQUEST_MORE']} bổ sung", "review", ico("queue"))]
    rows = "".join(f'<tr{" class=base" if base else ""}><td>{esc(v)}</td>' + "".join(f'<td class="n">{x}</td>' for x in xs)
                   + "</tr>" for v, *xs, base in RESULTS)
    st.html(f"""<div class="hero"><div class="eyebrow">Dự án AI engineering · dữ liệu tổng hợp</div>
<h1>Thẩm định hồ sơ vay tiêu dùng bằng VLM + rule tất định</h1>
<p>Pipeline đọc bộ hồ sơ 4 giấy tờ, đối chiếu chéo bằng rule và quyết định bộ nào được tự duyệt. Thước đo chính là
<b>escape rate</b>: tỉ lệ bộ có sai lệch bị tự duyệt nhầm. Bộ nào chưa chắc chắn đều vào hàng đợi để người rà soát
xem ảnh gốc cạnh trường đã trích, sửa và chốt.</p>
<div class="cta"><a class="btn primary" href="?">Mở hàng đợi rà soát {ico("right")}</a>
<a class="btn sec" href="https://github.com/luongducthangDS/loan-doc-pipeline" target="_blank" rel="noopener">Mã nguồn trên GitHub</a></div></div>
<div class="sec-t">Kết quả đo</div>
<div class="kpis">{''.join(f'<div class="kpi"><div><span class="l">{l}</span><span class="v">{v}</span>'
                           f'<span class="s">{s}</span></div><div class="ic {c}">{i}</div></div>' for l, v, s, c, i in kpi)}</div>
<div class="sec-t">Pipeline</div>
<div class="flow">{''.join(f'<div class="step"><span class="n">{k}</span><b>{t}</b><p>{p}</p></div>'
                           for k, (t, p) in enumerate(steps, 1))}</div>
<div class="sec-t">9 rule đối chiếu</div>
<div class="rgrid">{''.join(f'<div><span class="pill mono unknown">{r}</span>{esc(ok)}</div>' for r, (ok, _, _) in RULES.items())}</div>
<div class="sec-t">So sánh biến thể trích xuất · dev 50 bộ</div>
<div class="twrap"><table class="tbl"><thead><tr><th>Biến thể</th><th class="n">Escape</th><th class="n">Cận trên 95 %</th>
<th class="n">Automation</th><th class="n">False review</th><th class="n">Field acc</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="foot">Escape 0 trên dev chưa đủ kết luận an toàn (chỉ 25 bộ có lỗi), nên luôn báo kèm cận trên 95 %. Test set
150 bộ chỉ chạy một lần với cấu hình đã chọn. Demo đọc kết quả đã chạy sẵn: không upload, không gọi model. Bảng đầy đủ (theo mức ảnh, paired diff route):
<a href="https://github.com/luongducthangDS/loan-doc-pipeline/blob/agent-mode/docs/COMPARISON.md" target="_blank" rel="noopener">docs/COMPARISON.md</a>.</div>""")


bid = st.query_params.get("bundle")
if page == "overview":
    overview_view()
elif bid in traces:
    detail_view(bid)
else:
    queue_view()
