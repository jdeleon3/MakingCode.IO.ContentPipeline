"""Filesystem CRUD for `data/` (TDD 5.4, 7): path resolution, YAML I/O, and
resumability via `_manifest.json` (TDD §0, §7).

This is the only module that should touch `data/` directly. Every read
validates through the models in `models.py`; every write serialises through
them too, so a stray hand-edit that breaks a schema is caught here, not three
modules downstream.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from ce.exit_codes import ConfigError
from ce.models import Brief, Capture, Piece, PostRecord, Project, Rendition

# ---------------------------------------------------------------------------
# Generic YAML I/O
# ---------------------------------------------------------------------------


def read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    return yaml.safe_load(text)


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def _load_model(model: type[BaseModel], path: Path) -> Any:
    data = read_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _dump_model(model: BaseModel, path: Path) -> None:
    write_yaml(path, model.model_dump(mode="json"))


def _load_model_list(model: type[BaseModel], path: Path) -> list[Any]:
    data = read_yaml(path) or []
    if not isinstance(data, list):
        raise ConfigError(
            f"{path}: expected a YAML list at the top level, got {type(data).__name__}"
        )
    try:
        return [model.model_validate(item) for item in data]
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _dump_model_list(models: list[BaseModel], path: Path) -> None:
    write_yaml(path, [m.model_dump(mode="json") for m in models])


# ---------------------------------------------------------------------------
# Path conventions (TDD §7 — load-bearing, keep in sync with the layout there)
# ---------------------------------------------------------------------------


def project_dir(data_root: Path, slug: str) -> Path:
    return data_root / "projects" / slug


def project_yaml_path(data_root: Path, slug: str) -> Path:
    return project_dir(data_root, slug) / "project.yml"


def captures_dir(data_root: Path, slug: str) -> Path:
    return project_dir(data_root, slug) / "captures"


def harvest_dir(data_root: Path, slug: str) -> Path:
    return project_dir(data_root, slug) / "harvest"


def briefs_yaml_path(data_root: Path, slug: str) -> Path:
    return harvest_dir(data_root, slug) / "briefs.yml"


def pieces_dir(data_root: Path, slug: str) -> Path:
    return project_dir(data_root, slug) / "pieces"


def piece_dir(data_root: Path, slug: str, piece_id: str) -> Path:
    return pieces_dir(data_root, slug) / piece_id


def piece_yaml_path(data_root: Path, slug: str, piece_id: str) -> Path:
    return piece_dir(data_root, slug, piece_id) / "piece.yml"


def grades_json_path(data_root: Path, slug: str, piece_id: str) -> Path:
    return piece_dir(data_root, slug, piece_id) / "grades.json"


def verification_json_path(data_root: Path, slug: str, piece_id: str) -> Path:
    return piece_dir(data_root, slug, piece_id) / "verification.json"


def renditions_dir(data_root: Path, slug: str, piece_id: str) -> Path:
    return piece_dir(data_root, slug, piece_id) / "renditions"


def rendition_yaml_path(data_root: Path, slug: str, piece_id: str, platform: str) -> Path:
    return renditions_dir(data_root, slug, piece_id) / f"{platform}.yml"


def posted_yaml_path(data_root: Path) -> Path:
    return data_root / "posted.yml"


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


def read_project(data_root: Path, slug: str) -> Project:
    return _load_model(Project, project_yaml_path(data_root, slug))


def write_project(data_root: Path, project: Project) -> None:
    _dump_model(project, project_yaml_path(data_root, project.slug))


def project_exists(data_root: Path, slug: str) -> bool:
    return project_yaml_path(data_root, slug).exists()


def list_projects(data_root: Path) -> list[Project]:
    root = data_root / "projects"
    if not root.exists():
        return []
    slugs = [p.parent.name for p in root.glob("*/project.yml")]
    return [read_project(data_root, slug) for slug in slugs]


def scaffold_project_tree(data_root: Path, slug: str) -> None:
    """Create the directories a fresh project needs (TDD §7) — `project.yml`
    itself is written separately via `write_project`. `harvest/` and
    `pieces/` start empty; their contents are written by later WPs (harvest,
    produce) once there is something to put there.
    """
    base = project_dir(data_root, slug)
    for sub in (
        "captures/audio/raw",
        "captures/audio/transcript",
        "captures/screens",
        "captures/screencast",
        "harvest",
        "pieces",
    ):
        (base / sub).mkdir(parents=True, exist_ok=True)

    friction = base / "captures" / "friction.md"
    if not friction.exists():
        friction.write_text("# Friction log\n\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Capture — one file per capture under captures/, named `<id>.capture.yml`
# ---------------------------------------------------------------------------


def capture_yaml_path(data_root: Path, slug: str, capture_id: str) -> Path:
    return captures_dir(data_root, slug) / f"{capture_id}.capture.yml"


def read_capture(data_root: Path, slug: str, capture_id: str) -> Capture:
    return _load_model(Capture, capture_yaml_path(data_root, slug, capture_id))


def write_capture(data_root: Path, capture: Capture) -> None:
    _dump_model(capture, capture_yaml_path(data_root, capture.project, capture.id))


def list_captures(data_root: Path, slug: str) -> list[Capture]:
    directory = captures_dir(data_root, slug)
    if not directory.exists():
        return []
    return [_load_model(Capture, p) for p in sorted(directory.glob("*.capture.yml"))]


def generate_capture_id(data_root: Path, slug: str, captured_at: datetime) -> str:
    """A human-readable, collision-safe capture id: `cap-YYYYMMDD-HHMMSS`,
    with a `-N` suffix appended only if that id is already taken — multiple
    captures ingested within the same second (bulk import, or several
    `ce capture` calls back to back) would otherwise silently overwrite
    each other's `.capture.yml` file.
    """
    base = f"cap-{captured_at:%Y%m%d-%H%M%S}"
    candidate = base
    suffix = 2
    while capture_yaml_path(data_root, slug, candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


# ---------------------------------------------------------------------------
# Brief — array in harvest/briefs.yml
# ---------------------------------------------------------------------------


def read_briefs(data_root: Path, slug: str) -> list[Brief]:
    path = briefs_yaml_path(data_root, slug)
    if not path.exists():
        return []
    return _load_model_list(Brief, path)


def write_briefs(data_root: Path, slug: str, briefs: list[Brief]) -> None:
    _dump_model_list(briefs, briefs_yaml_path(data_root, slug))


def find_brief(data_root: Path, brief_id: str) -> tuple[Project, Brief] | None:
    """Scans every project for a brief with this id.

    TDD 9's CLI contract gives `ce brief select <brief-id>` no `--project`
    option, so the project has to be discovered rather than supplied. Brief
    ids are only unique *within* a project (`br-01`, `br-02`, ... restarts
    at 1 for every project — see `harvest/inventory.py::generate`), so an id
    that matches in more than one project is a genuine ambiguity, not
    something to resolve by silently picking the first hit.
    """
    matches = [
        (project, brief)
        for project in list_projects(data_root)
        for brief in read_briefs(data_root, project.slug)
        if brief.id == brief_id
    ]
    if len(matches) > 1:
        raise ConfigError(
            f"brief id {brief_id!r} is ambiguous across projects: "
            f"{', '.join(p.slug for p, _ in matches)}"
        )
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Piece
# ---------------------------------------------------------------------------


def read_piece(data_root: Path, slug: str, piece_id: str) -> Piece:
    return _load_model(Piece, piece_yaml_path(data_root, slug, piece_id))


def write_piece(data_root: Path, slug: str, piece: Piece) -> None:
    _dump_model(piece, piece_yaml_path(data_root, slug, piece.id))


def list_pieces(data_root: Path, slug: str) -> list[Piece]:
    directory = pieces_dir(data_root, slug)
    if not directory.exists():
        return []
    return [_load_model(Piece, p) for p in sorted(directory.glob("*/piece.yml"))]


def find_piece(data_root: Path, piece_id: str) -> tuple[Project, Piece] | None:
    """Scans every project for a piece with this id — same rationale as
    `find_brief`: `ce produce <piece-id>` (TDD 9) takes no `--project`."""
    matches = [
        (project, piece)
        for project in list_projects(data_root)
        for piece in list_pieces(data_root, project.slug)
        if piece.id == piece_id
    ]
    if len(matches) > 1:
        raise ConfigError(
            f"piece id {piece_id!r} is ambiguous across projects: "
            f"{', '.join(p.slug for p, _ in matches)}"
        )
    return matches[0] if matches else None


def read_rendition(data_root: Path, slug: str, piece_id: str, platform: str) -> Rendition:
    return _load_model(Rendition, rendition_yaml_path(data_root, slug, piece_id, platform))


def write_rendition(data_root: Path, slug: str, piece_id: str, rendition: Rendition) -> None:
    _dump_model(rendition, rendition_yaml_path(data_root, slug, piece_id, rendition.platform.value))


def generate_piece_id(data_root: Path, slug: str) -> str:
    """A human-readable, collision-safe piece id: `pc-0001`, `pc-0002`, ...
    (TDD 5.2 example: `id: pc-0007`). Same collision-safe-by-scanning
    approach as `generate_capture_id` — numbered per project, not globally.
    """
    directory = pieces_dir(data_root, slug)
    existing = {p.name for p in directory.glob("pc-*")} if directory.exists() else set()
    n = 1
    while f"pc-{n:04d}" in existing:
        n += 1
    return f"pc-{n:04d}"


# ---------------------------------------------------------------------------
# PostRecord — flat array at data/posted.yml (not per-project)
# ---------------------------------------------------------------------------


def read_posted(data_root: Path) -> list[PostRecord]:
    path = posted_yaml_path(data_root)
    if not path.exists():
        return []
    return _load_model_list(PostRecord, path)


def write_posted(data_root: Path, records: list[PostRecord]) -> None:
    _dump_model_list(records, posted_yaml_path(data_root))


# ---------------------------------------------------------------------------
# Manifest (TDD §0, §7) — idempotency via an input hash
# ---------------------------------------------------------------------------


class Manifest(BaseModel):
    input_hash: str
    updated_at: datetime
    extra: dict[str, Any] = Field(default_factory=dict)


def hash_inputs(*parts: str) -> str:
    """Stable hash of whatever a stage's re-run check depends on.

    Callers choose the parts (commit SHAs, file mtimes, config values) — this
    just hashes them consistently, so `--force` is the only way to bypass an
    unchanged-input no-op.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def manifest_path(stage_dir: Path) -> Path:
    return stage_dir / "_manifest.json"


