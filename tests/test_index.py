"""WP-06 acceptance (TDD 12): `ce index rebuild` reconstructs `index.db`
entirely from `data/`; cosine similarity separates near-identical text
from unrelated text at the thresholds the Done-when line names.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from ce import index as index_module
from ce import store
from ce.models import Piece, PieceStatus, Project, PublishedInfo

MODEL = "text-embedding-3-small"

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


def _make_project(data_root: Path, slug: str = "test-proj") -> Project:
    project = Project(slug=slug, title=slug, started_at=date(2026, 1, 1))
    store.write_project(data_root, project)
    store.scaffold_project_tree(data_root, slug)
    return project


def _make_piece(
    data_root: Path,
    slug: str,
    piece_id: str,
    *,
    text: str | None,
    status: PieceStatus = PieceStatus.DRAFTED,
    published_at: datetime | None = None,
) -> Piece:
    piece = Piece(
        id=piece_id,
        brief_id="br-01",
        project=slug,
        slug=piece_id,
        status=status,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        article_path=Path("article.md"),
        published=PublishedInfo(url=f"https://example.com/{piece_id}", at=published_at)
        if published_at
        else None,
    )
    store.write_piece(data_root, slug, piece)
    if text is not None:
        piece_dir = store.piece_dir(data_root, slug, piece_id)
        (piece_dir / "article.md").write_text(text, encoding="utf-8")
    return piece


# ---------------------------------------------------------------------------
# Cosine similarity thresholds (TDD 12 WP-06 Done-when)
# ---------------------------------------------------------------------------


def test_near_identical_texts_score_above_point_nine(fake_embeddings_client):
    a = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_A, model=MODEL))
    b = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_B, model=MODEL))
    assert index_module.cosine_similarity(a, b) > 0.9


def test_unrelated_texts_score_below_point_five(fake_embeddings_client):
    a = np.asarray(fake_embeddings_client.embed(NEAR_IDENTICAL_A, model=MODEL))
    c = np.asarray(fake_embeddings_client.embed(UNRELATED, model=MODEL))
    assert index_module.cosine_similarity(a, c) < 0.5


def test_cosine_similarity_of_identical_vector_is_one():
    v = np.array([1.0, 2.0, 3.0])
    assert index_module.cosine_similarity(v, v) == 1.0


def test_cosine_similarity_handles_zero_vector():
    zero = np.zeros(4)
    other = np.array([1.0, 0.0, 0.0, 0.0])
    assert index_module.cosine_similarity(zero, other) == 0.0


# ---------------------------------------------------------------------------
# rebuild() — reconstructs entirely from data/ (ADR-002)
# ---------------------------------------------------------------------------


def test_rebuild_indexes_pieces_with_an_article(tmp_path, fake_embeddings_client):
    data_root = tmp_path / "data"
    _make_project(data_root)
    _make_piece(data_root, "test-proj", "pc-0001", text=NEAR_IDENTICAL_A)
    _make_piece(data_root, "test-proj", "pc-0002", text=None)  # not drafted yet -- no article.md
    _make_piece(
        data_root, "test-proj", "pc-0003", text="   \n  "
    )  # blank article -- nothing to embed

    index_path = data_root / "index.db"
    count = index_module.rebuild(
        data_root, index_path, embeddings_client=fake_embeddings_client, model=MODEL
    )

    assert count == 1
    conn = index_module.connect(index_path)
    rows = index_module.all_rows(conn)
    conn.close()
    assert [r.piece_id for r in rows] == ["pc-0001"]


def test_rebuild_reconstructs_after_deleting_index_db(tmp_path, fake_embeddings_client):
    data_root = tmp_path / "data"
    _make_project(data_root)
    _make_piece(data_root, "test-proj", "pc-0001", text=NEAR_IDENTICAL_A)
    _make_piece(data_root, "test-proj", "pc-0002", text=UNRELATED)

    index_path = data_root / "index.db"
    index_module.rebuild(
        data_root, index_path, embeddings_client=fake_embeddings_client, model=MODEL
    )
    conn = index_module.connect(index_path)
    first_rows = {r.piece_id: r.embedding.tolist() for r in index_module.all_rows(conn)}
    conn.close()

    assert index_path.exists()
    index_path.unlink()
    assert not index_path.exists()

    index_module.rebuild(
        data_root, index_path, embeddings_client=fake_embeddings_client, model=MODEL
    )
    conn = index_module.connect(index_path)
    second_rows = {r.piece_id: r.embedding.tolist() for r in index_module.all_rows(conn)}
    conn.close()

    assert second_rows == first_rows
    assert set(second_rows) == {"pc-0001", "pc-0002"}


def test_upsert_roundtrips_status_and_published_at(tmp_path, fake_embeddings_client):
    data_root = tmp_path / "data"
    published_at = datetime(2026, 6, 1, tzinfo=UTC)
    _make_project(data_root)
    _make_piece(
        data_root,
        "test-proj",
        "pc-0001",
        text=NEAR_IDENTICAL_A,
        status=PieceStatus.PUBLISHED,
        published_at=published_at,
    )

    index_path = data_root / "index.db"
    index_module.rebuild(
        data_root, index_path, embeddings_client=fake_embeddings_client, model=MODEL
    )

    conn = index_module.connect(index_path)
    [row] = index_module.all_rows(conn)
    conn.close()

    assert row.status == "published"
    assert row.published_at == published_at
    assert row.project == "test-proj"


# --- OpenAIEmbeddingsClient error wrapping ------------------------------------


def test_openai_embeddings_client_wraps_http_errors_readably(tmp_path):
    """Without wrapping, an SDK error surfaces as a raw traceback with no
    visible status code or API error message (same class of regression as
    `OpenAITranscriptionClient` -- see test_capture_audio.py)."""
    import httpx
    import openai
    import pytest

    from ce.exit_codes import IndexingError

    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(401, request=request)
    api_error = openai.APIStatusError(
        "Incorrect API key provided",
        response=response,
        body={"error": {"message": "Incorrect API key provided"}},
    )

    class _FakeEmbeddings:
        def create(self, **kwargs):
            raise api_error

    class _FakeOpenAIClient:
        embeddings = _FakeEmbeddings()

    client = index_module.OpenAIEmbeddingsClient(api_key="sk-test")
    client._get_client = lambda: _FakeOpenAIClient()

    with pytest.raises(IndexingError, match="401") as excinfo:
        client.embed("some text", model="text-embedding-3-small")
    assert "Incorrect API key" in excinfo.value.message
