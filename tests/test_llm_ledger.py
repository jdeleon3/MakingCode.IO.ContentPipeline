"""WP-02 acceptance: append-only cost ledger, month-to-date total, per-prompt breakdown."""

from datetime import UTC, datetime

from ce.llm import ledger


def _record(**overrides):
    defaults = dict(
        ts=datetime(2026, 7, 26, 9, 4, 11, tzinfo=UTC),
        prompt="article_draft",
        version=3,
        model="claude-sonnet-5",
        in_tokens=8200,
        out_tokens=1900,
        usd=0.0512,
        piece="pc-0007",
        cache_hit=False,
    )
    defaults.update(overrides)
    return ledger.LedgerRecord(**defaults)


def test_append_then_read_all_round_trips(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, _record())
    ledger.append(path, _record(prompt="article_grade", usd=0.02))

    records = ledger.read_all(path)
    assert len(records) == 2
    assert records[0].in_tokens == 8200
    assert records[0].out_tokens == 1900


def test_ledger_record_uses_in_out_field_names_on_disk(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, _record())
    line = path.read_text(encoding="utf-8").strip()
    assert '"in": 8200' in line
    assert '"out": 1900' in line


def test_read_all_on_missing_ledger_is_empty(tmp_path):
    assert ledger.read_all(tmp_path / "does-not-exist.jsonl") == []


def test_month_to_date_usd_filters_by_month(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, _record(ts=datetime(2026, 7, 1, tzinfo=UTC), usd=1.0))
    ledger.append(path, _record(ts=datetime(2026, 7, 15, tzinfo=UTC), usd=2.0))
    ledger.append(path, _record(ts=datetime(2026, 8, 1, tzinfo=UTC), usd=5.0))

    records = ledger.read_all(path)
    assert ledger.month_to_date_usd(records, "2026-07") == 3.0
    assert ledger.month_to_date_usd(records, "2026-08") == 5.0
    assert ledger.month_to_date_usd(records, "2026-09") == 0.0


def test_per_prompt_breakdown_aggregates_and_sorts_by_spend(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, _record(prompt="a", usd=0.5, in_tokens=100, out_tokens=50))
    ledger.append(path, _record(prompt="a", usd=0.5, in_tokens=100, out_tokens=50))
    ledger.append(path, _record(prompt="b", usd=2.0, in_tokens=500, out_tokens=200))

    breakdown = ledger.per_prompt_breakdown(ledger.read_all(path), "2026-07")
    assert [s.prompt for s in breakdown] == ["b", "a"]
    a = next(s for s in breakdown if s.prompt == "a")
    assert a.calls == 2
    assert a.in_tokens == 200
    assert a.usd == 1.0


def test_per_prompt_breakdown_excludes_other_months(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, _record(ts=datetime(2026, 8, 1, tzinfo=UTC)))
    breakdown = ledger.per_prompt_breakdown(ledger.read_all(path), "2026-07")
    assert breakdown == []
