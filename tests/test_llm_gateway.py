"""WP-02 acceptance (TDD 12): identical call twice caches, schema failure repairs
once then raises, budget exceeded raises BudgetExceeded (exit 3).

Uses a fake `LLMClient` (dependency injection, per `gateway.LLMClient`) instead of
a pre-primed `tests/fixtures/llm-cache/` + `pytest --refresh-llm-cache` flag — see
STATUS.md deviations. Zero network calls, fully deterministic.
"""

import json
from pathlib import Path

import anthropic
import httpx
import pytest

from ce.config import EngineConfig
from ce.exit_codes import BudgetExceeded, Exit, SchemaValidationError
from ce.llm.gateway import Gateway, ProviderResponse

PROMPTS_DIR = Path("prompts")


def _engine_config(**overrides) -> EngineConfig:
    data = {
        "identity": {
            "name": "John",
            "site_url": "https://example.com",
            "site_repo": "~/code/site",
            "timezone": "America/New_York",
        },
        "repos": {"allowed": []},
        "llm": {
            "provider": "anthropic",
            "models": {
                "reasoning": "claude-opus-5",
                "default": "claude-sonnet-5",
                "cheap": "claude-haiku-4-5",
            },
            "budget": {"monthly_usd": 20, "per_run_usd": 2.0, "on_exceed": "halt"},
            "retry": {"max_attempts": 3, "backoff_base_sec": 0.001},
        },
        "transcription": {
            "provider": "openai",
            "model": "gpt-4o-mini-transcribe",
            "vocabulary": [],
            "preprocess": {"silence_threshold_db": -40, "silence_min_sec": 1.5, "loudnorm": True},
        },
        "embeddings": {"provider": "openai", "model": "text-embedding-3-small"},
        "gates": {
            "allowlist": "hard_fail",
            "secrets": "hard_fail",
            "dedupe": {"threshold": 0.88, "scope_days": 365},
            "claims": {"enabled": True, "block_on_unverifiable": True},
        },
        "produce": {
            "min_grade": 8.0,
            "max_attempts": 3,
            "grade_weights": {
                "hook": 0.3,
                "evidence": 0.3,
                "specificity": 0.2,
                "voice": 0.1,
                "cta": 0.1,
            },
        },
        "harvest": {
            "git": {"lookback_days": 60, "min_significance": 2},
            "research": {"max_sources": 8},
            "inventory": {"min_briefs": 6, "max_briefs": 8},
        },
        "utm": {"template": "?utm_source={platform}&utm_medium=social&utm_campaign={slug}"},
    }
    for key, value in overrides.items():
        data[key] = {**data[key], **value} if isinstance(value, dict) else value
    return EngineConfig.model_validate(data)


