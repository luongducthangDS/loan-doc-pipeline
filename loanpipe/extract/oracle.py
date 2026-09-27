"""Oracle extractor: trả đúng chuỗi raw đã in lên ảnh (lấy từ manifest), không gọi model.

Dùng để kiểm chứng phần tất định (chuẩn hóa, rule, router, eval) TRƯỚC khi có VLM ở M2.
Kết quả với oracle là CẬN TRÊN: escape rate phải = 0 và recall rule = 100%; nếu không, có bug
ở datagen hoặc rule, không phải ở model.
"""

from __future__ import annotations

from pathlib import Path

from loanpipe.extract import RawExtraction
from loanpipe.schemas import DocType


class OracleExtractor:
    name = "oracle"
    prompt_version = "n/a"

    def __init__(self, manifest: list[dict]):
        self._raw = {(e["bundle_id"], d["doc_id"]): d["fields_raw"] for e in manifest for d in e["docs"]}

    def extract(self, bundle_id: str, doc_id: str, doc_type: DocType, files: list[Path],
                variant: int = 0) -> RawExtraction:
        raw = self._raw[(bundle_id, doc_id)]
        return RawExtraction(fields={k: (v["raw"], v["page"]) for k, v in raw.items()}, n_calls=1)
