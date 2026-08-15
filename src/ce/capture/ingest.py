"""Screenshot, screencast, and friction-note capture (TDD 10.2, WP-04 —
the repo layout comment names this module for "screenshots, screencasts,
friction.md", as `capture/audio.py`'s sibling).
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from ce import store
from ce.capture import BatchOutcome
from ce.exit_codes import CaptureError, CEError
from ce.models import Capture, CaptureDerived, CaptureMoment, CaptureType

# TDD doesn't specify how `ce capture screen` tells a screenshot from a
# screencast — classifying by extension is the obvious rule and keeps the
# CLI contract's single `capture screen <file>` command unchanged.
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
_SCREEN_EXTENSIONS = _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS


def _classify(path: Path) -> CaptureType:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        return CaptureType.SCREENSHOT
    if suffix in _VIDEO_EXTENSIONS:
        return CaptureType.SCREENCAST
    raise CaptureError(
        f"unrecognized screen-capture file type: {suffix or '(no extension)'}",
        hint="expected an image (png/jpg/gif/webp/bmp) or video (mp4/mov/webm/mkv) file",
    )


def ingest_screen(
    data_root: Path,
    path: Path,
    project: str,
    *,
    context: str | None = None,
    captured_at: datetime | None = None,
) -> Capture:
    """`ce capture screen`."""
    if not path.exists():
        raise CaptureError(f"file not found: {path}")

    capture_type = _classify(path)
    captured_at = captured_at or datetime.now(UTC)
    capture_id = store.generate_capture_id(data_root, project, captured_at)

    project_root = store.project_dir(data_root, project)
    subdir = "screens" if capture_type is CaptureType.SCREENSHOT else "screencast"
    dest_dir = project_root / "captures" / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{capture_id}{path.suffix}"
    shutil.copy2(path, dest)

    capture = Capture(
        id=capture_id,
        project=project,
        type=capture_type,
        moment=CaptureMoment.IN_SITU,
        captured_at=captured_at,
        source_path=dest.relative_to(project_root),
        context=context,
    )
    store.write_capture(data_root, capture)
    return capture


def append_friction(
    data_root: Path,
    project: str,
    note: str,
    *,
    captured_at: datetime | None = None,
) -> Capture:
    """`ce capture friction`. Appends a timestamped line to the project's
    hand-maintained `friction.md` *and* records a `Capture` (type=friction)
    so `ce capture list` sees it alongside audio/screenshot/screencast
    captures — TDD 5.2's `capture.yml` schema lists `friction` as one of
    the four capture types, even though the CLI contract's own help text
    for this command only mentions the file append.
    """
    captured_at = captured_at or datetime.now(UTC)
    capture_id = store.generate_capture_id(data_root, project, captured_at)

    project_root = store.project_dir(data_root, project)
    friction_path = project_root / "captures" / "friction.md"
    friction_path.parent.mkdir(parents=True, exist_ok=True)
    with friction_path.open("a", encoding="utf-8") as handle:
        handle.write(f"- {captured_at:%Y-%m-%d %H:%M} {note}\n")

    capture = Capture(
        id=capture_id,
        project=project,
        type=CaptureType.FRICTION,
        moment=CaptureMoment.IN_SITU,
        captured_at=captured_at,
        source_path=friction_path.relative_to(project_root),
        context=note,
    )
    store.write_capture(data_root, capture)
    return capture


def ingest_note(
    data_root: Path,
    path: Path,
    project: str,
    *,
    moment: CaptureMoment = CaptureMoment.RETRO,
    context: str | None = None,
    captured_at: datetime | None = None,
) -> Capture:
    """`ce capture note`. Ingests a pre-written text file whole (copied
    verbatim into `captures/notes/`), with `derived.transcript_clean`
    pointing at the copy so `harvest/inventory.py::_format_captures_context`
    expands it fully into brief-generation context, the same treatment an
    audio capture's transcript already gets — see CaptureType.NOTE's own
    docstring for why neither FRICTION nor a bare `context` string fits."""
    if not path.exists():
        raise CaptureError(f"file not found: {path}")

    captured_at = captured_at or datetime.now(UTC)
    capture_id = store.generate_capture_id(data_root, project, captured_at)

    project_root = store.project_dir(data_root, project)
    dest_dir = project_root / "captures" / "notes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{capture_id}{path.suffix or '.md'}"
    shutil.copy2(path, dest)

    capture = Capture(
        id=capture_id,
        project=project,
        type=CaptureType.NOTE,
        moment=moment,
        captured_at=captured_at,
        source_path=dest.relative_to(project_root),
        derived=CaptureDerived(transcript_clean=dest.relative_to(project_root)),
        context=context,
    )
    store.write_capture(data_root, capture)
    return capture


def find_screen_files(dir_path: Path) -> list[Path]:
    """Every top-level file in `dir_path` with a recognized image/video
    extension, name-sorted. Not recursive."""
    return sorted(
        p for p in dir_path.iterdir() if p.is_file() and p.suffix.lower() in _SCREEN_EXTENSIONS
    )


def ingest_screen_batch(
    data_root: Path,
    dir_path: Path,
    project: str,
    *,
    context: str | None = None,
) -> BatchOutcome:
    """`ce capture screen --dir`. Skip-and-continue: one bad file doesn't
    block the rest of the folder — see `ce.capture.BatchOutcome`."""
    outcome = BatchOutcome()
    for path in find_screen_files(dir_path):
        try:
            outcome.succeeded.append(ingest_screen(data_root, path, project, context=context))
        except CEError as exc:
            outcome.failed.append((path, exc.message))
    return outcome


def list_captures(data_root: Path, project: str) -> list[Capture]:
    """`ce capture list <project>` — every capture, oldest first."""
    return sorted(store.list_captures(data_root, project), key=lambda c: c.captured_at)
