"""VLM extractor qua API tương thích OpenAI (FPT AI Marketplace, vLLM, ...). M2.

- Mỗi lần gọi chỉ gửi MỘT giấy tờ (có thể nhiều trang).
- Model chỉ CHÉP chuỗi in trên ảnh; chuẩn hóa và confidence do code làm (loanpipe.validate).
- Lỗi mạng / output không phải JSON: thử lại 1 lần, sau đó trả rỗng -> field low -> REVIEW.
- Cache theo (model, prompt, ảnh, variant): đổi ngưỡng rồi chạy lại eval không tốn thêm tiền API.

Dùng stdlib urllib thay cho SDK openai: chỉ cần 1 endpoint, bớt một dependency.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps

from loanpipe.extract import RawExtraction
from loanpipe.schemas import DocType, field_kinds

PROMPT_VERSION = "v1"
MAX_SIDE = 1600  # ponytail: cố định; ví dụ của FPT resize 1280, nhưng chữ sao kê A4 nhỏ -> đo trên dev rồi chỉnh

DOC_LABEL = {
    DocType.CCCD: "Căn cước công dân gắn chip (ảnh 1: mặt trước, ảnh 2: mặt sau)",
    DocType.DON_VAY: "Giấy đề nghị vay vốn",
    DocType.HDLD: "Hợp đồng lao động",
    DocType.SAO_KE: "Sao kê tài khoản ngân hàng (có thể nhiều trang)",
}
FIELD_HINT = {
    "so_cccd": "số CCCD / số định danh cá nhân", "ho_ten": "họ và tên", "ngay_sinh": "ngày sinh",
    "gioi_tinh": "giới tính", "que_quan": "quê quán", "noi_thuong_tru": "nơi thường trú",
    "ngay_cap": "ngày cấp (mặt sau)", "ngay_het_han": "có giá trị đến / ngày hết hạn",
    "so_dien_thoai": "số điện thoại", "dia_chi": "địa chỉ", "ten_cong_ty": "tên công ty / nơi làm việc",
    "thu_nhap_thang": "thu nhập mỗi tháng", "so_tien_vay": "số tiền đề nghị vay", "thoi_han_thang": "thời hạn vay",
    "muc_dich": "mục đích vay", "so_tk_nhan_luong": "số tài khoản nhận lương", "ngay_ky": "ngày ký / ngày làm đơn",
    "ho_ten_nld": "họ tên người lao động", "chuc_danh": "chức danh / vị trí", "loai_hd": "loại hợp đồng",
    "ngay_bat_dau": "ngày bắt đầu", "ngay_ket_thuc": "ngày kết thúc (ghi đúng chữ nếu là 'Không xác định')",
    "muc_luong": "mức lương", "chu_tk": "tên chủ tài khoản", "so_tk": "số tài khoản", "ky_tu": "sao kê từ ngày",
    "ky_den": "sao kê đến ngày",
    "giao_dich": 'MỌI dòng giao dịch, mỗi dòng {"ngay", "mo_ta", "so_tien", "loai"}; '
                 'loai chép đúng ký hiệu trên ảnh (Ghi có/Ghi nợ, +/-, C/D)',
}
SYSTEM = (
    "Bạn là công cụ CHÉP dữ liệu từ ảnh giấy tờ tiếng Việt. Quy tắc:\n"
    "1. Chép NGUYÊN VĂN chuỗi in trên ảnh: giữ dấu, giữ định dạng số và ngày, không sửa chính tả, "
    "không chuẩn hóa, không suy luận, không tính toán.\n"
    "2. Không thấy field trên ảnh thì trả null. Tuyệt đối không đoán.\n"
    "3. Chỉ trả về MỘT object JSON, không giải thích."
)


def build_prompt(doc_type: DocType) -> str:
    lines = [f'- "{k}": {FIELD_HINT[k]}' for k in field_kinds(doc_type)]
    return (f"Giấy tờ: {DOC_LABEL[doc_type]}.\nTrả về JSON với các key sau:\n" + "\n".join(lines) +
            '\nMỗi value có dạng {"raw": <chuỗi nguyên văn>, "page": <số thứ tự ảnh, từ 1>} hoặc null. '
            'Riêng "giao_dich": {"raw": [danh sách dòng], "page": 1}.')


def parse_output(text: str, doc_type: DocType) -> dict[str, tuple[str | None, int | None]]:
    """Output model -> {field: (raw, page)}. Không phải JSON object -> ValueError (để retry)."""
    m = re.search(r"\{.*\}", text, re.S)  # bỏ ```json ... ``` hoặc chữ thừa quanh JSON
    obj = json.loads(m.group(0)) if m else None
    if not isinstance(obj, dict):
        raise ValueError("output không phải JSON object")
    out = {}
    for name in field_kinds(doc_type):
        v = obj.get(name)
        raw, page = (v.get("raw"), v.get("page")) if isinstance(v, dict) else (v, None)
        if isinstance(raw, (list, dict)):
            raw = json.dumps(raw, ensure_ascii=False)
        elif raw is not None:
            raw = str(raw)
        out[name] = (raw, page if isinstance(page, int) else None)
    return out


def encode_image(path: Path, variant: int) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    if variant == 1:  # ảnh "khác đi" cho tín hiệu tự nhất quán
        img = ImageOps.autocontrast(ImageOps.grayscale(img)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def http_post(url: str, key: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class VLMExtractor:
    prompt_version = PROMPT_VERSION

    def __init__(self, base_url: str, api_key: str, model: str, cache_dir: Path = Path(".cache/vlm"),
                 price_in: float = 0.0, price_out: float = 0.0,
                 post: Callable[[str, str, dict], dict] = http_post):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.key, self.name, self.cache_dir, self.post = api_key, model, cache_dir, post
        self.price_in, self.price_out = price_in, price_out  # USD / 1 triệu token

    def extract(self, bundle_id: str, doc_id: str, doc_type: DocType, files: list[Path],
                variant: int = 0) -> RawExtraction:
        prompt = build_prompt(doc_type)
        h = hashlib.sha256(f"{self.name}|{SYSTEM}|{prompt}|{variant}".encode())
        for f in files:
            h.update(Path(f).read_bytes())
        cache = self.cache_dir / f"{h.hexdigest()[:32]}.json"
        if cache.exists():
            r = RawExtraction(**json.loads(cache.read_text("utf-8")))
            r.fields = {k: tuple(v) for k, v in r.fields.items()}
            return r

        payload = {"model": self.name, "temperature": 0, "max_tokens": 4096, "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": prompt}] +
             [{"type": "image_url", "image_url": {"url": encode_image(f, variant)}} for f in files]}]}
        errors, text, cost, t0, calls = [], None, 0.0, time.perf_counter(), 0
        fields = {k: (None, None) for k in field_kinds(doc_type)}
        for _ in range(2):  # thử lại đúng 1 lần
            calls += 1
            try:
                resp = self.post(self.url, self.key, payload)
                text = resp["choices"][0]["message"]["content"]
                u = resp.get("usage") or {}
                cost += (u.get("prompt_tokens", 0) * self.price_in + u.get("completion_tokens", 0) * self.price_out) / 1e6
                fields = parse_output(text, doc_type)
                errors = []
                break
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
                errors.append(f"{type(e).__name__}: {e}")
        r = RawExtraction(fields=fields, latency_ms=round((time.perf_counter() - t0) * 1000), n_calls=calls,
                          cost_usd=cost, model_output=text, errors=errors)
        if not errors:  # chỉ cache kết quả thành công
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(r.__dict__, ensure_ascii=False), "utf-8")
        return r


def from_env() -> VLMExtractor:
    missing = [k for k in ("VLM_API_BASE", "VLM_API_KEY", "VLM_MODEL") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Thiếu biến môi trường {missing}; điền vào .env (xem .env.example)")
    return VLMExtractor(os.environ["VLM_API_BASE"], os.environ["VLM_API_KEY"], os.environ["VLM_MODEL"],
                        price_in=float(os.environ.get("VLM_PRICE_IN", 0)),
                        price_out=float(os.environ.get("VLM_PRICE_OUT", 0)))
