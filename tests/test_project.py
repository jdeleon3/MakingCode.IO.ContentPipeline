"""WP-03 acceptance (TDD 12): project create/list/close lifecycle.

`ce project show` is covered by WP-01's `test_store.py` — it's a thin call
into `store.read_project_summary`, not new logic here.
"""

from datetime import date
from pathlib import Path

import pytest

from ce import project, store
from ce.config import EngineConfig
from ce.exit_codes import CEError, ConfigError
from ce.models import ProjectStatus


def _engine_config(repo_path: Path) -> EngineConfig:
    data = {
        "identity": {
            "name": "John",
            "site_url": "https://example.com",
            "site_repo": "~/code/site",
            "timezone": "America/New_York",
        },
        "repos": {
            "allowed": [
                {"name": "some-repo", "path": str(repo_path), "publishable": "full"},
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
    return EngineConfig.model_validate(data)


# --- create -----------------------------------------------------------------


def test_create_writes_project_yaml_and_scaffolds_tree(tmp_path):
    created = project.create(tmp_path, "test-proj")

    assert created.slug == "test-proj"
    assert created.title == "test-proj"  # defaults to slug
    assert created.started_at == date.today()
    assert store.read_project(tmp_path, "test-proj") == created
    assert (tmp_path / "projects" / "test-proj" / "captures" / "audio" / "raw").is_dir()
    assert (tmp_path / "projects" / "test-proj" / "harvest").is_dir()
    assert (tmp_path / "projects" / "test-proj" / "pieces").is_dir()


def test_create_with_explicit_title(tmp_path):
    created = project.create(tmp_path, "test-proj", title="A Real Title")
    assert created.title == "A Real Title"


def test_create_resolves_allowlisted_repo(tmp_path):
    repo_dir = tmp_path / "code" / "x"
    repo_dir.mkdir(parents=True)
    config = _engine_config(repo_dir)

    created = project.create(tmp_path / "data", "test-proj", repo_paths=[repo_dir], config=config)

    assert len(created.repos) == 1
    assert created.repos[0].name == "some-repo"
    assert created.repos[0].path == repo_dir.resolve()


def test_create_rejects_repo_not_in_allowlist(tmp_path):
    allowed_dir = tmp_path / "code" / "allowed"
    allowed_dir.mkdir(parents=True)
    other_dir = tmp_path / "code" / "other"
    other_dir.mkdir(parents=True)
    config = _engine_config(allowed_dir)

    with pytest.raises(CEError, match="not in allowlist"):
        project.create(tmp_path / "data", "test-proj", repo_paths=[other_dir], config=config)


def test_create_duplicate_slug_is_rejected(tmp_path):
    project.create(tmp_path, "test-proj")
    with pytest.raises(CEError, match="already exists"):
        project.create(tmp_path, "test-proj")


def test_create_invalid_slug_raises_readable_error(tmp_path):
    with pytest.raises(ConfigError):
        project.create(tmp_path, "Not A Valid Slug!")


# --- list_all -----------------------------------------------------------------


def test_list_all_returns_projects_sorted_by_slug(tmp_path):
    project.create(tmp_path, "zebra")
    project.create(tmp_path, "alpha")

    listed = project.list_all(tmp_path)
    assert [p.slug for p in listed] == ["alpha", "zebra"]


def test_list_all_filters_by_status(tmp_path):
    project.create(tmp_path, "active-one")
    project.close(tmp_path, "active-one")  # -> complete
    project.create(tmp_path, "still-active")

    only_active = project.list_all(tmp_path, status="active")
    assert [p.slug for p in only_active] == ["still-active"]

    only_complete = project.list_all(tmp_path, status="complete")
    assert [p.slug for p in only_complete] == ["active-one"]


def test_list_all_unknown_status_raises_readable_error(tmp_path):
    with pytest.raises(ConfigError, match="unknown project status"):
        project.list_all(tmp_path, status="not-a-real-status")


# --- close --------------------------------------------------------------------


def test_close_sets_complete_status_by_default(tmp_path):
    project.create(tmp_path, "test-proj")
    closed = project.close(tmp_path, "test-proj")
    assert closed.status == ProjectStatus.COMPLETE
    assert closed.ended_at == date.today()


def test_close_abandoned_sets_abandoned_status(tmp_path):
    project.create(tmp_path, "test-proj")
    closed = project.close(tmp_path, "test-proj", abandoned=True)
    assert closed.status == ProjectStatus.ABANDONED
    assert closed.ended_at == date.today()


def test_close_persists_status_to_disk(tmp_path):
    project.create(tmp_path, "test-proj")
    project.close(tmp_path, "test-proj", abandoned=True)
    reloaded = store.read_project(tmp_path, "test-proj")
    assert reloaded.status == ProjectStatus.ABANDONED
