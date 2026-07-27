"""WP-01 acceptance: round-trip every entity through the filesystem, and the
`_manifest.json` input-hash mechanics that make stages resumable (TDD §0, §7).
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ce import store
from ce.exit_codes import ConfigError
from ce.models import (
    Brief,
    BriefArchetype,
    BriefDemand,
    BriefEvidence,
    Capture,
    CaptureMoment,
    CaptureType,
    GroundingStrength,
    MetricSnapshot,
    Piece,
    PostPlatform,
    PostRecord,
    Project,
    PublishableLevel,
    RepoRef,
)


def _sample_project(slug="streaming-etl-duckdb") -> Project:
    return Project(
        slug=slug,
        title="Streaming ETL with DuckDB",
        started_at=date(2026, 7, 14),
        repos=[RepoRef(name=slug, path=Path("/code") / slug, publishable=PublishableLevel.FULL)],
    )


def _sample_capture(project_slug: str, capture_id: str = "cap-20260716-1423") -> Capture:
    return Capture(
        id=capture_id,
        project=project_slug,
        type=CaptureType.AUDIO,
        moment=CaptureMoment.IN_SITU,
        captured_at=datetime(2026, 7, 16, 14, 23, tzinfo=UTC),
        source_path=Path("captures/audio/raw/20260716-1423.m4a"),
        context="hit the OOM on the 40GB join",
    )


def _sample_brief(project_slug: str) -> Brief:
    return Brief(
        id="br-01",
        project=project_slug,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="DuckDB's memory limit is not what the docs imply",
        angle="counter-position",
        demand=BriefDemand(recurrence=3, signals=["HN thread"]),
        evidence=[BriefEvidence(kind="git", ref="a3f9c21")],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.31,
        weakest_point="n=1, single workload shape, 40GB",
    )


# --- Project -----------------------------------------------------------------


def test_project_round_trips_through_disk(tmp_path):
    project = _sample_project()
    store.write_project(tmp_path, project)
    assert store.read_project(tmp_path, project.slug) == project


def test_read_missing_project_is_a_readable_error(tmp_path):
    with pytest.raises(ConfigError, match="could not read"):
        store.read_project(tmp_path, "does-not-exist")


# --- Capture ------------------------------------------------------------------


def test_capture_round_trips_and_lists(tmp_path):
    project = _sample_project()
    one = _sample_capture(project.slug, "cap-1")
    two = _sample_capture(project.slug, "cap-2")
    store.write_capture(tmp_path, one)
    store.write_capture(tmp_path, two)

    assert store.read_capture(tmp_path, project.slug, "cap-1") == one
    listed = store.list_captures(tmp_path, project.slug)
    assert {c.id for c in listed} == {"cap-1", "cap-2"}


def test_list_captures_on_untouched_project_is_empty(tmp_path):
    assert store.list_captures(tmp_path, "no-captures-yet") == []


# --- Brief ----------------------------------------------------------------


def test_briefs_round_trip_as_an_array(tmp_path):
    project = _sample_project()
    briefs = [_sample_brief(project.slug)]
    store.write_briefs(tmp_path, project.slug, briefs)
    assert store.read_briefs(tmp_path, project.slug) == briefs


def test_read_briefs_before_any_harvest_is_empty(tmp_path):
    assert store.read_briefs(tmp_path, "no-harvest-yet") == []


# --- Piece ------------------------------------------------------------------


def test_piece_round_trips_through_disk(tmp_path):
    project = _sample_project()
    piece = Piece(
        id="pc-0007",
        brief_id="br-01",
        project=project.slug,
        slug="duckdb-memory-limit-reality",
        created_at=datetime(2026, 7, 26, 9, 0, tzinfo=UTC),
        article_path=Path("article.md"),
    )
    store.write_piece(tmp_path, project.slug, piece)
    assert store.read_piece(tmp_path, project.slug, piece.id) == piece


# --- PostRecord ---------------------------------------------------------------


def test_posted_round_trips_as_a_flat_array(tmp_path):
    records = [
        PostRecord(
            piece_id="pc-0007",
            platform=PostPlatform.LINKEDIN,
            url="https://linkedin.com/posts/example",
            posted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
            metrics=[
                MetricSnapshot(
                    at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
                    impressions=4200,
                    reactions=87,
                    comments=14,
                    site_clicks=133,
                )
            ],
        )
    ]
    store.write_posted(tmp_path, records)
    assert store.read_posted(tmp_path) == records


def test_read_posted_before_anything_shipped_is_empty(tmp_path):
    assert store.read_posted(tmp_path) == []


# --- Manifest / idempotency ---------------------------------------------------


def test_manifest_round_trips(tmp_path):
    store.write_manifest(tmp_path, "hash-a", extra={"commits": 12})
    manifest = store.read_manifest(tmp_path)
    assert manifest.input_hash == "hash-a"
    assert manifest.extra == {"commits": 12}


def test_missing_manifest_reads_as_none(tmp_path):
    assert store.read_manifest(tmp_path) is None


def test_is_stale_true_before_first_run(tmp_path):
    assert store.is_stale(tmp_path, "any-hash") is True


def test_is_stale_false_when_hash_unchanged(tmp_path):
    store.write_manifest(tmp_path, "hash-a")
    assert store.is_stale(tmp_path, "hash-a") is False


def test_is_stale_true_when_hash_changed(tmp_path):
    store.write_manifest(tmp_path, "hash-a")
    assert store.is_stale(tmp_path, "hash-b") is True


def test_hash_inputs_is_stable_and_order_sensitive():
    assert store.hash_inputs("a", "b") == store.hash_inputs("a", "b")
    assert store.hash_inputs("a", "b") != store.hash_inputs("b", "a")


# --- Project summary (the "ce project show" read/format path, TDD 12 WP-01) --


def test_read_project_summary_prints_repos_captures_and_briefs(tmp_path):
    project = _sample_project()
    store.write_project(tmp_path, project)
    store.write_capture(tmp_path, _sample_capture(project.slug))
    store.write_briefs(tmp_path, project.slug, [_sample_brief(project.slug)])

    summary = store.read_project_summary(tmp_path, project.slug)

    assert project.title in summary
    assert project.slug in summary
    assert "captures: 1" in summary
    assert "briefs: 1" in summary
    assert "candidate: 1" in summary  # default Brief.status


def test_format_project_summary_handles_a_bare_project():
    project = _sample_project()
    summary = store.format_project_summary(project, captures=[], briefs=[])
    assert "captures: 0" in summary
    assert "briefs: 0" in summary
