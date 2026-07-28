"""WP-04 acceptance: screenshot/screencast/friction capture and `ce capture
list` showing all four capture types (TDD 12 WP-04 Done-when)."""

from pathlib import Path

import pytest

from ce import store
from ce.capture import audio, ingest
from ce.exit_codes import CaptureError
from ce.models import CaptureMoment, CaptureType


def _touch(path: Path, content: bytes = b"fake") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# --- ingest_screen ------------------------------------------------------------


def test_ingest_screen_classifies_image_as_screenshot(tmp_path):
    src = _touch(tmp_path / "shot.png")
    captured = ingest.ingest_screen(tmp_path, src, "test-proj", context="the error dialog")

    assert captured.type == CaptureType.SCREENSHOT
    assert captured.context == "the error dialog"
    dest = store.project_dir(tmp_path, "test-proj") / captured.source_path
    assert dest.exists()
    assert dest.parent.name == "screens"


def test_ingest_screen_classifies_video_as_screencast(tmp_path):
    src = _touch(tmp_path / "recording.mp4")
    captured = ingest.ingest_screen(tmp_path, src, "test-proj")

    assert captured.type == CaptureType.SCREENCAST
    dest = store.project_dir(tmp_path, "test-proj") / captured.source_path
    assert dest.parent.name == "screencast"


def test_ingest_screen_rejects_unknown_extension(tmp_path):
    src = _touch(tmp_path / "notes.txt")
    with pytest.raises(CaptureError, match="unrecognized"):
        ingest.ingest_screen(tmp_path, src, "test-proj")


def test_ingest_screen_missing_file_is_a_readable_error(tmp_path):
    with pytest.raises(CaptureError, match="not found"):
        ingest.ingest_screen(tmp_path, tmp_path / "nope.png", "test-proj")


def test_ingest_screen_persists_the_capture_record(tmp_path):
    src = _touch(tmp_path / "shot.png")
    captured = ingest.ingest_screen(tmp_path, src, "test-proj")
    assert store.read_capture(tmp_path, "test-proj", captured.id) == captured


# --- ingest_screen_batch (--dir) ------------------------------------------------


def test_find_screen_files_filters_by_extension_not_recursive(tmp_path):
    folder = tmp_path / "screens"
    _touch(folder / "a.png")
    _touch(folder / "b.mp4")
    _touch(folder / "notes.txt")  # not a screen extension -- excluded
    _touch(folder / "sub" / "c.png")  # nested -- not scanned

    found = ingest.find_screen_files(folder)
    assert [p.name for p in found] == ["a.png", "b.mp4"]


def test_ingest_screen_batch_ingests_every_matching_file(tmp_path):
    folder = tmp_path / "screens"
    _touch(folder / "a.png")
    _touch(folder / "b.mp4")
    _touch(folder / "irrelevant.txt")  # skipped by extension filter, not a failure

    outcome = ingest.ingest_screen_batch(tmp_path, folder, "test-proj")

    assert len(outcome.succeeded) == 2
    assert outcome.failed == []
    assert {c.type for c in outcome.succeeded} == {CaptureType.SCREENSHOT, CaptureType.SCREENCAST}


def test_ingest_screen_batch_skip_and_continue_on_bad_file(tmp_path, monkeypatch):
    """One bad file shouldn't block the rest of the folder (the design
    explicitly chosen over stop-on-first-failure)."""
    folder = tmp_path / "screens"
    _touch(folder / "a.png")
    _touch(folder / "b.png")
    _touch(folder / "c.png")

    real_ingest_screen = ingest.ingest_screen

    def flaky_ingest_screen(data_root, path, project, **kwargs):
        if path.name == "b.png":
            raise CaptureError("simulated failure")
        return real_ingest_screen(data_root, path, project, **kwargs)

    monkeypatch.setattr(ingest, "ingest_screen", flaky_ingest_screen)

    outcome = ingest.ingest_screen_batch(tmp_path, folder, "test-proj")

    # ingest_screen renames files to capture-id-based names, so succeeded
    # captures can't be matched back to "a.png"/"c.png" by filename -- the
    # count plus the identified failure is what proves skip-and-continue.
    assert len(outcome.succeeded) == 2
    assert len(outcome.failed) == 1
    assert outcome.failed[0][0].name == "b.png"
    assert "simulated failure" in outcome.failed[0][1]


def test_ingest_screen_batch_empty_folder_is_empty_outcome(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    outcome = ingest.ingest_screen_batch(tmp_path, folder, "test-proj")
    assert outcome.succeeded == []
    assert outcome.failed == []


# --- append_friction ------------------------------------------------------------


def test_append_friction_writes_to_friction_md(tmp_path):
    store.scaffold_project_tree(tmp_path, "test-proj")
    ingest.append_friction(tmp_path, "test-proj", "the OOM hit at the 40GB join")

    friction_path = store.project_dir(tmp_path, "test-proj") / "captures" / "friction.md"
    text = friction_path.read_text(encoding="utf-8")
    assert "the OOM hit at the 40GB join" in text


def test_append_friction_appends_without_clobbering(tmp_path):
    store.scaffold_project_tree(tmp_path, "test-proj")
    ingest.append_friction(tmp_path, "test-proj", "first note")
    ingest.append_friction(tmp_path, "test-proj", "second note")

    friction_path = store.project_dir(tmp_path, "test-proj") / "captures" / "friction.md"
    text = friction_path.read_text(encoding="utf-8")
    assert "first note" in text
    assert "second note" in text


def test_append_friction_records_a_capture(tmp_path):
    captured = ingest.append_friction(tmp_path, "test-proj", "surprising thing")
    assert captured.type == CaptureType.FRICTION
    assert captured.context == "surprising thing"
    assert store.read_capture(tmp_path, "test-proj", captured.id) == captured


# --- list_captures --------------------------------------------------------------


def test_list_captures_shows_all_four_types(tmp_path):
    audio.ingest(tmp_path, _touch(tmp_path / "a.wav"), "test-proj", moment=CaptureMoment.IN_SITU)
    ingest.ingest_screen(tmp_path, _touch(tmp_path / "b.png"), "test-proj")
    ingest.ingest_screen(tmp_path, _touch(tmp_path / "c.mp4"), "test-proj")
    ingest.append_friction(tmp_path, "test-proj", "note")

    captures = ingest.list_captures(tmp_path, "test-proj")
    assert {c.type for c in captures} == {
        CaptureType.AUDIO,
        CaptureType.SCREENSHOT,
        CaptureType.SCREENCAST,
        CaptureType.FRICTION,
    }


def test_list_captures_sorted_oldest_first(tmp_path):
    from datetime import UTC, datetime

    early = ingest.append_friction(
        tmp_path, "test-proj", "early", captured_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    late = ingest.append_friction(
        tmp_path, "test-proj", "late", captured_at=datetime(2026, 6, 1, tzinfo=UTC)
    )

    captures = ingest.list_captures(tmp_path, "test-proj")
    assert [c.id for c in captures] == [early.id, late.id]


def test_list_captures_empty_project_is_empty(tmp_path):
    assert ingest.list_captures(tmp_path, "no-captures-yet") == []