class FakeLLMClient:
    """Queue of canned responses (or exceptions), one per call. Records every
    call's args so tests can assert on invocation count and content."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, model, system, user, max_tokens):
        self.calls.append(
            {"model": model, "system": system, "user": user, "max_tokens": max_tokens}
        )
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _echo_response(text="hello world", in_tokens=10, out_tokens=5):
    return ProviderResponse(content=text, in_tokens=in_tokens, out_tokens=out_tokens)


# --- caching (TDD 12 WP-02: "identical call twice -> one ledger entry, second cache_hit=True") ---


def test_identical_call_twice_hits_cache_second_time(tmp_path):
    client = FakeLLMClient([_echo_response()])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    first = gw.complete("_wp02_echo", {"message": "hello world"}, tier="cheap")
    second = gw.complete("_wp02_echo", {"message": "hello world"}, tier="cheap")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(client.calls) == 1  # provider only ever called once

    from ce.llm import ledger

    records = ledger.read_all(tmp_path / "ledger.jsonl")
    assert len(records) == 1  # cache hit writes no ledger entry


def test_no_cache_flag_bypasses_cache(tmp_path):
    client = FakeLLMClient([_echo_response(), _echo_response()])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    gw.complete("_wp02_echo", {"message": "hi"}, tier="cheap", cache=False)
    gw.complete("_wp02_echo", {"message": "hi"}, tier="cheap", cache=False)

    assert len(client.calls) == 2


def test_different_vars_are_different_cache_entries(tmp_path):
    client = FakeLLMClient([_echo_response(text="a"), _echo_response(text="b")])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    r1 = gw.complete("_wp02_echo", {"message": "one"}, tier="cheap")
    r2 = gw.complete("_wp02_echo", {"message": "two"}, tier="cheap")

    assert len(client.calls) == 2
    assert r1.content != r2.content


# --- schema validation + one repair (TDD 12 WP-02 / 10.1 step 6) ------------

_SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string"}, "summary": {"type": "string"}},
    "required": ["topic", "summary"],
    "additionalProperties": False,
}


def test_schema_validation_success_on_first_attempt(tmp_path):
    valid = json.dumps({"topic": "x", "summary": "y"})
    client = FakeLLMClient([_echo_response(text=valid)])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    result = gw.complete("_wp02_structured", {"topic": "x"}, tier="default", schema=_SCHEMA)

    assert result.parsed == {"topic": "x", "summary": "y"}
    assert len(client.calls) == 1


def test_schema_validation_failure_triggers_exactly_one_repair_then_succeeds(tmp_path):
    invalid = "not json at all"
    valid = json.dumps({"topic": "x", "summary": "y"})
    client = FakeLLMClient([_echo_response(text=invalid), _echo_response(text=valid)])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    result = gw.complete("_wp02_structured", {"topic": "x"}, tier="default", schema=_SCHEMA)

    assert result.parsed == {"topic": "x", "summary": "y"}
    assert len(client.calls) == 2
    assert "validation" in client.calls[1]["user"].lower()


def test_schema_validation_failure_after_repair_raises(tmp_path):
    invalid = "still not json"
    client = FakeLLMClient([_echo_response(text=invalid), _echo_response(text=invalid)])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    with pytest.raises(SchemaValidationError):
        gw.complete("_wp02_structured", {"topic": "x"}, tier="default", schema=_SCHEMA)

    assert len(client.calls) == 2  # exactly one repair attempt, then raise


def test_schema_validation_failure_still_records_spend(tmp_path):
    """Both the original and the failed-repair call are real, billed API calls —
    losing that spend from the ledger would make `ce cost` and the budget
    governor blind to real money spent (caught in WP-02 review)."""
    from ce.llm import ledger

    invalid = "still not json"
    client = FakeLLMClient(
        [
            _echo_response(text=invalid, in_tokens=10, out_tokens=5),
            _echo_response(text=invalid, in_tokens=20, out_tokens=8),
        ]
    )
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    with pytest.raises(SchemaValidationError):
        gw.complete("_wp02_structured", {"topic": "x"}, tier="default", schema=_SCHEMA)

    records = ledger.read_all(tmp_path / "ledger.jsonl")
    assert len(records) == 1
    assert records[0].in_tokens == 30  # 10 + 20, both calls' tokens combined
    assert records[0].out_tokens == 13  # 5 + 8
    assert records[0].usd > 0
    assert gw._run_usd == records[0].usd


# --- budget governor (TDD 6.5, 12 WP-02: "budget exceeded raises BudgetExceeded exit 3") ---


def test_budget_exceeded_halts_by_default(tmp_path):
    config = _engine_config(
        llm={"budget": {"monthly_usd": 0.00001, "per_run_usd": 2.0, "on_exceed": "halt"}}
    )
    client = FakeLLMClient([_echo_response()])
    gw = Gateway(config, data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    # First call spends more than the tiny monthly cap.
    gw.complete("_wp02_echo", {"message": "one"}, tier="cheap")

    with pytest.raises(BudgetExceeded) as excinfo:
        gw.complete("_wp02_echo", {"message": "two"}, tier="cheap")
    assert excinfo.value.exit_code == Exit.BUDGET_EXCEEDED


def test_budget_exceeded_degrades_to_cheap_tier(tmp_path):
    config = _engine_config(
        llm={"budget": {"monthly_usd": 0.0001, "per_run_usd": 2.0, "on_exceed": "degrade"}}
    )
    client = FakeLLMClient([_echo_response(), _echo_response()])
    gw = Gateway(config, data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    gw.complete("_wp02_echo", {"message": "one"}, tier="default")
    second = gw.complete("_wp02_echo", {"message": "two"}, tier="default")

    assert second.model == config.llm.models.cheap


def test_cache_hit_is_not_blocked_by_exceeded_budget(tmp_path):
    """A free cache hit must not be refused just because the budget is spent."""
    config = _engine_config(
        llm={"budget": {"monthly_usd": 0.00001, "per_run_usd": 2.0, "on_exceed": "halt"}}
    )
    client = FakeLLMClient([_echo_response()])
    gw = Gateway(config, data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    gw.complete("_wp02_echo", {"message": "one"}, tier="cheap")  # spends the budget
    cached = gw.complete("_wp02_echo", {"message": "one"}, tier="cheap")  # same call again

    assert cached.cache_hit is True
    assert len(client.calls) == 1


# --- retry on 429/5xx (TDD 10.1 step 5) -------------------------------------


def _api_status_error(status: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request)
    return anthropic.APIStatusError("boom", response=response, body=None)


def test_retries_on_5xx_then_succeeds(tmp_path):
    client = FakeLLMClient([_api_status_error(503), _echo_response()])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    result = gw.complete("_wp02_echo", {"message": "hi"}, tier="cheap")

    assert result.content == "hello world"
    assert len(client.calls) == 2


def test_exhausts_retries_then_raises(tmp_path):
    client = FakeLLMClient([_api_status_error(500), _api_status_error(500), _api_status_error(500)])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    with pytest.raises(anthropic.APIStatusError):
        gw.complete("_wp02_echo", {"message": "hi"}, tier="cheap")

    assert len(client.calls) == 3  # config.llm.retry.max_attempts


def test_does_not_retry_on_non_retryable_status(tmp_path):
    client = FakeLLMClient([_api_status_error(400)])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    with pytest.raises(anthropic.APIStatusError):
        gw.complete("_wp02_echo", {"message": "hi"}, tier="cheap")

    assert len(client.calls) == 1


def _connection_error() -> anthropic.APIConnectionError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(message="timed out", request=request)


def test_retries_on_read_timeout_then_succeeds(tmp_path):
    """Regression: `APIConnectionError` (covers `APITimeoutError`) isn't an
    `APIStatusError`, so it needs its own except clause in
    `_call_with_retry` or it isn't retried at all -- a real production
    failure on a slow reasoning-tier response."""
    client = FakeLLMClient([_connection_error(), _echo_response()])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    result = gw.complete("_wp02_echo", {"message": "hi"}, tier="cheap")

    assert result.content == "hello world"
    assert len(client.calls) == 2


def test_exhausts_retries_on_repeated_timeout_then_raises(tmp_path):
    client = FakeLLMClient([_connection_error(), _connection_error(), _connection_error()])
    gw = Gateway(_engine_config(), data_root=tmp_path, prompts_dir=PROMPTS_DIR, client=client)

    with pytest.raises(anthropic.APIConnectionError):
        gw.complete("_wp02_echo", {"message": "hi"}, tier="cheap")

    assert len(client.calls) == 3  # config.llm.retry.max_attempts
