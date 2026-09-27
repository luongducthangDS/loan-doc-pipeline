"""Bước 3: trích xuất. Model CHỈ xuất hiện ở bước này (spec mục 6).

Mọi extractor trả về raw (chuỗi chép nguyên văn) theo từng field; chuẩn hóa và confidence do code
tính ở `loanpipe.validate`. Mỗi lần gọi chỉ thấy ĐÚNG MỘT giấy tờ: đưa nhiều giấy tờ vào một prompt,
model có thể "sửa" tên trên đơn cho khớp CCCD và che mất sai lệch thật.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from loanpipe.schemas import DocType


@dataclass
class RawExtraction:
    fields: dict[str, tuple[str | None, int | None]]  # field -> (raw, page)
    latency_ms: int = 0
    n_calls: int = 1
    cost_usd: float = 0.0
    model_output: str | None = None  # output thô của model, ghi vào trace
    errors: list[str] = field(default_factory=list)


class Extractor(Protocol):
    name: str
    prompt_version: str

    def extract(self, bundle_id: str, doc_id: str, doc_type: DocType, files: list[Path],
                variant: int = 0) -> RawExtraction:
        """variant=0: ảnh gốc; variant=1: ảnh tiền xử lý khác đi (tín hiệu tự nhất quán)."""
        ...


def get_extractor(name: str, **kw) -> Extractor:
    if name == "oracle":
        from loanpipe.extract.oracle import OracleExtractor
        return OracleExtractor(**kw)
    raise ValueError(f"extractor chưa có: {name!r}. VLM thêm ở M2 (xem README).")
