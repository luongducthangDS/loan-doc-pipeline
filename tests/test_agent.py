"""Agent tiền kiểm: LLM giả, kiểm vòng tool-calling và các hàng rào an toàn trong loanpipe/agent.py."""

import json
import urllib.error
from pathlib import Path

import pytest

from datagen.build import build_split
from loanpipe.agent import run_bundle_agent
from loanpipe.config import load_rules, load_thresholds
from loanpipe.evaluate import compute_metrics
from loanpipe.extract import RawExtraction
from loanpipe.extract.oracle import OracleExtractor
from loanpipe.pipeline import bundle_input_from_manifest, run_bundle
from loanpipe.schemas import DocType


@pytest.fixture(scope="module")
def manifest():
    return build_split("test", 30, 3, None, images=False)


def baseline(m, e, ex=None):
    return run_bundle(bundle_input_from_manifest(e, Path(".")), ex or OracleExtractor(m), load_rules(),
                      load_thresholds(), check_files=False)


@pytest.fixture(scope="module")
def clean(manifest):
    return next(e for e in manifest if baseline(manifest, e)["decision"]["route"] == "AUTO_PASS")


def run(m, e, llm, ex=None):
    return run_bundle_agent(bundle_input_from_manifest(e, Path(".")), ex or OracleExtractor(m), load_rules(),
                            load_thresholds(), llm, check_files=False)


def call(name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def last_result(messages):
    return json.loads(messages[-1]["content"]) if messages[-1]["role"] == "tool" else None


def careful_policy(messages, tools):
    """Policy 'cẩn thận' viết tay: liệt kê, đọc hết, chạy rule, chốt theo rule; bị từ chối thì REVIEW."""
    done = [m["tool_calls"][0]["function"] for m in messages if m.get("tool_calls")]
    res = last_result(messages)
    if not done:
        return call("list_documents")
    if done[-1]["name"] == "list_documents":
        if res["missing"] or not all(d["readable"] for d in res["documents"]):
            return call("finish", route="REQUEST_MORE", note="thiếu giấy tờ")
        careful_policy.todo = [d["doc_type"] for d in res["documents"]]
    if done[-1]["name"] in ("list_documents", "read_document") and careful_policy.todo:
        return call("read_document", doc_type=careful_policy.todo.pop(0))
    if done[-1]["name"] == "read_document":
        return call("run_rules")
    if done[-1]["name"] == "run_rules":
        st = {r["status"] for r in res["rules"]}
        return call("finish", route="REVIEW" if st != {"pass"} else "AUTO_PASS", note="đã đối chiếu")
    return call("finish", route="REVIEW", note="bị từ chối, chuyển người xem")


def test_careful_agent_matches_workflow(manifest):
    """Đọc đủ thì agent + guardrail cho đúng nhánh của workflow tất định trên mọi bộ."""
    cfg, thr = load_rules(), load_thresholds()
    traces = {e["bundle_id"]: run(manifest, e, careful_policy) for e in manifest}
    for e in manifest:
        assert traces[e["bundle_id"]]["decision"]["route"] == baseline(manifest, e)["decision"]["route"]
        assert traces[e["bundle_id"]]["agent"]["finished_by"] == ("agent" if len(e["docs"]) == 4 else "guardrail")
    m = compute_metrics(manifest, traces, thr)[0]
    assert m["end_to_end"]["escape_rate"] == 0
    json.dumps(traces)


def test_missing_doc_stops_before_llm(manifest):
    """R0 fail được code chốt trước vòng LLM: 0 lượt LLM, 0 lượt VLM, kể cả khi LLM định chọn REVIEW."""
    e = next(e for e in manifest if len(e["docs"]) < 4)

    def must_not_call(messages, tools):
        raise AssertionError("LLM không được gọi khi R0 fail")
    t = run(manifest, e, must_not_call)
    assert t["decision"]["route"] == "REQUEST_MORE" and t["n_calls"] == 0
    assert t["agent"]["turns"] == 0 and t["agent"]["finished_by"] == "guardrail" and t["agent"]["error"] is None


def scripted(*msgs):
    it = iter(msgs)
    return lambda messages, tools: next(it, {"role": "assistant", "content": "hết kịch bản"})


def test_auto_pass_without_reading_is_rejected(manifest, clean):
    t = run(manifest, clean, scripted(call("finish", route="AUTO_PASS", note="trông ổn")))
    assert t["agent"]["steps"][0]["result"]["accepted"] is False
    assert t["agent"]["finished_by"] == "fallback" and t["decision"]["route"] == "REVIEW"


def test_early_review_is_allowed(manifest, clean):
    t = run(manifest, clean, scripted(call("read_document", doc_type="cccd"),
                                      call("finish", route="REVIEW", note="dừng sớm")))
    assert t["decision"]["route"] == "REVIEW" and t["agent"]["finished_by"] == "agent" and t["n_calls"] == 2


class BlurryCccd(OracleExtractor):
    """Ảnh gốc: lượt 2 không đọc được số CCCD (wrong=False) hoặc đọc ra số khác (wrong=True). deskew đọc đúng."""

    def __init__(self, manifest, wrong=False):
        super().__init__(manifest)
        self.wrong = wrong

    def extract(self, bundle_id, doc_id, doc_type, files, variant=0, method=""):
        r = super().extract(bundle_id, doc_id, doc_type, files, variant)
        if doc_type is DocType.CCCD and variant == 1 and not method:
            f = dict(r.fields)
            f["so_cccd"] = ("000000000000" if self.wrong else None, 1)
            return RawExtraction(fields=f)
        return r


def read_all_then(*tail):
    return scripted(*[call("read_document", doc_type=d.value) for d in DocType], *tail)


def test_reread_fills_gap(manifest, clean):
    t = run(manifest, clean, read_all_then(call("read_document", doc_type="cccd", method="deskew"),
                                           call("finish", route="AUTO_PASS", note="đọc lại CCCD đã rõ")),
            BlurryCccd(manifest))
    assert t["agent"]["steps"][4]["result"]["upgraded"] == ["so_cccd"]
    assert t["decision"]["route"] == "AUTO_PASS" and t["agent"]["rejections"] == 0


def test_reread_does_not_resolve_disagreement(manifest, clean):
    """Hai lượt đọc khác nhau có thể là lỗ E1: lượt đọc lại 'đẹp' cũng không được chọn."""
    t = run(manifest, clean, read_all_then(call("read_document", doc_type="cccd", method="deskew"),
                                           call("finish", route="AUTO_PASS", note="ok")),
            BlurryCccd(manifest, wrong=True))
    assert t["agent"]["steps"][4]["result"]["upgraded"] == []
    assert t["agent"]["rejections"] == 1 and t["decision"]["route"] == "REVIEW"


def test_same_read_only_once(manifest, clean):
    t = run(manifest, clean, scripted(call("read_document", doc_type="cccd"), call("read_document", doc_type="cccd")))
    assert "error" in t["agent"]["steps"][1]["result"] and t["n_calls"] == 2


def test_llm_failure_falls_back_to_router(manifest, clean):
    def down(messages, tools):
        raise urllib.error.URLError("down")
    t = run(manifest, clean, down)
    assert t["decision"]["route"] == "REVIEW" and t["agent"]["error"]


def test_json_mode_roundtrip():
    from loanpipe.agent import TOOLS, parse_json_reply, to_json_mode
    msg = parse_json_reply('Tôi sẽ đọc CCCD.\n```json\n{"tool": "read_document", "args": {"doc_type": "cccd"}}\n```', 3)
    f = msg["tool_calls"][0]["function"]
    assert f["name"] == "read_document" and json.loads(f["arguments"]) == {"doc_type": "cccd"}
    assert "tool_calls" not in parse_json_reply("xin chào", 1)
    conv = to_json_mode([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}, msg,
                         {"role": "tool", "tool_call_id": "read_document_3", "content": "{}"}], TOOLS)
    assert [m["role"] for m in conv] == ["system", "user", "assistant", "user"]
    assert '"tool": "finish"' in conv[0]["content"] and all(isinstance(m["content"], str) for m in conv)


