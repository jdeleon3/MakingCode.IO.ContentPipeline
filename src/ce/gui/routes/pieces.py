"""`/pieces/<id>` (TDD 10.10, WP-21): the article/grade/verification review
screen -- edit `article.md` in place, see every grading attempt, see claim
verification once it's run, and launch `verify`/`assets`/`render` as real
subprocesses.

Reads/writes/runs (TDD 10.10's table): reads `article.md`, `grades.json`,
`verification.json`; writes `article.md` straight back to its normal path
(the same file `ce produce`/a manual edit would touch); runs `ce verify` /
`ce assets` / `ce render` -- all three already exist as `runs.py::_COMMANDS`
entries, so this screen's action buttons reuse `/runs/start` + `/runs/<id>`
directly rather than adding a second, piece-scoped way to launch a subprocess.

**Why `grades.json`/`verification.json` are parsed as plain JSON, not through
`produce/writer.py::GradesLog` or `gates/claims.py::VerificationResult`.**
§10.10's hard rule: the GUI never imports pipeline modules
(`harvest/`, `produce/`, `gates/`, ...). Both files are already fully-formed
JSON written by those modules -- reading them with the stdlib `json` module
and handing the resulting dicts straight to the template is a plain file
read, not a reimplementation of either module's grading/verification logic.

**Why the article save writes the file directly, with no model in between.**
ADR-008's edit check compares `article.md`'s mtime to `piece.generated_at` --
a GUI save has to look indistinguishable from a manual edit made in a text
editor, so this is a bare `Path.write_text`, exactly like every other
`article.md` writer in this codebase (`produce/writer.py::produce`).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ce import store
from ce.exit_codes import ConfigError

router = APIRouter()


def _find_piece_or_404(data_root: Path, piece_id: str):
    try:
        found = store.find_piece(data_root, piece_id)
    except ConfigError as exc:
        # `find_piece` raises this only when the same id exists in more than
        # one project -- a genuine ambiguity, not a "not found".
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail=f"no such piece: {piece_id}")
    return found


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/pieces/{piece_id}")
def piece_detail(request: Request, piece_id: str) -> HTMLResponse:
    data_root = Path("data")
    project, piece = _find_piece_or_404(data_root, piece_id)

    article_path = store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
    article_text = article_path.read_text(encoding="utf-8") if article_path.exists() else None

    grades_log = _read_json(store.grades_json_path(data_root, project.slug, piece.id))
    attempts = grades_log["attempts"] if grades_log else []

    verification = _read_json(store.verification_json_path(data_root, project.slug, piece.id))
    claims = verification["claims"] if verification else []

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "pieces.html",
        {
            "project": project,
            "piece": piece,
            "article_text": article_text,
            "attempts": attempts,
            "claims": claims,
        },
    )


class _ArticleSave(BaseModel):
    content: str


@router.post("/pieces/{piece_id}/article")
def save_article(piece_id: str, body: _ArticleSave) -> dict[str, str]:
    data_root = Path("data")
    project, piece = _find_piece_or_404(data_root, piece_id)

    article_path = store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
    article_path.parent.mkdir(parents=True, exist_ok=True)
    article_path.write_text(body.content, encoding="utf-8")

    return {"status": "saved"}
