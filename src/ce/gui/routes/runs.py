"""`/runs` screen (TDD 10.10, WP-19): pick any §9 stage command, submit it as
a real `ce` subprocess via `runner.py`, and watch it stream live.

Reads/writes/runs (TDD 10.10's table): reads `data/runs/*.log` for the
recent-runs list; runs whichever command the operator picked. No file writes
of its own -- the subprocess is the real CLI, so any writes happen exactly
as they would from a terminal invocation.

**Confirm gate.** `ce publish site` reaches outside this machine (`git
push` to `identity.site_repo`, TDD 10.9/10.10) -- `_COMMANDS[...].confirm`
marks it, the template disables the submit button until the operator
checks the confirm box, and `/runs/start` re-checks the same rule
server-side so the gate can't be skipped by posting the form directly.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ce.gui import runner

router = APIRouter()


class _RunRequest(BaseModel):
    command: str
    argument: str = ""
    extra: str = ""
    confirm: bool = False


@dataclass(frozen=True)
class _Command:
    key: str
    argv: list[str]
    label: str
    arg_hint: str | None  # what the free-text "argument" field means, or None if unused
    confirm: bool = False


# Every §9 stage command the console can trigger. `ce project`/`ce capture`
# subcommands are left out -- they're authoring actions with their own future
# screens (WP-20+), not pipeline stages you'd re-run from a log console.
_COMMANDS: list[_Command] = [
    _Command("doctor", ["doctor"], "ce doctor", None),
    _Command("harvest", ["harvest"], "ce harvest <project>", "project slug"),
    _Command("brief-select", ["brief", "select"], "ce brief select <brief-id>", "brief id"),
    _Command("produce", ["produce"], "ce produce <piece-id>", "piece id"),
    _Command("verify", ["verify"], "ce verify <piece-id>", "piece id"),
    _Command("assets", ["assets"], "ce assets <piece-id>", "piece id"),
    _Command("render", ["render"], "ce render <piece-id>", "piece id"),
    _Command("package", ["package"], "ce package <piece-id>", "piece id"),
    _Command(
        "publish-site",
        ["publish", "site"],
        "ce publish site <piece-id>",
        "piece id",
        confirm=True,
    ),
    _Command("posted", ["posted"], "ce posted <piece-id> --platform P --url URL", "piece id"),
    _Command("metrics-pull", ["metrics", "pull"], "ce metrics pull", None),
    _Command("sweep", ["sweep"], "ce sweep", None),
    _Command("index-rebuild", ["index", "rebuild"], "ce index rebuild", None),
    _Command("cost", ["cost"], "ce cost", None),
]
_COMMANDS_BY_KEY = {c.key: c for c in _COMMANDS}


def _recent_runs(data_root: Path) -> list[dict[str, str]]:
    """Best-effort history from `data/runs/*.log` filenames -- a run's
    filename is `<run-id>-<command>.log` (`run_log.py`), and `run_id` itself
    never contains a `-`, so splitting on the first one recovers both parts
    without needing the in-memory `runner._runs` registry (which is empty
    after a GUI restart, TDD ADR-009: not a daemon)."""
    runs_dir = data_root / "runs"
    if not runs_dir.is_dir():
        return []
    entries = []
    for log_path in sorted(runs_dir.glob("*.log"), reverse=True)[:25]:
        stem = log_path.stem
        run_id, _, command = stem.partition("-")
        entries.append({"run_id": run_id, "command": command or stem})
    return entries


@router.get("/runs")
def runs_page(request: Request) -> HTMLResponse:
    data_root = Path("data")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "runs.html",
        {"commands": _COMMANDS, "recent_runs": _recent_runs(data_root)},
    )


@router.post("/runs/start")
def runs_start(req: _RunRequest) -> dict[str, str]:
    cmd = _COMMANDS_BY_KEY.get(req.command)
    if cmd is None:
        raise HTTPException(status_code=400, detail=f"unknown command: {req.command}")
    if cmd.confirm and not req.confirm:
        raise HTTPException(
            status_code=400,
            detail=f"{cmd.label} reaches outside this machine and requires confirmation",
        )

    argv = list(cmd.argv)
    if req.argument.strip():
        argv.append(req.argument.strip())
    if req.extra.strip():
        argv.extend(shlex.split(req.extra))

    handle = runner.run_command(argv, cwd=Path.cwd())
    return {"run_id": handle.run_id}


@router.get("/runs/{run_id}")
def run_detail(request: Request, run_id: str) -> HTMLResponse:
    """Reopening this URL -- after a page reload mid-run, or long after the
    run finished -- always reconnects to the same tailed log (TDD 10.10 /
    WP-19's Done-when line), never a blank console.

    `runner._runs` only lives for this `ce gui` process's lifetime (ADR-009:
    not a daemon). While the handle is still in memory, the SSE stream is
    used -- it replays the log from byte 0 either way, live or already
    finished. If the handle is gone (GUI restarted since), there is no
    `Popen` left to poll an exit code from, so the log file is read and
    shown statically instead of reconnecting a stream that would never end.
    """
    handle = runner.get_run(run_id)
    data_root = Path("data")

    if handle is not None:
        command_label = " ".join(handle.args)
        static_content = None
    else:
        matches = sorted(data_root.glob(f"runs/{run_id}-*.log"))
        if not matches:
            raise HTTPException(status_code=404, detail=f"no such run: {run_id}")
        command_label = matches[0].stem.partition("-")[2]
        static_content = matches[0].read_text(encoding="utf-8")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "run_id": run_id,
            "command_label": command_label,
            "static_content": static_content,
        },
    )


@router.get("/runs/stream/{run_id}")
def run_stream(run_id: str) -> StreamingResponse:
    def events() -> Iterator[str]:
        for event in runner.stream_run(run_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
