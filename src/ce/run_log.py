"""Per-invocation run logging (TDD §14: "Every run writes
`data/runs/<run-id>-<command>.log`").

This is the single place that decides a run's log path and writes to it.
`cli.main()` calls `tee()` unconditionally, so *every* invocation gets a log
-- whether started from a terminal or shelled out to by `gui/runner.py`
(WP-17, TDD 10.10) -- with one implementation of "how a run is logged", not
two. `gui/runner.py` never writes this file itself; it only tails the path
this module hands back.

No prior WP actually built this despite §14 describing it as an existing,
system-wide behavior -- WP-17 is the first WP whose own Done-when line
depends on the log genuinely existing (`runner.py` tails it), so it's built
here. See STATUS.md's WP-17 deviations entry.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

# Strips the ANSI colour/cursor codes console.py emits for a real terminal
# (console.COLOR is decided once at import time from the *original* stdout,
# before this module ever wraps it) -- the log file is meant to be plain text
# a GUI can render directly, not a terminal replay.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

RUN_ID_ENV_VAR = "CE_RUN_ID"


def new_run_id() -> str:
    """A fresh, filesystem-safe, lexically sortable run id.

    No colons (Windows forbids them in paths) and microsecond resolution --
    the GUI can trigger several runs within the same wall-clock second.
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")


def command_name(argv: list[str]) -> str:
    """Derive the '<command>' half of the log filename from argv, e.g.
    ``["doctor"]`` -> ``"doctor"``, ``["brief", "select", "br-01"]`` ->
    ``"brief-select"``, ``["gui", "--port", "8420"]`` -> ``"gui"``.

    Not a real argv parser: it just takes the leading run of non-flag
    tokens (stopping at the first token starting with "-"), capped at two,
    since every command in TDD 9's contract is either a bare command or a
    ``<group> <subcommand>`` pair before any positional/flag arguments. Good
    enough for a readable filename; it doesn't need to know Typer's schema.
    """
    parts: list[str] = []
    for tok in argv:
        if tok.startswith("-"):
            break
        parts.append(tok)
        if len(parts) >= 2:
            break
    return "-".join(parts) if parts else "ce"


def run_log_path(data_root: Path, run_id: str, command: str) -> Path:
    return data_root / "runs" / f"{run_id}-{command}.log"


class _Tee:
    """Writes every chunk to the real stream, and an ANSI-stripped copy to
    the run log. Mimics enough of TextIO for `print()`/click's own writes."""

    def __init__(self, real: TextIO, log_file: TextIO) -> None:
        self._real = real
        self._log = log_file

    def write(self, text: str) -> int:
        written = self._real.write(text)
        self._log.write(_ANSI_RE.sub("", text))
        self._log.flush()
        return written

    def flush(self) -> None:
        self._real.flush()
        self._log.flush()

    def isatty(self) -> bool:
        return self._real.isatty()

    def __getattr__(self, name: str):
        return getattr(self._real, name)


@contextmanager
def tee(data_root: Path, argv: list[str]) -> Iterator[Path]:
    """Tee stdout/stderr to `data/runs/<run-id>-<command>.log` for the
    duration of the block; yields the log path.

    `run_id` comes from the `CE_RUN_ID` environment variable if
    `gui/runner.py` set it before launching this process -- that lets the
    parent predict the exact log path without racing this module to
    generate its own timestamp. A plain terminal invocation (no GUI
    involved) has no such env var and gets a fresh one generated here.
    """
    run_id = os.environ.get(RUN_ID_ENV_VAR) or new_run_id()
    command = command_name(argv)
    path = run_log_path(data_root, run_id, command)
    path.parent.mkdir(parents=True, exist_ok=True)

    log_file = path.open("a", encoding="utf-8")
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = _Tee(real_out, log_file)  # type: ignore[assignment]
    sys.stderr = _Tee(real_err, log_file)  # type: ignore[assignment]
    try:
        yield path
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        log_file.close()
