"""`/pieces/<id>/assets/stage|stage-text|unstage` (operator-requested, post-
WP-22): stage the hand-placed *inputs* `ce assets` reads through the browser
instead of the filesystem.

`assets/__init__.py`'s own module docstring names four such inputs, none of
which had any GUI surface before this: `assets/hero-source.<ext>`,
`assets/thumbnail-bg.<ext>`, `assets/diagrams/*.mmd`, and `evidence/*`. This
module is only ever those *inputs* -- the piece's rendered *outputs*
(`thumbnail.png`, `hero.png`, ...) stay on WP-22's `renditions.py`, which
already lists/serves them.

Kept as a separate module from `pieces.py`, mirroring how `renditions.py` is
already split out for the piece's later (render/package) side -- staging is
a genuinely separate concern from article/grade/verification review, and
reuses `pieces.py`'s `find_piece_or_404` the same one-directional way
`renditions.py` already does (this module imports from `pieces.py`; `pieces.py`
never imports from this one, so there's no cycle).

**Why extensions are hardcoded here instead of imported.** §10.10's hard
rule: the GUI never imports pipeline modules (`assets/` is one of them).
`_HERO_EXTENSIONS`/`_IMAGE_EXTENSIONS` mirror `assets/__init__.py`'s own
`_HERO_EXTENSIONS` / `thumbnail.py`'s `_MIME_BY_EXTENSION` keys -- the same
"a plain, hardcoded, mirrored list, not a reflection of the real thing"
shape `renditions.py`'s own `_PLATFORMS` tuple already uses.

**Why upload and paste-to-create share `_write_staged_file`.** The operator
asked for evidence snippets to be pastable directly (filename + textarea),
not just uploaded as an existing file. Routing both through the same
extension-check-then-write helper means a pasted `fix.py` is byte-for-byte
what an uploaded `fix.py` would have been -- one code path to keep correct,
not two that could quietly drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ce import store
from ce.gui.routes.pieces import find_piece_or_404

router = APIRouter()

# assets/__init__.py::_HERO_EXTENSIONS
_HERO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
# thumbnail.py::_MIME_BY_EXTENSION keys
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_DIAGRAM_EXTENSIONS = {".mmd"}


@dataclass(frozen=True)
class _KindSpec:
    subdir: str
    extensions: frozenset[str] | None  # None == any extension accepted (evidence)
    singleton_stem: str | None  # set == exactly one file, named "<stem><ext>"


_KINDS: dict[str, _KindSpec] = {
    "hero": _KindSpec(subdir="assets", extensions=frozenset(_HERO_EXTENSIONS), singleton_stem="hero-source"),
    "thumbnail_bg": _KindSpec(
        subdir="assets", extensions=frozenset(_IMAGE_EXTENSIONS), singleton_stem="thumbnail-bg"
    ),
    "evidence": _KindSpec(subdir="evidence", extensions=None, singleton_stem=None),
    "diagram": _KindSpec(
        subdir="assets/diagrams", extensions=frozenset(_DIAGRAM_EXTENSIONS), singleton_stem=None
    ),
}


def _get_kind_spec(kind: str) -> _KindSpec:
    spec = _KINDS.get(kind)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"unknown kind: {kind!r}")
    return spec


def _target_dir(data_root: Path, slug: str, piece_id: str, spec: _KindSpec) -> Path:
    return store.piece_dir(data_root, slug, piece_id) / spec.subdir


def _write_staged_file(target_dir: Path, filename: str, spec: _KindSpec, content: bytes) -> str:
    """Validates the extension, sanitizes the filename (no directory
    components -- no path traversal), and writes `content`. For a singleton
    kind, deletes whatever was already staged under that stem first. Returns
    the filename actually written."""
    ext = Path(filename).suffix.lower()
    if spec.extensions is not None and ext not in spec.extensions:
        allowed = ", ".join(sorted(spec.extensions))
        raise HTTPException(
            status_code=400, detail=f"unsupported extension {ext!r} (allowed: {allowed})"
        )

    target_dir.mkdir(parents=True, exist_ok=True)

    if spec.singleton_stem is not None:
        for existing in target_dir.glob(f"{spec.singleton_stem}.*"):
            existing.unlink()
        dest = target_dir / f"{spec.singleton_stem}{ext}"
    else:
        name = Path(filename).name
        if not name:
            raise HTTPException(status_code=400, detail="missing filename")
        dest = target_dir / name

    dest.write_bytes(content)
    return dest.name


@router.post("/pieces/{piece_id}/assets/stage/{kind}")
async def stage_asset(piece_id: str, kind: str, file: UploadFile = File(...)) -> dict[str, str]:
    spec = _get_kind_spec(kind)
    data_root = Path("data")
    project, piece = find_piece_or_404(data_root, piece_id)

    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    content = await file.read()
    target_dir = _target_dir(data_root, project.slug, piece.id, spec)
    written = _write_staged_file(target_dir, file.filename, spec, content)

    return {"status": "staged", "filename": written}


class _StageText(BaseModel):
    filename: str
    content: str


@router.post("/pieces/{piece_id}/assets/stage-text/{kind}")
def stage_text_asset(piece_id: str, kind: str, body: _StageText) -> dict[str, str]:
    """Paste-to-create: a filename + textarea instead of an existing file on
    disk. Wired into both the `evidence` and `diagram` sub-blocks of
    `pieces.html` -- see the module docstring."""
    spec = _get_kind_spec(kind)
    data_root = Path("data")
    project, piece = find_piece_or_404(data_root, piece_id)

    target_dir = _target_dir(data_root, project.slug, piece.id, spec)
    written = _write_staged_file(target_dir, body.filename, spec, body.content.encode("utf-8"))

    return {"status": "staged", "filename": written}


class _Unstage(BaseModel):
    filename: str


@router.post("/pieces/{piece_id}/assets/unstage/{kind}")
def unstage_asset(piece_id: str, kind: str, body: _Unstage) -> dict[str, str]:
    spec = _get_kind_spec(kind)
    data_root = Path("data")
    project, piece = find_piece_or_404(data_root, piece_id)

    target_dir = _target_dir(data_root, project.slug, piece.id, spec)
    name = Path(body.filename).name
    path = (target_dir / name).resolve()
    if path.parent != target_dir.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"no such staged file: {body.filename}")
    path.unlink()

    return {"status": "removed"}
