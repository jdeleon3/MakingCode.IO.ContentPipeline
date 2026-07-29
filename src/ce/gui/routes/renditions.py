"""`/pieces/<id>/renditions` (TDD 10.10, WP-22): per-platform rendition
editing, asset previews, and the package preview -- the last screen in the
edit/review/package loop (TDD 12.1's GUI critical path: WP-17 -> WP-19 ->
WP-21 -> WP-22).

Reads/writes/runs (TDD 10.10's table): reads `renditions/*.yml`, `assets/`,
`outbox/<id>/REVIEW.html`; writes `renditions/*.yml` straight back to the
same file `ce render`/a manual edit would touch; runs `ce package`,
`ce publish site`, `ce posted` via WP-19's `/runs/start` + `/runs/<id>`,
exactly like WP-21's `verify`/`assets`/`render` buttons.

**Why platform names are a local tuple, not imported from
`produce/renditions.py::DEFAULT_PLATFORMS`.** §10.10's hard rule: the GUI
never imports pipeline modules (`harvest/`, `produce/`, `gates/`, ...).
`produce/` is one of them, so the three known platform keys are simply
repeated here -- the same "a plain, hardcoded command/platform list, not a
reflection of the real thing" shape `runs.py::_COMMANDS` already uses.

**Why `config/platforms/<p>.yml` *is* read directly (`ce.config`, not
`produce/`).** TDD 10.10 explicitly asks for this: the live character
counter must use "the exact constants `produce/renditions.py`'s own §10.6
validation reads from `config/platforms/<p>.yml`, never a second hardcoded
copy of `max_chars`/`hook_chars`." `ce.config` is a plain schema loader
(no pipeline logic, no LLM calls) -- reading `max_chars`/`hook_chars` from
it is a config read, not an import of `produce/`'s validation logic itself
(that logic is never re-run here; the GUI only *displays* the same limit).

**Why saving a rendition preserves its `prompt_version`/`generated_at`.**
`Rendition` (models.py) requires both fields -- they record which prompt
produced this copy (TDD §11's versioning contract) and don't change just
because the operator tweaked wording afterward, the same way editing
`article.md`'s body doesn't rewrite `piece.generated_at`. The save handler
reads the existing file, only overwrites the fields the form actually
edited, and writes it back through `store.write_rendition` -- indistinguishable
from a hand-edit of the YAML file's `body`/`first_comment`/`title`/`chapters`
keys.

**Why the package preview is an iframe over the literal file, with a second
route just to serve its `assets/*` images.** TDD 10.10: "never a GUI-side
reimplementation of §10.8's layout." `outbox/<id>/REVIEW.html` references its
images by *relative* path (ADR-006: the folder must stay portable) --
`/pieces/<id>/renditions/review/` and `/pieces/<id>/renditions/review/assets/<file>`
reproduce that same relative structure over HTTP so the real file's
`<img src="assets/...">` tags resolve unmodified, rather than rewriting any
path inside the HTML.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ce import store
from ce.config import load_platform_config
from ce.exit_codes import ConfigError
from ce.gui.routes.pieces import find_piece_or_404

router = APIRouter()

# The three platforms `ce render`/`ce package` know about (produce/renditions.py
# ::DEFAULT_PLATFORMS) -- repeated here rather than imported, see module docstring.
_PLATFORMS: tuple[str, ...] = ("linkedin", "facebook", "youtube")

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _outbox_dir(piece_id: str) -> Path:
    return Path("outbox") / piece_id


def _load_platform_config_or_none(name: str):
    path = Path("config/platforms") / f"{name}.yml"
    if not path.exists():
        return None
    try:
        return load_platform_config(path)
    except ConfigError:
        return None


def _list_asset_files(data_root: Path, slug: str, piece_id: str) -> list[str]:
    assets_dir = store.piece_dir(data_root, slug, piece_id) / "assets"
    if not assets_dir.exists():
        return []
    return sorted(
        p.name
        for p in assets_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
    )


@router.get("/pieces/{piece_id}/renditions")
def renditions_page(request: Request, piece_id: str) -> HTMLResponse:
    data_root = Path("data")
    project, piece = find_piece_or_404(data_root, piece_id)

    platforms = []
    for name in _PLATFORMS:
        rendition_path = store.rendition_yaml_path(data_root, project.slug, piece.id, name)
        rendition = (
            store.read_rendition(data_root, project.slug, piece.id, name)
            if rendition_path.exists()
            else None
        )
        platforms.append(
            {
                "name": name,
                "rendition": rendition,
                "config": _load_platform_config_or_none(name),
            }
        )

    asset_files = _list_asset_files(data_root, project.slug, piece.id)
    has_package = (_outbox_dir(piece.id) / "REVIEW.html").exists()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "renditions.html",
        {
            "project": project,
            "piece": piece,
            "platforms": platforms,
            "asset_files": asset_files,
            "has_package": has_package,
        },
    )


class _RenditionSave(BaseModel):
    body: str
    first_comment: str | None = None
    title: str | None = None
    chapters: list[str] = Field(default_factory=list)


@router.post("/pieces/{piece_id}/renditions/{platform}")
def save_rendition(piece_id: str, platform: str, req: _RenditionSave) -> dict[str, str]:
    if platform not in _PLATFORMS:
        raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")

    data_root = Path("data")
    project, piece = find_piece_or_404(data_root, piece_id)

    path = store.rendition_yaml_path(data_root, project.slug, piece.id, platform)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"no {platform} rendition yet -- run `ce render {piece_id}` first",
        )

    rendition = store.read_rendition(data_root, project.slug, piece.id, platform)
    rendition.body = req.body
    if platform == "youtube":
        rendition.title = req.title
        rendition.chapters = req.chapters
    else:
        rendition.first_comment = req.first_comment
    store.write_rendition(data_root, project.slug, piece.id, rendition)

    return {"status": "saved"}


@router.get("/pieces/{piece_id}/assets/{filename}")
def piece_asset(piece_id: str, filename: str) -> FileResponse:
    data_root = Path("data")
    project, piece = find_piece_or_404(data_root, piece_id)

    assets_dir = store.piece_dir(data_root, project.slug, piece.id) / "assets"
    path = (assets_dir / filename).resolve()
    if path.parent != assets_dir.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"no such asset: {filename}")
    return FileResponse(path)


@router.get("/pieces/{piece_id}/renditions/review/")
def review_html(piece_id: str) -> HTMLResponse:
    path = _outbox_dir(piece_id) / "REVIEW.html"
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"not packaged yet -- run `ce package {piece_id}` first"
        )
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/pieces/{piece_id}/renditions/review/assets/{filename}")
def review_asset(piece_id: str, filename: str) -> FileResponse:
    assets_dir = _outbox_dir(piece_id) / "assets"
    path = (assets_dir / filename).resolve()
    if path.parent != assets_dir.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"no such packaged asset: {filename}")
    return FileResponse(path)
