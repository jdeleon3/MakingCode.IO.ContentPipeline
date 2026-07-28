"""G1 — repo allowlist (TDD 6.1, 12 WP-05)."""

from pathlib import Path

import pytest

from ce.exit_codes import GateBlocked
from ce.gates import allowlist
from ce.models import PublishableLevel, RepoRef


def _repo(path: Path, name: str = "thing") -> RepoRef:
    return RepoRef(name=name, path=path, publishable=PublishableLevel.FULL)


def test_allowed_repo_passes(tmp_path, make_engine_config):
    repo = _repo(tmp_path)
    config = make_engine_config(repos={"allowed": [repo.model_dump(mode="json")]})
    allowlist.check(repo, config)  # must not raise


def test_repo_outside_allowlist_raises(tmp_path, make_engine_config):
    repo = _repo(tmp_path)
    other = _repo(tmp_path / "elsewhere", name="other")
    config = make_engine_config(repos={"allowed": [other.model_dump(mode="json")]})

    with pytest.raises(GateBlocked, match="G1") as exc_info:
        allowlist.check(repo, config)
    assert "not in allowlist" in exc_info.value.message


def test_empty_allowlist_raises(tmp_path, make_engine_config):
    repo = _repo(tmp_path)
    config = make_engine_config(repos={"allowed": []})
    with pytest.raises(GateBlocked, match="G1"):
        allowlist.check(repo, config)
