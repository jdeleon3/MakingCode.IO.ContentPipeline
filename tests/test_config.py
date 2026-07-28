"""WP-01 acceptance: engine.yml / platform config load, validate, and resolve paths."""

from pathlib import Path

import pytest
import yaml

from ce.config import (
    EngineConfig,
    load_engine_config,
    load_platform_config,
)
from ce.exit_codes import ConfigError


def _valid_engine_dict(**overrides) -> dict:
    data = {
        "identity": {
            "name": "John",
            "site_url": "https://example.com",
            "site_repo": "~/code/site",
            "timezone": "America/New_York",
        },
        "repos": {
            "allowed": [
                {"name": "content-engine", "path": "~/code/content-engine", "publishable": "full"},
                {
                    "name": "client-thing",
                    "path": "~/code/client-thing",
                    "publishable": "lessons-only",
                },
            ]
        },
        "llm": {
            "provider": "anthropic",
            "models": {
                "reasoning": "claude-opus-5",
                "default": "claude-sonnet-5",
                "cheap": "claude-haiku-4-5",
            },
            "budget": {"monthly_usd": 20, "per_run_usd": 2.0, "on_exceed": "halt"},
            "retry": {"max_attempts": 4, "backoff_base_sec": 2},
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
                "hook": 0.30,
                "evidence": 0.30,
                "specificity": 0.20,
                "voice": 0.10,
                "cta": 0.10,
            },
        },
        "harvest": {
            "git": {"lookback_days": 60, "min_significance": 2},
            "research": {"max_sources": 8},
            "inventory": {"min_briefs": 6, "max_briefs": 8},
        },
        "utm": {"template": "?utm_source={platform}&utm_medium=social&utm_campaign={slug}"},
        "analytics": {
            "umami": {"api_url": "https://umami.example.com", "website_id": "site-1"},
        },
    }
    data.update(overrides)
    return data


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_load_engine_config_reads_the_tdd_8_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    path = _write_yaml(tmp_path / "engine.yml", _valid_engine_dict())

    config = load_engine_config(path)

    assert isinstance(config, EngineConfig)
    assert config.identity.name == "John"
    assert config.llm.models.default == "claude-sonnet-5"
    assert config.produce.grade_weights.hook == 0.30


def test_engine_config_expands_and_resolves_repo_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    path = _write_yaml(tmp_path / "engine.yml", _valid_engine_dict())

    config = load_engine_config(path)

    for repo in config.repos.allowed:
        assert repo.path.is_absolute()
        assert str(repo.path).startswith(str(tmp_path))
    assert config.identity.site_repo.is_absolute()


def test_invalid_engine_config_names_the_field(tmp_path):
    bad = _valid_engine_dict()
    bad["llm"]["budget"]["monthly_usd"] = "not-a-number"
    path = _write_yaml(tmp_path / "engine.yml", bad)

    with pytest.raises(ConfigError, match="monthly_usd"):
        load_engine_config(path)


def test_engine_config_rejects_unknown_top_level_keys(tmp_path):
    bad = _valid_engine_dict()
    bad["not_a_real_section"] = {"whatever": 1}
    path = _write_yaml(tmp_path / "engine.yml", bad)

    with pytest.raises(ConfigError, match="not_a_real_section"):
        load_engine_config(path)


def test_inventory_max_briefs_must_be_at_least_min(tmp_path):
    bad = _valid_engine_dict()
    bad["harvest"]["inventory"] = {"min_briefs": 8, "max_briefs": 6}
    path = _write_yaml(tmp_path / "engine.yml", bad)

    with pytest.raises(ConfigError, match="max_briefs"):
        load_engine_config(path)


def test_research_provider_defaults_to_gemini(tmp_path):
    path = _write_yaml(tmp_path / "engine.yml", _valid_engine_dict())
    config = load_engine_config(path)
    assert config.harvest.research.provider == "gemini"


@pytest.mark.parametrize("provider", ["duckduckgo", "gemini", "perplexity"])
def test_research_provider_accepts_each_swappable_backend(tmp_path, provider):
    data = _valid_engine_dict()
    data["harvest"]["research"] = {"max_sources": 8, "provider": provider}
    path = _write_yaml(tmp_path / "engine.yml", data)
    config = load_engine_config(path)
    assert config.harvest.research.provider == provider


def test_research_provider_rejects_unknown_backend(tmp_path):
    data = _valid_engine_dict()
    data["harvest"]["research"] = {"max_sources": 8, "provider": "bing"}
    path = _write_yaml(tmp_path / "engine.yml", data)
    with pytest.raises(ConfigError, match="provider"):
        load_engine_config(path)


def test_missing_engine_config_file_is_a_readable_error(tmp_path):
    with pytest.raises(ConfigError, match="could not read"):
        load_engine_config(tmp_path / "does-not-exist.yml")


def test_non_mapping_yaml_is_a_readable_error(tmp_path):
    path = tmp_path / "engine.yml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_engine_config(path)


# --- platform config ---------------------------------------------------------


def _valid_linkedin_dict(**overrides) -> dict:
    data = {
        "name": "linkedin",
        "max_chars": 3000,
        "hook_chars": 200,
        "links_in_body": False,
        "supports_markdown": False,
        "allow_unicode_styling": False,
        "line_break_style": "double",
        "assets": {"image": {"w": 1200, "h": 1200, "formats": ["png"]}},
        "extras": ["first_comment"],
    }
    data.update(overrides)
    return data


def test_load_platform_config_reads_linkedin_yml(tmp_path):
    path = _write_yaml(tmp_path / "linkedin.yml", _valid_linkedin_dict())
    platform = load_platform_config(path)
    assert platform.name == "linkedin"
    assert platform.assets.image.w == 1200


def test_invalid_platform_config_names_the_field(tmp_path):
    bad = _valid_linkedin_dict(line_break_style="triple")
    path = _write_yaml(tmp_path / "linkedin.yml", bad)
    with pytest.raises(ConfigError, match="line_break_style"):
        load_platform_config(path)
