"""G1 — repo allowlist (TDD 6.1; ADR-005 non-bypassable, not configurable).

Runs before any git subprocess touches a repo. WP-03's `project._resolve_repo`
already fail-fasts an unconfigured `--repo` at `ce project new` time, but that
check is against whatever `config/engine.yml` said *then* — the allowlist can
change afterwards (a repo removed from `repos.allowed`, or `project.yml`
hand-edited), and TDD 6.1 scopes G1 as running "before any git access", i.e.
at harvest time. This is that check, re-run against the *current* config
immediately before `harvest/git.py` runs a single git command.
"""

from __future__ import annotations

from ce.config import EngineConfig
from ce.exit_codes import GateBlocked
from ce.models import RepoRef


def check(repo: RepoRef, config: EngineConfig) -> None:
    """Raise `GateBlocked` if `repo.path` is not in `config.repos.allowed`.

    Comparison is on resolved absolute paths. `RepoRef.path` is normalised by
    `models.expand_and_resolve` at construction (both here and on
    `config.repos.allowed` entries), so a symlink or `..` segment can't slip
    a disallowed directory past this check by spelling it differently
    (TDD 6.1: "no symlink or `..` escapes").
    """
    allowed_paths = {r.path for r in config.repos.allowed}
    if repo.path not in allowed_paths:
        raise GateBlocked(
            "G1",
            f"repo not in allowlist: {repo.path}",
            hint="add it to config/engine.yml under repos.allowed, then retry",
        )
