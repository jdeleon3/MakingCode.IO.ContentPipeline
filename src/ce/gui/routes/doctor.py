"""`/doctor` screen (TDD 10.10, WP-17): triggers a real `ce doctor` run
through `runner.py` and streams its output line-by-line over SSE.

Reads/writes/runs (TDD 10.10's table): runs `ce doctor` only, nothing read
or written directly -- `doctor.py`'s own checks are the single source of
truth for what "environment ok" means, this screen never re-implements them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from ce.gui import runner

router = APIRouter()


@router.get("/doctor")
def doctor_page(request: Request, run: str | None = None) -> HTMLResponse:
    """`?run=<run-id>` lets a page reload mid-run reconnect to the same
    stream instead of starting a fresh `ce doctor` -- the template's inline
    script auto-connects to `/doctor/stream/<run-id>` when it's present."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "doctor.html", {"run_id": run})


@router.post("/doctor/run")
def doctor_start() -> dict[str, str]:
    handle = runner.run_command(["doctor"], cwd=Path.cwd())
    return {"run_id": handle.run_id}


@router.get("/doctor/stream/{run_id}")
def doctor_stream(run_id: str) -> StreamingResponse:
    def events() -> Iterator[str]:
        for event in runner.stream_run(run_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
