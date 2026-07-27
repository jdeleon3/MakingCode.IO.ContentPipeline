"""Cost accounting: `data/ledger.jsonl`, an append-only log of paid LLM calls
(TDD 10.1). Cache hits never appear here — see `cache.py`.

Backs both the budget governor (`gateway.Gateway._check_budget`) and
`ce cost` (month-to-date total, per-prompt breakdown).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ce.exit_codes import ConfigError


class LedgerRecord(BaseModel):
    """One paid call. Field names mirror the TDD 10.1 `ledger.jsonl` example
    exactly (`in`/`out`), which collide with Python keywords/builtins as
    attribute names — aliased rather than renamed so the on-disk shape
    matches the spec.
    """

    model_config = ConfigDict(populate_by_name=True)

    ts: datetime
    prompt: str
    version: int
    model: str
    in_tokens: int = Field(alias="in")
    out_tokens: int = Field(alias="out")
    usd: float
    piece: str | None = None
    cache_hit: bool


def append(ledger_path: Path, record: LedgerRecord) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.model_dump(mode="json", by_alias=True)) + "\n")


def read_all(ledger_path: Path) -> list[LedgerRecord]:
    if not ledger_path.exists():
        return []
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"could not read {ledger_path}: {exc}") from exc

    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(LedgerRecord.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConfigError(f"{ledger_path}: malformed record: {exc}") from exc
    return records


def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def current_month(now: datetime | None = None) -> str:
    return month_key(now or datetime.now(UTC))


def month_to_date_usd(
    records: list[LedgerRecord], month: str | None = None, *, now: datetime | None = None
) -> float:
    target = month or current_month(now)
    return sum(r.usd for r in records if month_key(r.ts) == target)


@dataclass
class PromptCostSummary:
    prompt: str
    calls: int
    in_tokens: int
    out_tokens: int
    usd: float


def per_prompt_breakdown(
    records: list[LedgerRecord], month: str | None = None, *, now: datetime | None = None
) -> list[PromptCostSummary]:
    """Per-prompt totals for one calendar month, highest spend first."""
    target = month or current_month(now)
    totals: dict[str, PromptCostSummary] = {}
    for r in records:
        if month_key(r.ts) != target:
            continue
        summary = totals.setdefault(r.prompt, PromptCostSummary(r.prompt, 0, 0, 0, 0.0))
        summary.calls += 1
        summary.in_tokens += r.in_tokens
        summary.out_tokens += r.out_tokens
        summary.usd += r.usd
    return sorted(totals.values(), key=lambda s: s.usd, reverse=True)
