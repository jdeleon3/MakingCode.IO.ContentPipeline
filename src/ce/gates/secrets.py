"""G2 — secret scan (TDD 6.2; ADR-005 non-bypassable, not configurable).

Two layers, both applied before anything from a repo can reach an LLM:

1. A path deny-list (`DENY_GLOBS`), applied before any file content is read
   at all — a denied file is never opened, never copied into the staging
   directory `GitleaksScanner` points gitleaks at, never scanned.
2. `gitleaks detect --report-format json --no-git` over whatever the
   deny-list left standing. `--no-git` scans a plain directory of files
   rather than walking commit history — paired with a deny-list that only
   makes sense against on-disk paths (not per-commit diffs), that's the
   right mode here.

`gitleaks` itself is reached through the `SecretScanner` Protocol — the same
DI shape WP-04 used for `ffmpeg`/the transcription API
(`capture/audio.py`). This dev environment has no `gitleaks` binary at all
(confirmed via `ce doctor`), so the mandatory planted-secret test (TDD 12
WP-05, TDD 13 #2) injects a fake scanner that does real regex detection
against real fixture-repo content — not a canned response — and the real
`GitleaksScanner` is exercised manually on a machine that has gitleaks
installed.
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import BaseModel

from ce.exit_codes import GateBlocked

# TDD 6.2's fixed deny-list. Every pattern here reduces to "does some path
# component match this glob", once directory markers (`secrets/`) and `**`
# traversal segments (`**/fixtures/**`) are stripped — nothing in this list
# needs to match more than one path component at a time.
DENY_GLOBS: list[str] = [
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "secrets/",
    "credentials*",
    "*.tfstate",
    ".npmrc",
    ".pypirc",
    "**/fixtures/**",
    "**/seed*/**",
]


def _pattern_component(pattern: str) -> str:
    core = pattern.strip("/")
    segments = [s for s in core.split("/") if s not in ("", "**")]
    return segments[0] if segments else core


_DENY_COMPONENTS = [_pattern_component(p) for p in DENY_GLOBS]


def is_denied(relative_path: str) -> bool:
    """True if `relative_path` (posix-style, relative to a repo root)
    matches any TDD 6.2 deny-list pattern, at any depth."""
    parts = PurePosixPath(relative_path).parts
    return any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in _DENY_COMPONENTS)


def list_scannable_files(repo_path: Path) -> list[Path]:
    """Every file `git ls-files` tracks, minus the deny-list — the set that
    is actually allowed to have its content read by anything downstream."""
    proc = subprocess.run(  # noqa: S603
        ["git", "ls-files"], cwd=repo_path, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return []
    return [
        repo_path / rel for rel in proc.stdout.splitlines() if rel.strip() and not is_denied(rel)
    ]


class SecretFinding(BaseModel):
    rule_id: str
    file: str
    line: int | None = None
    match: str  # truncated — never the full raw secret verbatim


class SecretScanner(Protocol):
    def scan(self, repo_path: Path, files: list[Path]) -> list[SecretFinding]: ...


class GitleaksScanner:
    """Real implementation. Copies only the deny-list-surviving files into a
    temp staging directory (mirroring their relative paths) and points
    gitleaks at *that* — so a denied file's content is never read by
    anything, gitleaks included, rather than merely having its findings
    discarded after the fact.
    """

    def scan(self, repo_path: Path, files: list[Path]) -> list[SecretFinding]:
        if shutil.which("gitleaks") is None:
            raise GateBlocked("G2", "gitleaks is not on PATH", hint="ce doctor")

        with tempfile.TemporaryDirectory(prefix="ce-gitleaks-") as staging:
            staging_path = Path(staging)
            for f in files:
                rel = f.relative_to(repo_path)
                dest = staging_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)

            proc = subprocess.run(  # noqa: S603
                [
                    "gitleaks",
                    "detect",
                    "--source",
                    str(staging_path),
                    "--report-format",
                    "json",
                    "--no-git",
                    "--exit-code",
                    "0",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        if not proc.stdout.strip():
            return []
        raw = json.loads(proc.stdout)
        return [
            SecretFinding(
                rule_id=item.get("RuleID", "unknown"),
                file=item.get("File", ""),
                line=item.get("StartLine"),
                match=str(item.get("Match", ""))[:80],
            )
            for item in raw
        ]


def scan_repo(repo_path: Path, scanner: SecretScanner) -> tuple[list[SecretFinding], int]:
    """Runs the deny-list filter then the scanner. Returns
    `(findings, scanned_count)` — `scanned_count` is what `git.json`'s
    `redaction.scanned` field records on a clean run."""
    files = list_scannable_files(repo_path)
    return scanner.scan(repo_path, files), len(files)


def write_redaction_report(path: Path, repo_path: Path, findings: list[SecretFinding]) -> None:
    """Written only when G2 blocks a run (TDD 10.3 step 4) — a clean scan
    never produces this file, only the `redaction: {findings: 0}` summary
    embedded in `git.json`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "repo": str(repo_path),
        "findings": [f.model_dump() for f in findings],
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
