"""Capture ingestion package (TDD 10.2, WP-04): audio, screenshots,
screencasts, and friction notes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ce.models import Capture


@dataclass
class BatchOutcome:
    """Result of a `--dir` batch ingest.

    Skip-and-continue: one bad file in a folder of ten shouldn't block the
    other nine. `failed` carries `(path, readable error message)` so the
    caller can print a summary after the batch finishes rather than losing
    partial progress to the first failure.
    """

    succeeded: list[Capture] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
