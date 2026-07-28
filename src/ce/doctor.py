"""Environment verification. `ce doctor`.

Reports every external dependency the pipeline needs and whether it is present.

Checks carry a `needed_for` work-package id and a `required` flag. Only
dependencies needed by *already-implemented* work packages are required; the
rest report as pending so `ce doctor` is informative without nagging about
tools you will not touch for another three sessions.

WHEN YOU IMPLEMENT A WORK PACKAGE, flip its dependencies to required=True.
The table below is the single place to do that.

    WP-02  ANTHROPIC_API_KEY (done)
    WP-04  ffmpeg, OPENAI_API_KEY (done)
    WP-05  gitleaks
    WP-11  mermaid-cli, playwright + chromium
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ce import console
from ce.exit_codes import Exit

MIN_PYTHON = (3, 11)


@dataclass
class CheckResult:
    ok: bool
    detail: str = ""


@dataclass
class Check:
    name: str
    probe: Callable[[], CheckResult]
    required: bool
    needed_for: str
    install: str


# --------------------------------------------------------------------------
# Probes
# --------------------------------------------------------------------------


def _run_version(cmd: list[str]) -> CheckResult:
    """Run a --version style command. Never raises."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return CheckResult(False, "not on PATH")
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult(False, f"failed to execute: {exc}")

    output = (proc.stdout or proc.stderr or "").strip()
    first_line = output.splitlines()[0] if output else "(no version output)"
    if proc.returncode != 0 and not output:
        return CheckResult(False, f"exited {proc.returncode}")
    return CheckResult(True, first_line[:70])


def check_python() -> CheckResult:
    v = sys.version_info
    current = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < MIN_PYTHON:
        return CheckResult(False, f"{current} (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")
    return CheckResult(True, current)


def check_git() -> CheckResult:
    return _run_version(["git", "--version"])


def check_ffmpeg() -> CheckResult:
    return _run_version(["ffmpeg", "-version"])


def check_gitleaks() -> CheckResult:
    return _run_version(["gitleaks", "version"])


def check_mermaid() -> CheckResult:
    # shutil.which honours PATHEXT, so mmdc.cmd resolves on Windows.
    return _run_version(["mmdc", "--version"])


def _playwright_browser_root() -> Path:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def check_playwright() -> CheckResult:
    if importlib.util.find_spec("playwright") is None:
        return CheckResult(False, "python package not installed")
    root = _playwright_browser_root()
    if not root.exists():
        return CheckResult(False, "installed, but no browsers downloaded")
    chromium = sorted(root.glob("chromium-*"))
    if not chromium:
        return CheckResult(False, "installed, but chromium missing")
    return CheckResult(True, f"chromium at {chromium[-1].name}")


def _check_env(var: str) -> Callable[[], CheckResult]:
    def probe() -> CheckResult:
        value = os.environ.get(var, "")
        if not value.strip():
            return CheckResult(False, "not set")
        # Never print the value. Length alone confirms it is populated.
        return CheckResult(True, f"set ({len(value)} chars)")

    return probe


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

CHECKS: list[Check] = [
    Check(
        name="python >= 3.11",
        probe=check_python,
        required=True,
        needed_for="WP-00",
        install="Install Python 3.11+ from python.org, recreate the venv.",
    ),
    Check(
        name="git",
        probe=check_git,
        required=True,
        needed_for="WP-00",
        install="https://git-scm.com/downloads",
    ),
    Check(
        name="ANTHROPIC_API_KEY",
        probe=_check_env("ANTHROPIC_API_KEY"),
        required=True,
        needed_for="WP-02",
        install="setx ANTHROPIC_API_KEY sk-ant-...  (then open a new terminal)",
    ),
    Check(
        name="OPENAI_API_KEY",
        probe=_check_env("OPENAI_API_KEY"),
        required=True,
        needed_for="WP-04",
        install="setx OPENAI_API_KEY sk-...  (transcription + embeddings)",
    ),
    Check(
        name="ffmpeg",
        probe=check_ffmpeg,
        required=True,
        needed_for="WP-04",
        install="winget install Gyan.FFmpeg   (or scoop install ffmpeg)",
    ),
    Check(
        name="gitleaks",
        probe=check_gitleaks,
        required=False,
        needed_for="WP-05",
        install="winget install gitleaks   (or scoop install gitleaks)",
    ),
    Check(
        name="mermaid-cli",
        probe=check_mermaid,
        required=False,
        needed_for="WP-11",
        install="npm install -g @mermaid-js/mermaid-cli",
    ),
    Check(
        name="playwright + chromium",
        probe=check_playwright,
        required=False,
        needed_for="WP-11",
        install="pip install playwright && playwright install chromium",
    ),
]


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(strict: bool = False) -> int:
    """Run every check. Returns a process exit code."""
    console.heading("Content Engine - environment check")

    missing_required: list[Check] = []
    missing_pending: list[Check] = []

    width = max(len(c.name) for c in CHECKS)

    for check in CHECKS:
        try:
            result = check.probe()
        except Exception as exc:  # a probe must never take the CLI down
            result = CheckResult(False, f"probe error: {exc}")

        is_required = check.required or strict
        label = check.name.ljust(width)

        if result.ok:
            console.out(
                f"  {console.paint(console.OK, 'green')} {label}  {console.paint(result.detail, 'dim')}"
            )
        elif is_required:
            console.out(f"  {console.paint(console.FAIL, 'red')} {label}  {result.detail}")
            missing_required.append(check)
        else:
            note = f"{result.detail}  (needed for {check.needed_for})"
            console.out(
                f"  {console.paint(console.WARN, 'yellow')} {label}  {console.paint(note, 'dim')}"
            )
            missing_pending.append(check)

    console.out()

    if missing_required:
        noun = "dependency" if len(missing_required) == 1 else "dependencies"
        console.failure(f"{len(missing_required)} required {noun} missing:")
        for check in missing_required:
            console.hint(f"{check.name}: {check.install}")
        return Exit.ERROR

    if missing_pending:
        console.warn(f"{len(missing_pending)} not yet needed (install before the listed WP):")
        for check in missing_pending:
            console.hint(f"{check.name} [{check.needed_for}]: {check.install}")
        console.out()

    console.success("All required dependencies present.")
    return Exit.OK
