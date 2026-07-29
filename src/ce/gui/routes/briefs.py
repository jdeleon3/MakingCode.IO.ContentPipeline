"""`/projects/<slug>/briefs` (TDD 10.10, WP-20): list candidate briefs and let
the operator promote one to a `Piece` via `ce brief select`.

Reads/writes/runs (TDD 10.10's table): reads `briefs.yml` (`store.read_briefs`
-- the same structured source `inventory.md` itself is rendered from, so
there is nothing `inventory.md` would add that isn't already on the `Brief`
model); runs `ce brief select <brief-id>` through WP-19's `runner.py` for the
"Select" action; no direct writes of its own -- the subprocess is the real
CLI, so `briefs.yml`/`piece.yml` are written exactly as they would be from a
terminal invocation.

**Why `assert_selectable` is never imported here.** §10.10's hard rule: the
GUI never imports pipeline modules (`harvest/`, `produce/`, `gates/`, ...).
`Brief.status == DROPPED` is a plain data field already on the model
`store.read_briefs` returns -- checking it (to disable the Select control
client-side, and to short-circuit the POST server-side before spending a
subprocess launch on an already-known-refused action) is reading data, not
reimplementing `harvest/inventory.py::assert_selectable`'s business logic.
The subprocess itself -- which *does* run that check, for real -- is still
the sole authority: if it exits non-zero for any reason (a race where the
brief was dropped by a concurrent run since this page loaded, or anything
else), that exit code is what determines success here, not this pre-check.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ce import store
from ce.exit_codes import ConfigError
from ce.gui import runner
from ce.models import BriefStatus

router = APIRouter()


@router.get("/projects/{slug}/briefs")
def briefs_page(request: Request, slug: str) -> HTMLResponse:
    data_root = Path("data")
    try:
        project = store.read_project(data_root, slug)
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail=f"no such project: {slug}") from exc

    briefs = store.read_briefs(data_root, slug)
    ranked = sorted(
        briefs,
        key=lambda b: (b.status == BriefStatus.DROPPED, -b.demand.recurrence),
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "briefs.html",
        {"project": project, "briefs": ranked, "BriefStatus": BriefStatus},
    )


def _error_tail(log_path: Path, *, max_lines: int = 5) -> str:
    """Best-effort last few non-blank lines of a failed run's log -- the same
    `console.failure`/`console.hint` text `ce brief select` printed on a real
    terminal (ANSI stripped, per `run_log.tee`), so a GUI failure reads the
    same as the CLI's own report (WP-20's Done-when line)."""
    if not log_path.exists():
        return "ce brief select failed"
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:]) or "ce brief select failed"


@router.post("/projects/{slug}/briefs/{brief_id}/select")
def select_brief(slug: str, brief_id: str) -> dict[str, str]:
    """Runs the real `ce brief select <brief-id>` synchronously (it's a plain
    file read/write with no LLM call, so waiting for it is cheap) and hands
    the resulting piece id back as JSON -- same shape as `/runs/start`'s
    `{run_id}` response, which its own `runs.html` JS turns into a
    `window.location.href` navigation rather than a server-issued redirect.
    Kept consistent here for the same reason: `/pieces/<id>` (WP-21) doesn't
    exist yet, so the two failure modes -- this call itself refusing/failing,
    versus the destination page not being built yet -- need to stay visibly
    distinct rather than both collapsing into a raw 3xx a fetch() would
    silently follow.

    Passes `--skip-research`: `ce brief select` now also runs a brief-scoped
    research pass by default (a real network + LLM call), which would break
    this route's "cheap, synchronous, block on it" premise above. The GUI
    opts out here rather than becoming a genuinely async flow through
    `/runs/start`'s console -- that's a bigger UX change than this refactor
    covers. A GUI-selected piece simply doesn't get brief-scoped research
    until this route is revisited.
    """
    data_root = Path("data")
    briefs = store.read_briefs(data_root, slug)
    brief = next((b for b in briefs if b.id == brief_id), None)
    if brief is None:
        raise HTTPException(status_code=404, detail=f"no such brief: {brief_id}")
    if brief.status == BriefStatus.DROPPED:
        raise HTTPException(
            status_code=400,
            detail=f"brief {brief_id!r} is dropped and cannot be selected "
            "(weak grounding or too similar to a published piece; see risk_flags)",
        )

    pieces_before = {p.id for p in store.list_pieces(data_root, slug)}

    handle = runner.run_command(
        ["brief", "select", brief_id, "--skip-research"], cwd=Path.cwd(), data_root=data_root
    )
    exit_code = handle.process.wait()
    if exit_code != 0:
        raise HTTPException(status_code=422, detail=_error_tail(handle.log_path))

    new_pieces = [
        p
        for p in store.list_pieces(data_root, slug)
        if p.id not in pieces_before and p.brief_id == brief_id
    ]
    if not new_pieces:
        raise HTTPException(
            status_code=500,
            detail="ce brief select exited 0 but no new piece was found",
        )
    piece = max(new_pieces, key=lambda p: p.id)
    return {"piece_id": piece.id}
