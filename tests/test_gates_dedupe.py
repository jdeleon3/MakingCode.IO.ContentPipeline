"""G3 — dedupe (TDD 6.3, 12 WP-06): blocks above threshold and names the
colliding piece; scoped to published pieces within `scope_days`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from ce import index as index_module
from ce.exit_codes import GateBlocked
from ce.gates import dedupe
from ce.models import Piece, PieceStatus, PublishedInfo

MODEL = "text-embedding-3-small"
NOW = datetime(2026, 7, 27, tzinfo=UTC)

NEAR_IDENTICAL_A = """DuckDB replaced our Spark job for the streaming ETL pipeline.
The join kept spilling to disk once the dataset crossed 40GB, and we
eventually found that increasing the memory limit configuration fixed
the OOM crash we were hitting during the nightly batch run."""

NEAR_IDENTICAL_B = """DuckDB replaced our Spark job for the streaming ETL workload.
The join kept spilling to disk once the dataset crossed 40GB, and we
eventually discovered that increasing the memory limit setting fixed
the OOM crash we kept hitting during the nightly batch run."""

UNRELATED = """My tomato plants finally started fruiting after I switched to a
richer potting soil mix and began watering them every morning before
sunrise. The basil next to them is thriving too, and the whole garden
smells incredible in the summer heat."""


def _seed(
    conn, piece_id, text, client, *, status=PieceStatus.PUBLISHED, published_at=NOW, project="p"
):
    piece = Piece(
        id=piece_id,
        brief_id="br-01",
        project=project,
        slug=piece_id,
        status=status,
        created_at=NOW,
        article_path="article.md",
        published=PublishedInfo(url="https://example.com/x", at=published_at)
        if published_at
        else None,
    )
    index_module.upsert(conn, piece, project, client.embed(text, model=MODEL), MODEL)


@pytest.fixture
def conn(tmp_path):
    connection = index_module.connect(tmp_path / "index.db")
    yield connection
    connection.close()


def test_blocks_above_threshold_and_names_colliding_piece(conn, fake_embeddings_client):
    _seed(conn, "pc-0001", NEAR_IDENTICAL_A, fake_embeddings_client)
    conn.commit()

    candidate = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_B, model=MODEL))

    with pytest.raises(GateBlocked, match="G3") as exc_info:
        dedupe.check(candidate, conn=conn, threshold=0.88, scope_days=365, now=NOW)

    assert "pc-0001" in exc_info.value.message
    assert exc_info.value.exit_code == 2


def test_passes_below_threshold(conn, fake_embeddings_client):
    _seed(conn, "pc-0001", UNRELATED, fake_embeddings_client)
    conn.commit()

    candidate = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_A, model=MODEL))

    dedupe.check(candidate, conn=conn, threshold=0.88, scope_days=365, now=NOW)  # must not raise


def test_max_similarity_returns_score_without_raising(conn, fake_embeddings_client):
    _seed(conn, "pc-0001", NEAR_IDENTICAL_A, fake_embeddings_client)
    conn.commit()

    candidate = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_B, model=MODEL))
    match = dedupe.max_similarity(candidate, conn=conn, scope_days=365, now=NOW)

    assert match is not None
    piece_id, score = match
    assert piece_id == "pc-0001"
    assert score > 0.9


def test_max_similarity_none_when_index_empty(conn, fake_embeddings_client):
    candidate = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_A, model=MODEL))
    assert dedupe.max_similarity(candidate, conn=conn, scope_days=365, now=NOW) is None


def test_non_published_pieces_are_excluded(conn, fake_embeddings_client):
    _seed(conn, "pc-0001", NEAR_IDENTICAL_A, fake_embeddings_client, status=PieceStatus.DRAFTED)
    conn.commit()

    candidate = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_B, model=MODEL))
    assert dedupe.max_similarity(candidate, conn=conn, scope_days=365, now=NOW) is None


def test_pieces_published_outside_scope_days_are_excluded(conn, fake_embeddings_client):
    old_publish = NOW - timedelta(days=400)
    _seed(conn, "pc-0001", NEAR_IDENTICAL_A, fake_embeddings_client, published_at=old_publish)
    conn.commit()

    candidate = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_B, model=MODEL))
    assert dedupe.max_similarity(candidate, conn=conn, scope_days=365, now=NOW) is None


def test_pieces_published_within_scope_days_are_included(conn, fake_embeddings_client):
    recent_publish = NOW - timedelta(days=10)
    _seed(conn, "pc-0001", NEAR_IDENTICAL_A, fake_embeddings_client, published_at=recent_publish)
    conn.commit()

    candidate = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_B, model=MODEL))
    match = dedupe.max_similarity(candidate, conn=conn, scope_days=365, now=NOW)
    assert match is not None
    assert match[0] == "pc-0001"
