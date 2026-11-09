"""Agent tiền kiểm hồ sơ vay: LLM tự lập kế hoạch và gọi tool, thay cho workflow cố định 6 bước.

LLM tự quyết đọc giấy tờ nào, theo thứ tự nào, đọc lại bằng cách xử lý ảnh nào, khi nào chạy rule, khi nào
dừng sớm (vd thiếu giấy tờ -> REQUEST_MORE ngay, không tốn lượt gọi VLM cho 3 giấy tờ còn lại).

Mẫu thiết kế mượn từ các framework agent phổ biến, viết lại gọn bằng stdlib (không thêm dependency):
- Vòng ReAct qua function calling chuẩn OpenAI, giới hạn `max_turns` (OpenAI Agents SDK, smolagents).
- Output guardrail ở tool `finish`: kết luận không hợp lệ bị TỪ CHỐI và lý do được trả lại cho model để nó tự
  sửa (ModelRetry của Pydantic AI), thay vì âm thầm ghi đè.
- Mọi bước ghi vào trace (tool, tham số, kết quả) để truy ngược quyết định.

Ranh giới an toàn do CODE giữ, không nằm trong prompt:
1. LLM không bao giờ đưa ra giá trị field. Giá trị chỉ đến từ VLM, mỗi lượt gọi đúng một giấy tờ, rồi qua
   chuẩn hóa + confidence của pipeline (finalize_doc).
2. Đọc lại chỉ LẤP CHỖ TRỐNG: field low thành high khi 2 lượt mới tự nhất quán VÀ khớp mọi lượt đọc hợp lệ
   trước đó. Bất đồng giữa các lượt (vd Thăng/Thắng, lỗ E1) giữ low. Field high bị khoá.
3. Mỗi (giấy tờ, cách đọc) chỉ 1 lần: không thể thử mãi tới khi ra kết quả vừa ý.
4. AUTO_PASS chỉ nhận khi router tất định trên dữ liệu hiện có cũng ra AUTO_PASS (giấy tờ chưa đọc = unknown,
   không bao giờ là pass). Thiếu giấy tờ (R0 fail) chỉ được REQUEST_MORE.
5. LLM lỗi / hết lượt mà chưa có kết luận hợp lệ -> dùng router trên dữ liệu đã đọc được.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
from collections.abc import Callable

from loanpipe.config import RulesConfig, Thresholds
from loanpipe.extract import Extractor
from loanpipe.pipeline import BundleInput, finalize_doc, is_readable
from loanpipe.router import route
from loanpipe.rules import BundleView, run_rules, salary_months
from loanpipe.schemas import Decision, DocType, Extraction, Field, field_kinds
from loanpipe.validate import finalize_field

METHODS = ("original", "deskew", "hires")
ROUTES = ("AUTO_PASS", "REVIEW", "REQUEST_MORE")
MAX_TURNS = 12

SYSTEM = """Bạn là chuyên viên tiền kiểm hồ sơ vay tiêu dùng. Một bộ hồ sơ cần đủ 4 giấy tờ: cccd, don_vay, hdld, sao_ke.
Bạn tự lập kế hoạch và gọi tool để chốt bộ hồ sơ vào 1 nhánh:
- AUTO_PASS: đủ giấy tờ, mọi rule pass, mọi field quan trọng đọc chắc chắn (high).
- REVIEW: có rule fail, hoặc còn điều chưa chắc -> người rà soát.
- REQUEST_MORE: thiếu giấy tờ / file không đọc được / ảnh quá xấu -> xin khách nộp lại.

Rule đối chiếu (code tính, bạn chỉ đọc kết quả):
R0 đủ 4 giấy tờ đọc được | R1 họ tên khớp: đơn = CCCD = HĐLĐ = chủ TK sao kê | R2 số CCCD: đơn = CCCD
R3 ngày sinh: đơn = CCCD | R4 thu nhập khai <= lương TB 3 tháng trên sao kê x 1,1 | R5 CCCD còn hạn tại ngày ký đơn
R6 TK nhận lương trên đơn = số TK sao kê | R7 HĐLĐ còn hiệu lực tại ngày ký | R8 sao kê gần ngày ký và phủ >= 3 tháng

