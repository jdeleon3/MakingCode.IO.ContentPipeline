"""WP-01 acceptance: every TDD 5.2 entity round-trips through YAML-shaped data."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ce.models import (
    Brief,
    BriefArchetype,
    BriefDemand,
    BriefEvidence,
    Capture,
    CaptureDerived,
    CaptureMoment,
    CaptureType,
    GradeAttempt,
    GradeScores,
    GroundingStrength,
    MetricSnapshot,
    Piece,
    PieceStatus,
    PostPlatform,
    PostRecord,
    Project,
    ProjectStatus,
    PublishableLevel,
    PublishedInfo,
    RepoRef,
    Selection,
    VerificationSummary,
)


def _round_trip(model):
    """Every entity must survive dump(mode='json') -> validate, since that is
    exactly the path store.py uses to write and read YAML."""
    return type(model).model_validate(model.model_dump(mode="json"))


# --- RepoRef / PublishableLevel --------------------------------------------


def test_repo_ref_expands_and_resolves_home(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    monkeypatch.setenv("HOME", str(tmp_path))  # POSIX
    ref = RepoRef(name="x", path="~/code/x", publishable="full")
    assert ref.path.is_absolute()
    assert str(ref.path).startswith(str(tmp_path)), "~ should expand against the (mocked) home dir"
    assert ".." not in ref.path.parts


def test_publishable_level_uses_hyphenated_value():
    """TDD 5.2 literally writes `publishable: lessons-only` — the enum value
    must match exactly or round-tripping hand-written YAML would fail."""
    assert PublishableLevel.LESSONS_ONLY.value == "lessons-only"


# --- Project ------------------------------------------------------------


def test_project_round_trips(tmp_path):
    project = Project(
        slug="streaming-etl-duckdb",
        title="Streaming ETL with DuckDB",
        status=ProjectStatus.ACTIVE,
        started_at=date(2026, 7, 14),
        repos=[RepoRef(name="streaming-etl", path=tmp_path, publishable=PublishableLevel.FULL)],
        selection=Selection(
            demand_signals=["HN 3 threads", "inbound x2"],
            hypothesis="DuckDB replaces Spark for <100GB workloads",
            expected_failure_surface="memory limits on joins",
        ),
        tags=["duckdb", "etl", "data"],
    )
    restored = _round_trip(project)
    assert restored == project


def test_project_slug_rejects_invalid_characters():
    with pytest.raises(ValidationError, match="slug"):
        Project(slug="Not Valid!", title="x", started_at=date(2026, 1, 1))


# --- Capture ----------------------------------------------------------------


def test_capture_round_trips_with_derived():
    capture = Capture(
        id="cap-20260716-1423",
        project="streaming-etl-duckdb",
        type=CaptureType.AUDIO,
        moment=CaptureMoment.IN_SITU,
        captured_at=datetime(2026, 7, 16, 14, 23, tzinfo=UTC),
        source_path=Path("captures/audio/raw/20260716-1423.m4a"),
        derived=CaptureDerived(
            transcript_raw=Path("captures/audio/transcript/cap-20260716-1423.raw.txt"),
            transcript_clean=Path("captures/audio/transcript/cap-20260716-1423.clean.md"),
            duration_sec=94,
        ),
        context="hit the OOM on the 40GB join",
    )
    assert _round_trip(capture) == capture


def test_capture_derived_is_optional():
    capture = Capture(
        id="cap-friction-1",
        project="p",
        type=CaptureType.FRICTION,
        moment=CaptureMoment.IN_SITU,
        captured_at=datetime.now(UTC),
        source_path=Path("captures/friction.md"),
    )
    assert capture.derived is None
    assert _round_trip(capture).derived is None


# --- Brief --------------------------------------------------------------


def _sample_brief(**overrides) -> Brief:
    defaults = dict(
        id="br-01",
        project="streaming-etl-duckdb",
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="DuckDB's memory limit is not what the docs imply",
        angle="counter-position",
        target_platforms=["site", "linkedin"],
        demand=BriefDemand(recurrence=3, signals=["HN thread 412pts"]),
        evidence=[
            BriefEvidence(
                kind="git", ref="a3f9c21", note="reverted the streaming join, -340 lines"
            ),
            BriefEvidence(kind="audio", ref="cap-20260716-1423@02:10", quote="it just died"),
        ],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.31,
        weakest_point="n=1, single workload shape, 40GB",
    )
    defaults.update(overrides)
    return Brief(**defaults)


def test_brief_round_trips():
    brief = _sample_brief()
    assert _round_trip(brief) == brief


def test_brief_evidence_kind_is_not_restricted_to_a_fixed_enum():
    """Only the archetype enum is fixed (TDD 5.3); evidence `kind` is produced
    by WP-05/WP-07, which are not built yet, so it stays a free string."""
    brief = _sample_brief(evidence=[BriefEvidence(kind="external", ref="https://example.com")])
    assert brief.evidence[0].kind == "external"


def test_brief_dedupe_similarity_must_be_a_fraction():
    with pytest.raises(ValidationError, match="dedupe_max_similarity"):
        _sample_brief(dedupe_max_similarity=1.5)


# --- Piece ----------------------------------------------------------------


def test_piece_round_trips_with_full_lifecycle():
    piece = Piece(
        id="pc-0007",
        brief_id="br-01",
        project="streaming-etl-duckdb",
        slug="duckdb-memory-limit-reality",
        status=PieceStatus.PUBLISHED,
        created_at=datetime(2026, 7, 26, 9, 0, tzinfo=UTC),
        article_path=Path("article.md"),
        generated_at=datetime(2026, 7, 26, 9, 4, 11, tzinfo=UTC),
        grades=[
            GradeAttempt(
                attempt=1,
                total=6.8,
                scores=GradeScores(hook=6, evidence=8, specificity=7, voice=6, cta=5),
            ),
            GradeAttempt(
                attempt=2,
                total=8.4,
                scores=GradeScores(hook=9, evidence=9, specificity=8, voice=7, cta=7),
            ),
        ],
        verification=VerificationSummary(
            claims_checked=7, claims_failed=0, ran_at=datetime(2026, 7, 26, 10, 30, tzinfo=UTC)
        ),
        published=PublishedInfo(
            url="https://example.com/blog/duckdb-memory-limit-reality",
            at=datetime(2026, 7, 26, 11, 0, tzinfo=UTC),
        ),
    )
    assert _round_trip(piece) == piece


def test_piece_defaults_have_no_grades_or_verification():
    piece = Piece(
        id="pc-0001",
        brief_id="br-01",
        project="p",
        slug="s",
        created_at=datetime.now(UTC),
        article_path=Path("article.md"),
    )
    assert piece.grades == []
    assert piece.verification is None
    assert piece.published is None


# --- PostRecord ------------------------------------------------------------


def test_post_record_round_trips():
    record = PostRecord(
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
    assert _round_trip(record) == record
