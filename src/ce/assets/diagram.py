"""Mermaid source -> PNG via `mermaid-cli` (TDD 10.7).

Reached through a `DiagramRenderer` Protocol, same DI shape as every other
external-binary seam in this codebase (WP-04's `Preprocessor`, WP-05's
`SecretScanner`). Not optional here, the way it was mostly-a-style-choice
for WP-02's `AnthropicClient`: this dev environment has no `mermaid-cli`
on PATH at all (confirmed via `ce doctor`), so the automated suite cannot
invoke the real thing regardless of preference. Tests inject a fake; the
real `MermaidCliRenderer` is exercised only manually on a machine that has
`mermaid-cli` installed.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from ce.exit_codes import AssetError

DEFAULT_WIDTH = 1600  # TDD 10.7: "1600px wide, transparent"


class DiagramRenderer(Protocol):
    def render(self, mermaid_source: str, output_path: Path, *, width: int) -> None: ...


class MermaidCliRenderer:
    """Shells out to `mmdc` (mermaid-cli) with a transparent background."""

    def render(self, mermaid_source: str, output_path: Path, *, width: int = DEFAULT_WIDTH) -> None:
        # Resolve to a full path (not just check-and-discard): on Windows
        # shutil.which("mmdc") resolves the PATHEXT shim mmdc.CMD, but
        # subprocess.run(["mmdc", ...]) with the bare name fails with
        # WinError 2 -- CreateProcess doesn't apply PATHEXT resolution
        # itself without a shell, so the resolved path must be reused below.
        exe = shutil.which("mmdc")
        if exe is None:
            raise AssetError(
                "mermaid-cli (mmdc) is not on PATH",
                hint="npm install -g @mermaid-js/mermaid-cli, then `ce doctor`",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".mmd", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(mermaid_source)
            source_path = Path(handle.name)
        try:
            proc = subprocess.run(
                [
                    exe,
                    "-i",
                    str(source_path),
                    "-o",
                    str(output_path),
                    "-w",
                    str(width),
                    "-b",
                    "transparent",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            source_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            raise AssetError(f"mermaid-cli failed: {proc.stderr[-2000:]}")
