"""`ce assets <piece-id> [--only KIND]` (TDD 10.7, 12 WP-11).

Four independently-invocable kinds, all optional/best-effort — a missing
input for one kind is a no-op for that kind, not an error, so
`ce assets <piece-id>` on a piece with nothing staged yet still succeeds
(with zero assets produced):

- **diagram**: hand-authored Mermaid source at
  `pieces/<id>/assets/diagrams/*.mmd` -> `mermaid-cli` -> `assets/<name>.png`.
- **codecard**: hand-selected snippets at `pieces/<id>/evidence/*` (TDD 6.2:
  "the operator hand-selects the snippet into evidence/ explicitly") ->
  `assets/codecard-<name>.png`, one per file.
- **thumbnail**: the brief's title, plus an optional hand-placed
  `pieces/<id>/assets/thumbnail-bg.<ext>` background -> `assets/thumbnail.png`.
- **hero**: a hand-placed `pieces/<id>/assets/hero-source.<ext>`, copied
  as-is to `assets/hero.<ext>` -- TDD 10.7's unlabeled fourth row
  ("screenshots: copy + manual review flag"). The manual-review checklist
  itself is `package/review_html.py`'s job (WP-13), not this one.

None of these input locations are named explicitly by the TDD (no `Asset`
schema exists in TDD 5.2 — only the `Piece 1--* Asset` entity-relationship
line) — see STATUS.md's deviations log for the reasoning behind each.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ce import store
from ce.assets import codecard as codecard_module
from ce.assets import thumbnail as thumbnail_module
from ce.assets.codecard import ScreenshotRenderer
from ce.assets.diagram import DEFAULT_WIDTH, DiagramRenderer
from ce.exit_codes import AssetError
from ce.models import Brief, Piece

_HERO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
KINDS = ("diagram", "codecard", "thumbnail", "hero")


@dataclass
class AssetsResult:
    produced: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _assets_dir(data_root: Path, project_slug: str, piece_id: str) -> Path:
    return store.piece_dir(data_root, project_slug, piece_id) / "assets"


def _render_diagrams(
    data_root: Path,
    project_slug: str,
    piece_id: str,
    *,
    renderer: DiagramRenderer,
    result: AssetsResult,
) -> None:
    diagrams_dir = _assets_dir(data_root, project_slug, piece_id) / "diagrams"
    mmd_files = sorted(diagrams_dir.glob("*.mmd")) if diagrams_dir.exists() else []
    if not mmd_files:
        result.skipped.append("diagram: no *.mmd files in assets/diagrams/")
        return
    for mmd_path in mmd_files:
        output_path = _assets_dir(data_root, project_slug, piece_id) / f"{mmd_path.stem}.png"
        renderer.render(mmd_path.read_text(encoding="utf-8"), output_path, width=DEFAULT_WIDTH)
        result.produced.append(output_path)


def _render_codecards(
    data_root: Path,
    project_slug: str,
    piece_id: str,
    *,
    renderer: ScreenshotRenderer,
    result: AssetsResult,
) -> None:
    evidence_dir = store.piece_dir(data_root, project_slug, piece_id) / "evidence"
    snippet_files = (
        sorted(p for p in evidence_dir.glob("*") if p.is_file()) if evidence_dir.exists() else []
    )
    if not snippet_files:
        result.skipped.append("codecard: no files in evidence/")
        return
    for snippet_path in snippet_files:
        output_path = (
            _assets_dir(data_root, project_slug, piece_id) / f"codecard-{snippet_path.stem}.png"
        )
        codecard_module.render(
            snippet_path.read_text(encoding="utf-8"),
            codecard_module.lang_for(snippet_path),
            output_path,
            renderer=renderer,
        )
        result.produced.append(output_path)


def _render_thumbnail(
    data_root: Path,
    project_slug: str,
    piece_id: str,
    brief: Brief,
    *,
    renderer: ScreenshotRenderer,
    result: AssetsResult,
) -> None:
    assets_dir = _assets_dir(data_root, project_slug, piece_id)
    bg_candidates = sorted(assets_dir.glob("thumbnail-bg.*")) if assets_dir.exists() else []
    output_path = assets_dir / "thumbnail.png"
    thumbnail_module.render(
        brief.title,
        output_path,
        renderer=renderer,
        background_image_path=bg_candidates[0] if bg_candidates else None,
    )
    result.produced.append(output_path)


def _copy_hero(data_root: Path, project_slug: str, piece_id: str, *, result: AssetsResult) -> None:
    assets_dir = _assets_dir(data_root, project_slug, piece_id)
    candidates = (
        sorted(p for p in assets_dir.glob("hero-source.*") if p.suffix.lower() in _HERO_EXTENSIONS)
        if assets_dir.exists()
        else []
    )
    if not candidates:
        result.skipped.append("hero: no assets/hero-source.<ext> staged")
        return
    source = candidates[0]
    dest = assets_dir / f"hero{source.suffix.lower()}"
    shutil.copy2(source, dest)
    result.produced.append(dest)


def generate(
    piece: Piece,
    brief: Brief,
    *,
    data_root: Path,
    only: str | None = None,
    diagram_renderer: DiagramRenderer,
    screenshot_renderer: ScreenshotRenderer,
) -> AssetsResult:
    """Runs the requested kind(s) (all four if `only` is `None`)."""
    if only is not None and only not in KINDS:
        raise AssetError(f"unknown --only kind {only!r}, expected one of {', '.join(KINDS)}")

    _assets_dir(data_root, piece.project, piece.id).mkdir(parents=True, exist_ok=True)
    result = AssetsResult()

    if only in (None, "diagram"):
        _render_diagrams(
            data_root, piece.project, piece.id, renderer=diagram_renderer, result=result
        )
    if only in (None, "codecard"):
        _render_codecards(
            data_root, piece.project, piece.id, renderer=screenshot_renderer, result=result
        )
    if only in (None, "thumbnail"):
        _render_thumbnail(
            data_root, piece.project, piece.id, brief, renderer=screenshot_renderer, result=result
        )
    if only in (None, "hero"):
        _copy_hero(data_root, piece.project, piece.id, result=result)

    return result