Cách làm tốt:
- Gọi list_documents trước. Thiếu giấy tờ hoặc file hỏng -> finish REQUEST_MORE ngay, không cần đọc gì.
- read_document đọc một giấy tờ (mỗi lần gọi model đọc ảnh tốn tiền, đừng đọc thừa). Đọc cccd và don_vay trước:
  nếu R1/R2/R3 đã fail với field high thì đó là sai lệch thật -> REVIEW, không cần đọc tiếp.
- Field low (ảnh nghiêng, chữ nhỏ, đọc không rõ): thử đọc lại giấy tờ đó với method deskew (ảnh chụp nghiêng)
  hoặc hires (chữ nhỏ, như sao kê). Mỗi cặp (giấy tờ, method) chỉ 1 lần. Đọc lại không sửa được bất đồng
  giữa các lượt đọc: field đó sẽ vẫn low -> REVIEW.
- Bạn KHÔNG sửa được giá trị field và không được tự suy diễn tên/số cho khớp nhau.
- Kết thúc bằng finish(route, note). note: 1-3 câu tiếng Việt cho người rà soát: đã kiểm gì, vướng ở đâu.
  Nếu finish bị từ chối, đọc lý do rồi xử lý tiếp."""


def _fn(name: str, desc: str, props: dict, req: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": req}}}


TOOLS = [
    _fn("list_documents", "Liệt kê giấy tờ trong bộ: loại, số trang, file đọc được không, loại nào còn thiếu.", {}, []),
    _fn("read_document", "Cho model đọc một giấy tờ (2 lượt tự nhất quán). Trả field: giá trị, confidence, lỗi.",
        {"doc_type": {"type": "string", "enum": [d.value for d in DocType]},
         "method": {"type": "string", "enum": list(METHODS), "description": "original lần đầu; deskew/hires để đọc lại"}},
        ["doc_type"]),
    _fn("run_rules", "Chạy rule R0–R8 và router trên dữ liệu đã đọc. Giấy tờ chưa đọc cho ra unknown.", {}, []),
    _fn("finish", "Chốt nhánh cho bộ hồ sơ.",
        {"route": {"type": "string", "enum": list(ROUTES)}, "note": {"type": "string"}}, ["route", "note"]),
]


class Session:
    """Trạng thái của một bộ hồ sơ; mỗi tool là một method `tool_<tên>`."""

    def __init__(self, inp: BundleInput, extractor: Extractor, cfg: RulesConfig, thr: Thresholds,
                 check_files: bool = True):
        self.inp, self.ex, self.cfg, self.thr = inp, extractor, cfg, thr
        self.docs = {d.doc_type: d for d in inp.docs}
        self.unreadable = [d.doc_type for d in inp.docs if check_files and not is_readable(d.files)]
        self.fields: dict[DocType, dict[str, Field]] = {}
        self.history: dict[tuple[DocType, str], list[str | None]] = {}  # mọi raw đã đọc theo field
        self.tried: set[tuple[DocType, str]] = set()
        self.n_calls, self.cost, self.latency = 0, 0.0, {}
        self.model_outputs: dict[str, str | None] = {}
        self.extract_errors: dict[str, list[str]] = {}
        self.final: Decision | None = None
        self.note: str | None = None
        self.rejections = 0

    # --- trạng thái -> rule/router ---
    def evaluate(self) -> tuple[list, Decision]:
        # giấy tờ có mặt nhưng chưa đọc: field rỗng -> rule unknown (không bao giờ pass), R0 không tính là thiếu
        docs = {dt: self.fields.get(dt, {}) for dt in self.docs if dt not in self.unreadable}
        view = BundleView(docs, self.unreadable)
        checks = run_rules(view, self.cfg)
        return checks, route(self.inp.bundle_id, view, checks, self.cfg, self.thr)

    def _same(self, kind: str):
        if kind == "transactions":
            return lambda a, b: salary_months(a, self.cfg) == salary_months(b, self.cfg)
        return lambda a, b: a == b

    def _show(self, dt: DocType) -> dict:
        out = {}
        for k, f in self.fields[dt].items():
            v = f.value
            if k == "giao_dich" and isinstance(v, list):
                v = {"so_dong": len(v), "luong_theo_thang": {f"{y}-{m:02d}": s for (y, m), s in
                                                             salary_months(v, self.cfg).items()}}
            out[k] = {"value": v, "confidence": f.confidence, **({"error": f.error} if f.error else {})}
        return out

    # --- tools ---
    def tool_list_documents(self) -> dict:
        missing = [dt.value for dt in DocType if dt not in self.docs]
        bad = missing + [u.value for u in self.unreadable]
        # Observation nêu thẳng hệ quả: model nhỏ (7B) đo được là bỏ qua "missing" rồi vẫn đọc tiếp
        hint = (f"R0 fail ({', '.join(bad)}): kết luận duy nhất hợp lệ là REQUEST_MORE, không cần đọc giấy tờ nào"
                if bad else "Đủ 4 giấy tờ, file đọc được")
        return {"documents": [{"doc_type": d.doc_type.value, "pages": len(d.files),
                               "readable": d.doc_type not in self.unreadable,
                               "read_with": sorted(m for t, m in self.tried if t is d.doc_type)}
                              for d in self.inp.docs],
                "missing": missing, "hint": hint}

    def tool_read_document(self, doc_type: str, method: str = "original") -> dict:
        try:
            dt = DocType(doc_type)
        except ValueError:
            return {"error": f"doc_type không hợp lệ: {doc_type}"}
        if method not in METHODS:
            return {"error": f"method không hợp lệ: {method}"}
        if dt not in self.docs or dt in self.unreadable:
            return {"error": f"{doc_type} không có trong bộ hoặc file không đọc được"}
        if (dt, method) in self.tried:
            return {"error": f"đã đọc {doc_type} bằng {method} rồi"}
        self.tried.add((dt, method))
        d, m = self.docs[dt], "" if method == "original" else method
        r1 = self.ex.extract(self.inp.bundle_id, d.doc_id, dt, d.files, variant=0, method=m)
        r2 = (self.ex.extract(self.inp.bundle_id, d.doc_id, dt, d.files, variant=1, method=m)
              if self.thr.use_self_consistency else None)
        runs = [r for r in (r1, r2) if r is not None]
        self.n_calls += sum(r.n_calls for r in runs)
        self.cost += sum(r.cost_usd for r in runs)
        self.latency[dt] = self.latency.get(dt, 0) + sum(r.latency_ms for r in runs)
        self.model_outputs.setdefault(d.doc_id, r1.model_output)
        if errs := [e for r in runs for e in r.errors]:
            self.extract_errors.setdefault(d.doc_id, []).extend(errs)

        new = finalize_doc(dt, r1, r2, self.cfg, self.thr)
        kinds, upgraded = field_kinds(dt), []
        for k, f in new.items():
            old = self.history.get((dt, k), [])
            self.history[(dt, k)] = old + [r.fields.get(k, (None, None))[0] for r in runs]
            if dt not in self.fields:
                continue  # lần đọc đầu: nhận nguyên
            cur = self.fields[dt][k]
            if cur.confidence == "high" or f.confidence != "high":
                continue  # khoá field high; lượt mới không chắc thì bỏ
            same = self._same(kinds[k])
            prior = [finalize_field(kinds[k], r).value for r in old]
            if all(v is None or same(v, f.value) for v in prior):
                self.fields[dt][k] = f
                upgraded.append(k)
        if dt not in self.fields:
            self.fields[dt] = new
        return {"doc_type": doc_type, "method": method, "fields": self._show(dt),
                **({"upgraded": upgraded} if method != "original" else {})}

    def tool_run_rules(self) -> dict:
        checks, d = self.evaluate()
        return {"rules": [{"rule": c.rule_id, "status": c.status, "message": c.message} for c in checks],
                "router_route": d.route, "router_reasons": d.reasons,
                "unread": [dt.value for dt in self.docs if dt not in self.fields and dt not in self.unreadable]}

    def tool_finish(self, route: str, note: str = "") -> dict:
        if route not in ROUTES:
            return {"accepted": False, "error": f"route phải là một trong {ROUTES}"}
        checks, d = self.evaluate()
        r0_fail = any(c.rule_id == "R0" and c.status == "fail" for c in checks)
        why = None
        if route == "AUTO_PASS" and d.route != "AUTO_PASS":
            why = "Chưa đủ điều kiện AUTO_PASS: " + ", ".join(d.reasons)
        elif r0_fail and route != "REQUEST_MORE":
            why = "Thiếu giấy tờ hoặc file hỏng (R0 fail): chỉ được REQUEST_MORE"
        if why:
            self.rejections += 1
            return {"accepted": False, "error": why}
        self.note = note
        self.final = d if route == d.route else d.model_copy(
            update={"route": route, "reasons": d.reasons + [f"AGENT:{route}"]})
        return {"accepted": True}

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return {"error": f"không có tool {name}"}
        try:
            return fn(**args)
        except TypeError as e:  # sai tham số: trả lại cho model tự sửa
            return {"error": f"tham số sai: {e}"}


def run_bundle_agent(inp: BundleInput, extractor: Extractor, rules_cfg: RulesConfig, thr: Thresholds,
                     llm: Callable[[list, list], dict], check_files: bool = True, max_turns: int = MAX_TURNS) -> dict:
    t0 = time.perf_counter()
    s = Session(inp, extractor, rules_cfg, thr, check_files)
    log: dict = {"model": getattr(llm, "model", "?"), "turns": 0, "steps": [], "note": None,
                 "finished_by": "fallback", "rejections": 0, "error": None,
                 "llm_ms": 0, "llm_tokens_in": 0, "llm_tokens_out": 0, "llm_cost_usd": 0.0}
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Tiền kiểm bộ hồ sơ {inp.bundle_id}."}]
    try:
        while log["turns"] < max_turns and s.final is None:
            t1 = time.perf_counter()
            msg = dict(llm(msgs, TOOLS))
            log["llm_ms"] += round((time.perf_counter() - t1) * 1000)
            log["turns"] += 1
            u = msg.pop("_usage", None) or {}  # from_env gắn usage vào message; LLM giả thì không có
            log["llm_tokens_in"] += u.get("prompt_tokens", 0)
            log["llm_tokens_out"] += u.get("completion_tokens", 0)
            log["llm_cost_usd"] += msg.pop("_cost_usd", 0.0)
            msgs.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:  # model trả lời bằng chữ: nhắc dùng tool
                if msg.get("content"):
                    log["steps"].append({"thought": msg["content"]})
                msgs.append({"role": "user", "content": "Hãy gọi tool; kết thúc bằng finish."})
                continue
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = None
                res = s.call(name, args) if isinstance(args, dict) else {"error": "arguments không phải JSON object"}
                content = json.dumps(res, ensure_ascii=False, default=str)  # date -> chuỗi ISO
                log["steps"].append({"tool": name, "args": args, "result": json.loads(content)})
                msgs.append({"role": "tool", "tool_call_id": c.get("id", name), "content": content})
                if s.final is not None:
                    break
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as e:
        log["error"] = f"{type(e).__name__}: {e}"

    checks, d = s.evaluate()
    if s.final is not None:
        log["finished_by"], log["note"], d = "agent", s.note, s.final
    log["rejections"] = s.rejections
    extractions = [Extraction(bundle_id=inp.bundle_id, doc_id=s.docs[dt].doc_id, doc_type=dt, fields=f,
                              model=extractor.name, prompt_version=extractor.prompt_version,
                              latency_ms=s.latency.get(dt, 0), n_calls=0) for dt, f in s.fields.items()]
    return {
        "bundle_id": inp.bundle_id,
        "steps": {"agent_ms": round((time.perf_counter() - t0) * 1000)},
        # latency VLM đã ghi (đọc được cả từ cache) + thời gian thật của LLM điều phối
        "latency_ms": sum(s.latency.values()) + log["llm_ms"],
        "n_calls": s.n_calls,  # lượt gọi VLM; lượt gọi LLM ở agent.turns
        "cost_usd": s.cost + log["llm_cost_usd"],
        "unreadable": [u.value for u in s.unreadable],
        "extractions": [e.model_dump(mode="json") for e in extractions],
        "model_outputs": s.model_outputs,
        "extract_errors": s.extract_errors,
        "checks": [c.model_dump(mode="json") for c in checks],
        "decision": d.model_dump(mode="json"),
        "agent": log,
    }


JSON_PROTOCOL = """

