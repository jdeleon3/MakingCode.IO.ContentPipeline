"""Project lifecycle (TDD 12 WP-03): `ce project new|list|show|close`.

Command bodies live here rather than in `cli.py` — `cli.py`'s own docstring
says it is registration-only (TDD §7), and this is the one place that turns
a slug plus CLI flags into on-disk project state, mirroring how `doctor.py`
holds `doctor_cmd`'s real logic.

`ce project show` isn't here: its read/format logic already lives in
`store.format_project_summary` / `store.read_project_summary` (WP-01), and
this module just calls those directly rather than duplicating them.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import ValidationError

from ce import store
from ce.config import EngineConfig, load_engine_config
from ce.exit_codes import CEError, ConfigError
from ce.models import Project, ProjectStatus, RepoRef


def _resolve_repo(config: EngineConfig, raw_path: Path) -> RepoRef:
    """Match a `--repo` path against `config.repos.allowed` (TDD 6.1 G1).

    This is a fail-fast usability check at project-creation time, not the G1
    gate itself — G1 is scoped in the TDD as running "before any git access"
    and is implemented in WP-05's `gates/allowlist.py`. Catching an
    unconfigured repo here means a typo surfaces immediately instead of
    weeks later at harvest.
    """
    resolved = raw_path.expanduser().resolve()
    for candidate in config.repos.allowed:
        if candidate.path == resolved:
            return candidate
    raise CEError(
        f"repo not in allowlist: {resolved}",
        hint="add it to config/engine.yml under repos.allowed, then retry",
    )


def create(
    data_root: Path,
    slug: str,
    *,
    title: str | None = None,
    repo_paths: list[Path] | None = None,
    config: EngineConfig | None = None,
) -> Project:
    """`ce project new`. Raises `CEError` if `slug` is already taken."""
    if store.project_exists(data_root, slug):
        raise CEError(f"project {slug!r} already exists")

    repos: list[RepoRef] = []
    if repo_paths:
        config = config or load_engine_config()
        repos = [_resolve_repo(config, p) for p in repo_paths]

    try:
        project = Project(
            slug=slug,
            title=title or slug,
            started_at=date.today(),
            repos=repos,
        )
    except ValidationError as exc:
        raise ConfigError(f"invalid project: {exc}") from exc

    store.write_project(data_root, project)
    store.scaffold_project_tree(data_root, slug)
    return project


def list_all(data_root: Path, status: str | None = None) -> list[Project]:
    """`ce project list [--status S]`."""
    projects = store.list_projects(data_root)
    if status is not None:
        try:
            target = ProjectStatus(status)
        except ValueError as exc:
            raise ConfigError(f"unknown project status {status!r}") from exc
        projects = [p for p in projects if p.status == target]
    return sorted(projects, key=lambda p: p.slug)


def close(data_root: Path, slug: str, *, abandoned: bool = False) -> Project:
    """`ce project close [--abandoned]`."""
    project = store.read_project(data_root, slug)
    project.status = ProjectStatus.ABANDONED if abandoned else ProjectStatus.COMPLETE
    project.ended_at = date.today()
    store.write_project(data_root, project)
    return project
