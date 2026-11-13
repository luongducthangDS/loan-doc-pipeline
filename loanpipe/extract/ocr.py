"""B1: OCR truyền thống (EasyOCR) + neo nhãn theo mẫu giấy tờ. CPU, không gọi API.

Khác VLM ở chỗ không "hiểu" ảnh: đọc chữ bằng detector+recognizer, rồi cắt giá trị bằng nhãn đã biết
của từng mẫu giấy tờ (layout A/B của datagen). Đây là cực "truyền thống" của trục so sánh: không có
model ngôn ngữ, không suy luận, chỉ có regex + vị trí cột.

Giới hạn có chủ đích (đo được, không giấu):
- Neo nhãn viết cho 3 mẫu trong `datagen/render.py`; layout C (chỉ có ở test) không được viết riêng.
- Bảng sao kê cần toạ độ cột để phân biệt "Ghi có"/"Ghi nợ" ở layout A (ô tiền không in dấu). Thiếu
  box cache thì chỉ đọc được bảng một cột có dấu +/- (layout B); ảnh photo nghiêng cũng hay mất header
  cột nên hướng giao dịch thành không rõ.
- variant=1 trả cùng kết quả: OCR là tất định trên cùng ảnh, nên tín hiệu "tự nhất quán" ở đây chỉ xác
  nhận lại cùng một lần đọc, KHÔNG phải lần đọc độc lập như ảnh autocontrast của VLM. Field vẫn high
  khi parse được, đúng như một pipeline OCR+rule.

Cache:
- `.cache/ocr`        danh sách dòng chữ (text-only), dùng chung với scripts/ocr_benchmark.py
- `.cache/ocr_boxes`  dòng chữ + box + latency: cần cho thứ tự đọc/nối dòng wrap và cho cột sao kê
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from loanpipe.extract import RawExtraction
from loanpipe.schemas import DocType

TEXT_CACHE = Path(".cache/ocr")
BOX_CACHE = Path(".cache/ocr_boxes")


# --- Chuỗi -------------------------------------------------------------------------

def fold(s: str) -> str:
    """Bỏ dấu, viết thường, gộp khoảng trắng và mọi dấu câu. Dùng cho neo nhãn."""
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})


def repair(s: str) -> str:
    """Sửa nhầm lẫn kinh điển của OCR trong chuỗi SỐ. Chỉ dùng cho field số/ngày/tiền."""
    return s.translate(_DIGIT_FIX)


_DATE = re.compile(r"\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{4}")
_LONG_DATE = re.compile(r"ngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*(\d{4})")


def dates_in(s: str) -> list[str]:
    return [m.group(0) for m in _DATE.finditer(repair(s))]


def find_date(s: str) -> str | None:
    ds = dates_in(s)
    if ds:
        return ds[0]
    m = _LONG_DATE.search(fold(s))
    if m:  # chép lại dạng số để normalize đọc được; chuỗi này không còn nguyên văn trên ảnh
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
    return None


def find_money(s: str) -> str | None:
    for m in re.finditer(r"[+\-]?\d[\d.,]*", repair(s)):
        tok = m.group(0)
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", tok) or re.fullmatch(r"\d{6,}", tok):
            return tok
    return None


def find_account(s: str) -> str | None:
    if find_date(s):  # dòng kỳ sao kê / ngày giao dịch: các cụm số không phải số tài khoản
        return None
    for m in re.finditer(r"\d[\d ]{4,}\d", repair(s)):
        tok = m.group(0).strip()
        if 6 <= len(re.sub(r"\D", "", tok)) <= 19:
            return tok
    return None


def find_cccd(s: str) -> str | None:
    for m in re.finditer(r"\d[\d ]{10,}\d", repair(s)):
        tok = m.group(0).strip()
        if len(re.sub(r"\D", "", tok)) == 12:
            return tok
    return None


def find_phone(s: str) -> str | None:
    if find_cccd(s):
        return None
    for m in re.finditer(r"\d[\d ]{7,}\d", repair(s)):
        tok = m.group(0).strip()
        d = re.sub(r"\D", "", tok)
        if 9 <= len(d) <= 11 and d.startswith("0"):
            return tok
    return None


def find_gender(s: str) -> str | None:
    f = fold(s)
    if re.search(r"\bnam\b", f):
        return "Nam"
    if re.search(r"\bnu\b", f):
        return "Nữ"
    return None


def find_int(s: str) -> str | None:
    m = re.search(r"(?<![\d.,])(\d{1,3})(?![\d.,])", repair(s))
    return m.group(1) if m else None


def find_loai_hd(s: str) -> str | None:
    f = fold(s)
    return s.strip() if ("khong xac dinh" in f or "xac dinh thoi han" in f) else None


def find_opt_date(s: str) -> str | None:
    if "khong xac dinh" in fold(s) or "khong thoi han" in fold(s):
        return "Không xác định"
    return find_date(s)


_STOP1 = set("""vay sinh thang cong tac von chuyen ve tai khoan nhan luong dien thoai di dong ngay ky
so cccd ho ten nguoi lao dung su muc dich thoi han thu nhap binh quan thuc hang nam nu gioi tinh que
noi thuong tru dia chi lien he don vi hien lam viec chuc danh mon loai hop bat dau ket tu den chinh
hoac tien ben a b chung toi mot va ong ba""".split())

# Nhãn song ngữ trên CCCD / sao kê: dòng chỉ có nhãn, không phải giá trị
_LABEL_LINES = {"full name", "full nome", "date of birth", "place of origin", "place of residence",
                "date of expiry", "date month year", "sex", "no", "personal identification",
                "citizen identity card", "account name", "account no", "signature",
                "sao ke tai khoan", "sao ke", "hop dong lao dong", "can cuoc cong dan"}


def _is_label_line(s: str) -> bool:
    return fold(s).strip(" .:-") in _LABEL_LINES


def find_text(s: str) -> str | None:
    v = s.strip(" .•-")
    if not v or v.endswith(":") or find_date(v) or find_money(v) or _is_label_line(v):
        return None
    f = fold(v)
    toks = f.split()
    if not toks or sum(c.isalpha() for c in v) < 4:
        return None
    if len(toks) == 1 and toks[0] in _STOP1:
        return None
    if len(toks) <= 4 and re.match(r"^(ngay|date|so|no|full nom|place of|sex|personal id|signature|account)\b", f):
        return None
    return v


def text_after_label(s: str) -> str | None:
    """Phần sau 'nhãn:' là giá trị theo cấu trúc, nên 'TA' vẫn hợp lệ dù ngắn.
    find_text từ chối chuỗi <4 chữ cái để tránh nuốt tiêu đề; ở đây không cần luật đó."""
    v = s.strip(" .•-")
    f = fold(v)
    if not v or v.endswith(":") or _is_label_line(v) or find_date(v) or find_money(v) \
            or sum(c.isalpha() for c in v) < 2:
        return None
    if len(f.split()) == 1 and f in _STOP1:
        return None
    return v


def split_amount(s: str) -> tuple[str, str, str] | None:
    """'704,000 PHI QUAN LY TAI KHOAN' -> ('', '704,000', 'PHI QUAN LY TAI KHOAN').
    Chỉ sửa ký tự trong cụm số; phần mô tả giữ nguyên (không biến O->0 trong chữ)."""
    m = re.match(r"^\s*([+\-]?)\s*([0-9OoIl|SB][0-9OoIl|SB.,]*)\s*(.*)$", s)
    if not m:
        return None
    tok = repair(m.group(2))
    if not re.fullmatch(r"(?:\d{1,3}(?:[.,]\d{3})+|\d+)", tok):
        return None
    return m.group(1), tok, m.group(3).strip()


def tail(s: str) -> str:
    return s.split(":", 1)[1].strip() if ":" in s else ""


def value_from(line: str, finder: Callable[[str], str | None]) -> str | None:
    """Dòng có thể là 'nhãn: giá trị' (nhãn ngắn, không chứa số) hoặc giá trị trần.
    Địa chỉ 'Phường 12, ... TP: Hồ Chí Minh' có dấu ':' bên trong giá trị nên chỉ cắt khi phần
    trước dấu ':' thật sự trông như nhãn."""
    if ":" in line:
        pre, post = line.split(":", 1)
        if post.strip() and not re.search(r"\d", pre) and len(fold(pre).split()) <= 4:
            if v := finder(post.strip()):
                return v
    return finder(line)


# --- Trang OCR ----------------------------------------------------------------------

@dataclass
class Line:
    text: str
    box: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2 if self.box else 0.0

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2 if self.box else 0.0


class OCRReader:
    def __init__(self, text_cache: Path = TEXT_CACHE, box_cache: Path = BOX_CACHE, engine=None):
        self.text_cache, self.box_cache, self._engine = text_cache, box_cache, engine

    def _easyocr(self):
        if self._engine is None:
            try:
                import easyocr
            except ImportError as e:
                raise RuntimeError("cần easyocr: pip install -r requirements-ocr.txt") from e
            self._engine = easyocr.Reader(["vi", "en"], gpu=False, verbose=False)
        return self._engine

    def read(self, path: Path) -> tuple[list[Line], int]:
        key = hashlib.sha1(Path(path).read_bytes()).hexdigest()[:24]
        bp = self.box_cache / f"{key}.json"
        if bp.exists():
            d = json.loads(bp.read_text("utf-8"))
            lines = [Line(t, (b[0][0], b[0][1], b[2][0], b[2][1])) for b, t, _ in d["lines"]]
            return lines, int(d.get("latency_ms", 0))
        tp = self.text_cache / f"{key}.json"
        if tp.exists():
            return [Line(t) for t in json.loads(tp.read_text("utf-8"))], 0
        t0 = time.perf_counter()
        out = self._easyocr().readtext(str(path), detail=1, paragraph=False)
        ms = round((time.perf_counter() - t0) * 1000)
        rows = [[[[round(p[0]), round(p[1])] for p in box], text, round(conf, 4)]
                for box, text, conf in out]
        self.box_cache.mkdir(parents=True, exist_ok=True)
        bp.write_text(json.dumps({"lines": rows, "latency_ms": ms}, ensure_ascii=False), "utf-8")
        self.text_cache.mkdir(parents=True, exist_ok=True)
        tp.write_text(json.dumps([r[1] for r in rows], ensure_ascii=False), "utf-8")
        return [Line(t, (b[0][0], b[0][1], b[2][0], b[2][1])) for b, t, _ in rows], ms


# --- Neo nhãn -----------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    anchors: tuple[str, ...]  # regex trên chuỗi đã fold
    finder: Callable[[str], str | None]
    pages: tuple[int, ...] | None = None  # 1-based; None = mọi trang
    direct: bool = False  # không thấy nhãn thì quét toàn trang bằng finder
    window: int = 4


CCCD = {
    "so_cccd": FieldSpec((), find_cccd, (1,), direct=True),
    "ho_ten": FieldSpec((r"ho\s*va\s*ten",), find_text, (1,)),
    "ngay_sinh": FieldSpec((r"ngay\s*sinh",), find_date, (1,)),
    "gioi_tinh": FieldSpec((r"gioi\s*tinh",), find_gender, (1,)),
    "que_quan": FieldSpec((r"que\s*quan",), find_text, (1,)),
    "noi_thuong_tru": FieldSpec((r"noi\s*thuong\s*tru",), find_text, (1,)),
    "ngay_het_han": FieldSpec((r"co\s*gia\s*tri\s*den", r"date of expiry"), find_date, (1,)),
    "ngay_cap": FieldSpec((r"ngay\s*thang\s*nam", r"date month year"), find_date, (2,)),
}

DON_VAY = {
    "ho_ten": FieldSpec((r"ho\s*va\s*ten\b", r"ho\s*ten\b", r"toi\s*ten\s*la"), find_text),
    "so_cccd": FieldSpec((r"so\s*cccd", r"cccd\s*so", r"so\s*dinh\s*danh"), find_cccd,
                         direct=True),
    "ngay_sinh": FieldSpec((r"ngay\s*sinh", r"thang\s*nam\s*sinh", r"sinh\s*ngay"), find_date),
    "so_dien_thoai": FieldSpec((r"dien\s*thoai", r"lien\s*lac\s*qua\s*so"), find_phone, direct=True),
    "dia_chi": FieldSpec((r"dia\s*chi\s*thuong\s*tru", r"dia\s*chi\s*lien\s*he", r"cho\s*o\s*hien\s*nay"),
                         find_text),
    "ten_cong_ty": FieldSpec((r"noi\s*cong\s*tac", r"don\s*vi\s*cong\s*tac", r"hien\s*lam\s*viec\s*tai"),
                             find_text),
    "thu_nhap_thang": FieldSpec((r"thu\s*nhap\s*thuc\s*nhan", r"thu\s*nhap\s*binh\s*quan",
                                 r"luong\s*thu\s*nhap\s*moi\s*thang"), find_money),
    "so_tk_nhan_luong": FieldSpec((r"so\s*tai\s*khoan\s*nhan", r"tai\s*khoan\s*nhan\s*luong",
                                   r"luong\s*chuyen\s*ve\s*tai\s*khoan"), find_account),
    "so_tien_vay": FieldSpec((r"so\s*tien\s*de\s*nghi\s*vay", r"so\s*tien\s*vay", r"khoan\s*tien"),
                             find_money),
    "thoi_han_thang": FieldSpec((r"thoi\s*han\s*vay", r"tra\s*dan\s*trong"), find_int),
    "muc_dich": FieldSpec((r"muc\s*dich\s*vay", r"muc\s*dich\s*su\s*dung", r"dich\s*su\s*dung\s*von",
                           r"de\s*dung\s*vao\s*viec"), find_text),
    "ngay_ky": FieldSpec((r"ngay\s*ky", r"lam\s*tai", r"ha\s*noi"), find_date),
}

HDLD = {
    "ten_cong_ty": FieldSpec((r"ben\s*a", r"chung\s*toi\s*,?\s*mot\s*ben\s*la", r"nguoi\s*su\s*dung\s*lao"),
                             find_text),
    "ho_ten_nld": FieldSpec((r"ben\s*b", r"va\s*mot\s*ben\s*la", r"nguoi\s*lao\s*dong"), find_text),
    "chuc_danh": FieldSpec((r"chuc\s*danh\s*chuyen\s*mon", r"chuc\s*vu", r"vi\s*tri"), find_text),
    "loai_hd": FieldSpec((r"loai\s*hop\b", r"loai\s*hd"), find_loai_hd),
    "ngay_bat_dau": FieldSpec((r"tu\s*ngay", r"bat\s*dau", r"ngay\s*hieu\s*luc"), find_date),
    "ngay_ket_thuc": FieldSpec((r"den\s*ngay", r"ket\s*thuc", r"ngay\s*het\s*han"), find_opt_date),
    "muc_luong": FieldSpec((r"muc\s*luong\s*chinh", r"luong\s*co\s*ban", r"muc\s*luong"), find_money),
}

SAO_KE = {
    "chu_tk": FieldSpec((r"chu\s*tai\s*khoan", r"ten\s*tai\s*khoan", r"ten\s*tk", r"account name"),
                        find_text),
    "so_tk": FieldSpec((r"so\s*tai\s*khoan", r"so\s*tk", r"account no"), find_account),
}

DOC_SPECS = {DocType.CCCD: CCCD, DocType.DON_VAY: DON_VAY, DocType.HDLD: HDLD, DocType.SAO_KE: SAO_KE}


def scan(lines: list[Line], spec: FieldSpec, others: tuple[str, ...] = ()) -> str | None:
    texts = [ln.text for ln in lines]
    for i, line in enumerate(texts):
        f = fold(line)
        if not any(re.search(a, f) for a in spec.anchors):
            continue
        t = tail(line)
        if t:
            v = spec.finder(t)
            if v is None and spec.finder is find_text:
                v = text_after_label(t)
            if v:
                return v + (joined(lines, i, others, inline=True) if spec.finder is find_text else "")
        # giá trị cùng dòng, không có dấu ':' (vd "Hà Nội, ngày 15 tháng 09 năm 2026"):
        # chỉ nhận khi finder cắt ra một phần của dòng, tránh trả lại nguyên nhãn cho field text
        if (v := spec.finder(line)) and v.strip() != line.strip():
            return v
        for j in range(i + 1, min(i + 1 + spec.window, len(texts))):
            nxt = fold(texts[j])
            if any(re.search(a, nxt) for a in others if a not in spec.anchors):
                continue  # nhãn của field khác: đừng lấy giá trị của nó
            if v := value_from(texts[j], spec.finder):
                if spec.finder is find_text:
                    v += joined(lines, j, others, inline=False)
                return v
            if spec.finder is find_text and (v := value_from(texts[j], text_after_label)):
                return v + joined(lines, j, others, inline=False)
    return None


def joined(lines: list[Line], j: int, others: tuple[str, ...], inline: bool) -> str:
    """Nối dòng xuống của một giá trị text, chỉ khi cùng cột với giá trị.
    inline: giá trị nằm sau 'nhãn:' trên dòng nhãn -> dòng nối thụt vào so với lề nhãn.
    Ngược lại dòng j là dòng giá trị -> dòng nối phải cùng x0 (sai số vài px)."""
    base = lines[j]
    if base.box is None:
        return ""
    out = []
    for ln in lines[j + 1:j + 3]:
        if ln.box is None:
            break
        same_col = (ln.box[0] - base.box[0] >= 40) if inline else abs(ln.box[0] - base.box[0]) <= 18
        f = fold(ln.text)
        stop = (ln.text.strip().endswith(":") or _is_label_line(ln.text)
                or (len(f.split()) == 1 and f in _STOP1)
                or any(re.search(a, f) for a in others))
        if not same_col or stop:
            break
        out.append(ln.text.strip())
    return (" " + " ".join(out)) if out else ""


def ordered(page: list[Line]) -> list[Line]:
    """Thứ tự đọc theo hàng: gom dòng cùng độ cao (ảnh nghiêng lệch vài px), trong hàng xếp theo x.
    OCR trên ảnh photo trả dòng lộn xộn; neo nhãn cần thứ tự địa lý chứ không phải thứ tự detector."""
    if not page or page[0].box is None:
        return page
    heights = sorted(ln.box[3] - ln.box[1] for ln in page)
    tol = max(8.0, 0.6 * heights[len(heights) // 2])
    bands: list[list[Line]] = []
    for ln in sorted(page, key=lambda x: x.cy):
        if bands and ln.cy - bands[-1][0].cy <= tol:
            bands[-1].append(ln)
        else:
            bands.append([ln])
    return [ln for band in bands for ln in sorted(band, key=lambda x: x.cx)]


def extract_doc(doc_type: DocType, pages: list[list[Line]]) -> dict[str, tuple[str, int]]:
    """Trả {field: (raw, page)}. Chỉ gồm field đọc được; field thiếu để validate chấm low."""
    specs = DOC_SPECS[doc_type]
    out: dict[str, tuple[str, int]] = {}
    for name, spec in specs.items():
        others = tuple(a for n, s in specs.items() if n != name for a in s.anchors)
        hit = None
        for pno in spec.pages or range(1, len(pages) + 1):
            if pno > len(pages):
                break
            page = ordered(pages[pno - 1])
            if (v := scan(page, spec, others)) or (
                    spec.direct and (v := next((x for x in map(spec.finder, (ln.text for ln in page)) if x), None))):
                hit = (v, pno)
                break
        if hit:
            out[name] = hit
    if doc_type is DocType.DON_VAY and out.get("so_tk_nhan_luong", ("",))[0] == out.get("so_cccd", (None,))[0]:
        out.pop("so_tk_nhan_luong", None)  # số CCCD 12 chữ số cũng khớp mẫu số tài khoản
    return out


# --- Bảng sao kê --------------------------------------------------------------------

_NOISE = ("du lieu tong hop", "khong co gia tri phap ly")


def _is_noise(f: str) -> bool:
    return f in ("mau", "") or any(k in f for k in _NOISE) or f.startswith("trang ")


_HEADER_NAMES = {"ngay", "ngay gd", "ghi co", "ghi no", "noi dung", "so tien", "dien giai", "mo ta",
                 "mo ta description", "phat sinh", "c d", "so du"}


def _lead_date(s: str) -> str | None:
    m = _DATE.match(repair(s).strip())
    return m.group(0) if m else None


def _header_kind(s: str) -> str | None:
    """Tên cột chuẩn từ chữ OCR; nhận cả bản đọc thiếu ký tự ('Ghi ng') theo tiền tố mẫu."""
    f = fold(s)
    if f in _HEADER_NAMES:
        return f
    if re.match(r"^ghi\s+c", f):
        return "ghi co"
    if re.match(r"^ghi\s+n", f):
        return "ghi no"
    return None


def _col_map(peers: list[Line]) -> dict[str, float]:
    out: dict[str, float] = {}
    for ln in peers:
        if kind := _header_kind(ln.text):
            out.setdefault(kind, ln.cx)
    return out


def parse_statement_page(lines: list[Line]) -> list[dict]:
    if not lines or lines[0].box is None:
        return parse_statement_text([ln.text for ln in lines])
    best: tuple[Line, list[Line]] | None = None
    for ln in lines:
        if fold(ln.text) not in ("ngay", "ngay gd"):
            continue
        peers = [x for x in lines if x.box and abs(x.cy - ln.cy) <= 30 and _header_kind(x.text)]
        if len(peers) >= 3 and (best is None or ln.cy < best[0].cy):
            best = (ln, peers)
    if not best:
        return parse_statement_text([ln.text for ln in lines])
    hdr, peers = best
    cols = _col_map(peers)
    body = sorted((x for x in lines if x.box and x.cy > hdr.cy and not _is_noise(fold(x.text))),
                  key=lambda x: (x.cy, x.cx))
    dates = [x for x in body if _lead_date(x.text)]
    if not dates:
        return []
    groups: dict[int, list[Line]] = {id(d): [] for d in dates}
    for ln in body:
        if _lead_date(ln.text):
            continue
        owner = min(dates, key=lambda d: abs(d.cy - ln.cy))  # gán theo hàng gần nhất: ảnh hơi nghiêng vẫn đúng
        groups[id(owner)].append(ln)
    rows = []
    for d in dates:
        if row := _row([d, *sorted(groups[id(d)], key=lambda x: (x.cy, x.cx))], cols):
            rows.append(row)
    return rows


def _row(g: list[Line], cols: dict[str, float]) -> dict | None:
    date = _lead_date(g[0].text)
    amounts: list[tuple[str, float]] = []  # (số tiền, x tâm)
    cds: list[str] = []
    desc: list[str] = []
    for ln in g[1:]:
        f = fold(ln.text)
        if f in ("c", "d", "cr", "dr"):
            cds.append("ghi_co" if f in ("c", "cr") else "ghi_no")
            continue
        m = split_amount(ln.text)
        if m:
            sign, tok, rest = m
            amounts.append((tok, ln.cx))
            if rest:
                desc.append(rest)
            if sign:
                cds.append("ghi_co" if sign == "+" else "ghi_no")
        else:
            desc.append(ln.text.strip())
    if not amounts:
        return {"ngay": date, "mo_ta": " ".join(desc), "so_tien": "", "loai": ""}
    amt, x = amounts[0]
    if len(amounts) > 1 and "phat sinh" in cols:  # layout C: bỏ cột số dư
        amt, x = min(amounts, key=lambda a: abs(a[1] - cols["phat sinh"]))
    if cds:
        loai = cds[0]
    elif "ghi co" in cols and "ghi no" in cols:
        loai = min(("ghi co", "ghi no"), key=lambda k: abs(x - cols[k]))
    else:
        loai = ""
    return {"ngay": date, "mo_ta": " ".join(desc), "so_tien": amt,
            "loai": {"ghi_co": "Ghi có", "ghi_no": "Ghi nợ"}.get(loai.replace(" ", "_"), "")}


def parse_statement_text(lines: list[str]) -> list[dict]:
    """Fallback không có toạ độ: chỉ đọc được bảng một cột tiền có dấu +/- (layout B)."""
    raw_rows: list[list[str]] = []
    for s in (x.strip() for x in lines):
        f = fold(s)
        if not s or _is_noise(f):
            continue
        if _lead_date(s):
            raw_rows.append([s])
        elif raw_rows:
            raw_rows[-1].append(s)
    rows = []
    for g in raw_rows:
        amounts, signs, desc = [], [], []
        for s in g[1:]:
            m = split_amount(s)
            if not m:
                desc.append(s)
                continue
            sign, tok, rest = m
            amounts.append(tok)
            if sign:
                signs.append(sign)
            if rest:
                desc.append(rest)
        rows.append({"ngay": _lead_date(g[0]), "mo_ta": " ".join(desc),
                     "so_tien": amounts[0] if amounts else "",
                     "loai": {"+": "Ghi có", "-": "Ghi nợ"}.get(signs[0], "") if signs else ""})
    return rows


def extract_period(pages: list[list[Line]]) -> tuple[str | None, str | None, int | None]:
    for pno, page in enumerate(pages, 1):
        for ln in page:
            f = fold(ln.text)
            if not any(k in f for k in ("tu ngay", "ky sao ke", "period")):
                continue
            ds = dates_in(ln.text)
            if len(ds) >= 2:
                return ds[0], ds[1], pno
    return None, None, None


# --- Extractor ----------------------------------------------------------------------

class OCRExtractor:
    name = "ocr"
    prompt_version = "anchors-v1"

    def __init__(self, reader: OCRReader | None = None):
        self.reader = reader or OCRReader()

    def extract(self, bundle_id: str, doc_id: str, doc_type: DocType, files: list[Path],
                variant: int = 0, method: str = "") -> RawExtraction:
        pages: list[list[Line]] = []
        latency, errors = 0, []
        for f in files:
            try:
                lines, ms = self.reader.read(f)
                latency += ms
                pages.append(lines)
            except Exception as e:  # ảnh hỏng: giấy tờ coi như thiếu field, pipeline đẩy REVIEW
                errors.append(f"{f.name}: {type(e).__name__}: {e}")
                pages.append([])
        raw: dict[str, tuple[str | None, int]] = {
            k: (v, p) for k, (v, p) in extract_doc(doc_type, pages).items()}
        if doc_type is DocType.SAO_KE:
            tu, den, pno = extract_period(pages)
            if tu:
                raw["ky_tu"] = (tu, pno)
            if den:
                raw["ky_den"] = (den, pno)
            rows: list[dict] = []
            first = None
            for pno, page in enumerate(pages, 1):
                part = parse_statement_page(page)
                if part and first is None:
                    first = pno
                rows += part
            if rows:
                raw["giao_dich"] = (json.dumps(rows, ensure_ascii=False), first)
        return RawExtraction(fields=raw, latency_ms=latency, n_calls=len(files), errors=errors)