def test_list_documents_states_r0_consequence(manifest):
    e = next(e for e in manifest if len(e["docs"]) < 4)
    t = run(manifest, e, scripted(call("list_documents")))
    assert "REQUEST_MORE" in t["agent"]["steps"][0]["result"]["hint"]


def test_from_env_throttles_and_parses_native_tool_calls(monkeypatch):
    """AGENT_RPM giãn các lượt gọi; message trả về giữ nguyên field lạ (vd thought signature của Gemini)."""
    import time

    from loanpipe import agent
    from loanpipe.extract import vlm
    for k, v in {"AGENT_API_BASE": "http://x/v1", "AGENT_API_KEY": "k", "AGENT_MODEL": "gemini-test",
                 "AGENT_TOOL_MODE": "native", "AGENT_RPM": "600"}.items():
        monkeypatch.setenv(k, v)
    reply = {"choices": [{"message": {**call("list_documents"), "extra_content": {"google": {"thought_signature": "s"}}}}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
    monkeypatch.setattr(vlm, "http_post", lambda url, key, payload: reply)
    llm = agent.from_env()
    t0 = time.monotonic()
    a, b = llm([], agent.TOOLS), llm([], agent.TOOLS)
    assert time.monotonic() - t0 >= 0.09  # 600 RPM -> cách nhau >= 0.1 s
    assert a["tool_calls"][0]["function"]["name"] == "list_documents" and "extra_content" in b
    assert a["_usage"]["prompt_tokens"] == 10 and llm.model == "gemini-test"