Server này không có function calling. Mỗi lượt, chỉ trả về MỘT object JSON, không thêm chữ nào khác:
{"tool": "<tên tool>", "args": {...}}
Tool có thể gọi (JSON schema của tham số):
"""


def to_json_mode(messages: list, tool_spec: list) -> list:
    """Hội thoại dạng function calling -> hội thoại chữ thường, cho server không bật tool parser (vd FPT)."""
    out = []
    for m in messages:
        if m["role"] == "system":
            out.append({"role": "system", "content": m["content"] + JSON_PROTOCOL + "\n".join(
                json.dumps({"tool": t["function"]["name"], "description": t["function"]["description"],
                            "args": t["function"]["parameters"]["properties"]}, ensure_ascii=False)
                for t in tool_spec)})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            f = m["tool_calls"][0]["function"]
            out.append({"role": "assistant", "content": json.dumps(
                {"tool": f["name"], "args": json.loads(f.get("arguments") or "{}")}, ensure_ascii=False)})
        elif m["role"] == "tool":
            out.append({"role": "user", "content": f"Kết quả {m['tool_call_id']}: {m['content']}"})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


def parse_json_reply(text: str, turn: int) -> dict:
    """Chữ model trả -> message có tool_calls. Không phải JSON tool call -> giữ là chữ (agent nhắc gọi tool)."""
    start = text.find("{")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:]) if start >= 0 else (None, 0)
    except ValueError:
        obj = None
    if not (isinstance(obj, dict) and isinstance(obj.get("tool"), str)):
        return {"role": "assistant", "content": text}
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": f"{obj['tool']}_{turn}", "type": "function",
        "function": {"name": obj["tool"], "arguments": json.dumps(obj.get("args") or {}, ensure_ascii=False)}}]}


def from_env() -> Callable[[list, list], dict]:
    """LLM điều phối qua API tương thích OpenAI, cần tool calling (vLLM: --enable-auto-tool-choice
    --tool-call-parser hermes cho Qwen). Mặc định dùng chung endpoint/model với VLM."""
    from loanpipe.extract import load_dotenv
    from loanpipe.extract.vlm import http_post
    load_dotenv()
    base = os.environ.get("AGENT_API_BASE") or os.environ.get("VLM_API_BASE")
    key = os.environ.get("AGENT_API_KEY") or os.environ.get("VLM_API_KEY")
    model = os.environ.get("AGENT_MODEL") or os.environ.get("VLM_MODEL")
    if not (base and key and model):
        raise SystemExit("Thiếu AGENT_API_BASE/KEY/MODEL (hoặc VLM_*) trong .env")
    url = base.rstrip("/") + "/chat/completions"
    # USD / 1 triệu token; để trống thì lấy giá VLM (cùng model)
    p_in = float(os.environ.get("AGENT_PRICE_IN") or os.environ.get("VLM_PRICE_IN") or 0)
    p_out = float(os.environ.get("AGENT_PRICE_OUT") or os.environ.get("VLM_PRICE_OUT") or 0)
    mode = os.environ.get("AGENT_TOOL_MODE") or "native"
    if mode not in ("native", "json"):
        raise SystemExit(f"AGENT_TOOL_MODE không hợp lệ: {mode!r} (native | json)")

    def post(payload: dict) -> dict:
        for wait in (2, 5, 15, None):  # 429 / 5xx: chờ rồi thử lại; lỗi khác hoặc hết lượt -> ném ra (agent fallback)
            try:
                return http_post(url, key, payload)
            except urllib.error.HTTPError as e:
                if wait is None or (e.code != 429 and e.code < 500):
                    raise
                time.sleep(wait)

    def llm(messages: list, tool_spec: list) -> dict:
        if mode == "json":
            resp = post({"model": model, "temperature": 0, "max_tokens": 1024,
                         "messages": to_json_mode(messages, tool_spec)})
            msg = parse_json_reply(resp["choices"][0]["message"].get("content") or "", len(messages))
        else:
            resp = post({"model": model, "temperature": 0, "max_tokens": 1024,
                         "messages": messages, "tools": tool_spec, "tool_choice": "auto"})
            msg = resp["choices"][0]["message"]
        u = resp.get("usage") or {}
        return {**msg, "_usage": u,
                "_cost_usd": (u.get("prompt_tokens", 0) * p_in + u.get("completion_tokens", 0) * p_out) / 1e6}
    llm.model = model + ("+json" if mode == "json" else "")  # type: ignore[attr-defined]
    return llm
