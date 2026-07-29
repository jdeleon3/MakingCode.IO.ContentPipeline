"""`/` and `/projects/<slug>` (TDD 10.10, WP-18): read-only rollup of every
project's on-disk state.

Reads/writes/runs (TDD 10.10's table): reads only -- `project.yml` plus the
same `store.py` helpers WP-08/09 already use to list captures/briefs/pieces.
No writes, no subprocess runs, so this module never touches `runner.py`.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ce import store
from ce.exit_codes import ConfigError

router = APIRouter()


def _harvest_summary(data_root: Path, slug: str) -> dict[str, bool]:
    """Whether each harvest artifact exists yet. `harvested` is true the
    moment *any* of them do -- a project mid-harvest (e.g. `git.json`
    written, `research.json` not yet) is still "harvested", just partially;
    a project with none of the three is the "not harvested" state WP-18's
    Done-when line calls out explicitly.
    """
    hdir = store.harvest_dir(data_root, slug)
    git_done = (hdir / "git.json").exists()
    research_done = (hdir / "research.json").exists()
    inventory_done = (hdir / "inventory.md").exists()
    return {
        "git": git_done,
        "research": research_done,
        "inventory": inventory_done,
        "harvested": git_done or research_done or inventory_done,
    }


@router.get("/")
def dashboard(request: Request) -> HTMLResponse:
    data_root = Path("data")
    projects = sorted(store.list_projects(data_root), key=lambda p: p.slug)
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "dashboard.html", {"projects": projects})


@router.get("/projects/{slug}")
def project_detail(request: Request, slug: str) -> HTMLResponse:
    data_root = Path("data")
    try:
        project = store.read_project(data_root, slug)
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail=f"no such project: {slug}") from exc

    captures = store.list_captures(data_root, slug)
    captures_by_type = Counter(c.type.value for c in captures)

    harvest = _harvest_summary(data_root, slug)

    briefs = store.read_briefs(data_root, slug)
    briefs_by_status = Counter(b.status.value for b in briefs)

    pieces = store.list_pieces(data_root, slug)
    pieces_by_status = Counter(p.status.value for p in pieces)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "project": project,
            "captures": captures,
            "captures_by_type": sorted(captures_by_type.items()),
            "harvest": harvest,
            "briefs": briefs,
            "briefs_by_status": sorted(briefs_by_status.items()),
            "pieces": pieces,
            "pieces_by_status": sorted(pieces_by_status.items()),
        },
    )
