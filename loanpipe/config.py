"""Nạp cấu hình rule và ngưỡng từ YAML. Mỗi file có `version`, được ghi vào Decision và run."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass(frozen=True)
class RulesConfig:
    version: str
    salary_patterns: tuple[re.Pattern, ...]
    income_tolerance: float
    statement_max_age_days: int
    statement_min_months: int


@dataclass(frozen=True)
class Thresholds:
    version: str
    critical_fields: dict[str, tuple[str, ...]]
    request_more_min_format_errors: int
    use_self_consistency: bool

    def is_critical(self, doc_type: str, field: str) -> bool:
        return field in self.critical_fields.get(doc_type, ())


@lru_cache
def load_rules(path: Path = CONFIG_DIR / "rules.yaml") -> RulesConfig:
    d = yaml.safe_load(Path(path).read_text("utf-8"))
    return RulesConfig(
        version=d["version"],
        salary_patterns=tuple(re.compile(p) for p in d["salary_patterns"]),
        income_tolerance=float(d["income_tolerance"]),
        statement_max_age_days=int(d["statement_max_age_days"]),
        statement_min_months=int(d["statement_min_months"]),
    )


@lru_cache
def load_thresholds(path: Path = CONFIG_DIR / "thresholds.yaml") -> Thresholds:
    d = yaml.safe_load(Path(path).read_text("utf-8"))
    return Thresholds(
        version=d["version"],
        critical_fields={k: tuple(v) for k, v in d["critical_fields"].items()},
        request_more_min_format_errors=int(d["request_more_min_format_errors"]),
        use_self_consistency=bool(d["use_self_consistency"]),
    )
