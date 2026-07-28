"""Shells out to the real `ce` entry point and tails the run log `cli.main()`
writes for every invocation (`ce/run_log.py`, TDD §14). This is the only
place the GUI touches a subprocess -- every screen's "Run" action goes
through `run_command`, never a direct `subprocess` call of its own (TDD
10.10's hard rule: the GUI is never a second implementation of the pipeline).

`run_command` returns immediately (TDD 10.10's literal signature); the
caller gets a `run_id` back and polls/streams via `stream_run`. State lives
in the `_RUNS` module dict for the lifetime of the `ce gui` process --
ADR-009 says this is deliberately not a daemon, so nothing here needs to
survive a server restart, only a browser tab closing/reloading while the
server itself stays up (WP-17/WP-19's Done-when lines).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from ce.run_log import RUN_ID_ENV_VAR, command_name, new_run_id, run_log_path

_POLL_INTERVAL_S = 0.1


class RunEvent(TypedDict, total=False):
    line: str
    done: bool
    exit_code: int


@dataclass
class RunHandle:
    run_id: str
    args: list[str]
    log_path: Path
    process: subprocess.Popen
    exit_code: int | None = None


_runs: dict[str, RunHandle] = {}
_lock = threading.Lock()


def run_command(args: list[str], *, cwd: Path, data_root: Path = Path("data")) -> RunHandle:
    """Launch the real CLI as a subprocess and return immediately.

    Invokes `[sys.executable, "-m", "ce.cli", *args]` rather than a bare
    `["ce", *args]` (TDD 10.10's literal pseudocode) so this doesn't depend
    on the installed `ce` console-script's directory being on PATH inside
    whatever environment `ce gui` itself happens to be running in -- it's
    still a genuine subprocess of the same unmodified `cli.main()`, just
    invoked in the one way guaranteed to resolve regardless of PATH.
    `CE_RUN_ID` is set here (not left to `run_log.tee`'s own fallback) so
    this function can predict the exact log path the child will write to,
    without racing it or duplicating its file-naming logic.
    """
    run_id = new_run_id()
    log_path = run_log_path(data_root, run_id, command_name(args))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, RUN_ID_ENV_VAR: run_id}
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "ce.cli", *args],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle = RunHandle(run_id=run_id, args=args, log_path=log_path, process=process)
    with _lock:
        _runs[run_id] = handle
    return handle


def get_run(run_id: str) -> RunHandle | None:
    with _lock:
        return _runs.get(run_id)


def stream_run(run_id: str) -> Iterator[RunEvent]:
    """Tail the run's log file from byte 0, live.

    Reads the log file itself, never the subprocess's stdout/stderr pipes
    (TDD 10.10) -- a run keeps executing if the browser tab closes, and
    calling this again (page reload mid-run, or after it finished) always
    replays the same content from the top instead of missing lines a
    one-shot pipe read would have already consumed.
    """
    handle = get_run(run_id)
    if handle is None:
        return

    while not handle.log_path.exists() and handle.process.poll() is None:
        time.sleep(_POLL_INTERVAL_S)

    with handle.log_path.open("r", encoding="utf-8") as f:
        while True:
            line = f.readline()
            if line:
                yield {"line": line.rstrip("\n")}
                continue

            exit_code = handle.process.poll()
            if exit_code is None:
                time.sleep(_POLL_INTERVAL_S)
                continue

            # One more read: a final flush can land between the last empty
            # readline() and the process actually reporting its exit code.
            for remaining in f.read().splitlines():
                yield {"line": remaining}
            handle.exit_code = exit_code
            yield {"done": True, "exit_code": exit_code}
            return


def terminate_all() -> None:
    """Stop every still-running child. Called from `gui/app.py`'s shutdown
    handler so closing `ce gui` never leaves an orphaned `ce doctor` (or
    later, `ce harvest`/`ce produce`/...) process behind."""
    with _lock:
        handles = list(_runs.values())
    for handle in handles:
        if handle.process.poll() is None:
            handle.process.terminate()
