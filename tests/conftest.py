"""Shared test fixtures.

`make_engine_config` factors out the "build a fully valid `EngineConfig`"
boilerplate that WP-02's `test_llm_gateway.py` and WP-03's `test_project.py`
each wrote their own copy of — new tests should use this one instead of
adding a fourth copy. Existing copies are left alone; a shared conftest
fixture doesn't require touching already-closed WPs' test files to adopt.
"""

from __future__ import annotations

from typing import Any

import pytest

from ce.config import EngineConfig


def _base_engine_config_dict() -> dict[str, Any]:
    return {
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
            "vocabulary": ["DuckDB", "Astro", "Cloudflare"],
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


@pytest.fixture
def make_engine_config():
    """Returns a `(**overrides) -> EngineConfig` factory. Overrides merge
    one level deep, e.g. `make_engine_config(llm={"budget": {...}})` keeps
    the default `llm.models`/`llm.retry` and replaces only `llm.budget`."""

    def _make(**overrides: Any) -> EngineConfig:
        data = _base_engine_config_dict()
        for key, value in overrides.items():
            data[key] = {**data[key], **value} if isinstance(value, dict) else value
        return EngineConfig.model_validate(data)

    return _make