def read_manifest(stage_dir: Path) -> Manifest | None:
    path = manifest_path(stage_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    try:
        return Manifest.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def write_manifest(stage_dir: Path, input_hash: str, extra: dict[str, Any] | None = None) -> None:
    manifest = Manifest(input_hash=input_hash, updated_at=datetime.now(UTC), extra=extra or {})
    path = manifest_path(stage_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")


def is_stale(stage_dir: Path, input_hash: str) -> bool:
    """True if the stage has never run, or its recorded inputs have changed."""
    manifest = read_manifest(stage_dir)
    return manifest is None or manifest.input_hash != input_hash


# ---------------------------------------------------------------------------
# Project summary — the read/format logic behind `ce project show` (WP-03).
#
# WP-03 owns wiring this into the CLI (`project new|list|show|close`); this
# is only the part WP-01's Done-when line ("`ce project show` ... prints
# correctly") actually exercises: assembling a project's on-disk state into
# readable text.
# ---------------------------------------------------------------------------


def format_project_summary(project: Project, captures: list[Capture], briefs: list[Brief]) -> str:
    lines = [
        f"{project.title} ({project.slug})",
        f"  status: {project.status.value}",
    ]
    if project.repos:
        lines.append("  repos:")
        lines += [f"    - {r.name} [{r.publishable.value}] {r.path}" for r in project.repos]
    if project.tags:
        lines.append(f"  tags: {', '.join(project.tags)}")

    lines.append(f"  captures: {len(captures)}")
    for capture in captures:
        lines.append(f"    - {capture.id} ({capture.type.value}, {capture.moment.value})")

    lines.append(f"  briefs: {len(briefs)}")
    by_status: dict[str, int] = {}
    for brief in briefs:
        by_status[brief.status.value] = by_status.get(brief.status.value, 0) + 1
    for status, count in sorted(by_status.items()):
        lines.append(f"    - {status}: {count}")

    return "\n".join(lines)


def read_project_summary(data_root: Path, slug: str) -> str:
    """Convenience wrapper: read a project's full on-disk state and format it."""
    project = read_project(data_root, slug)
    captures = list_captures(data_root, slug)
    briefs = read_briefs(data_root, slug)
    return format_project_summary(project, captures, briefs)
