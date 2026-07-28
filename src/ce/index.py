"""Derived SQLite index (TDD 7, ADR-002/003): piece embeddings for G3 dedupe.

`index.db` holds nothing that isn't reconstructable from `data/` (ADR-002)
— `ce index rebuild` deletes it and walks every project's pieces, embedding
each one's `article.md` and writing the vector back. Similarity is a
brute-force cosine scan over the resulting rows (`gates/dedupe.py`), not a
vector database: ADR-003 bets on staying under ~1,000 documents (TDD 2.5's
scale assumptions), where a full scan is sub-millisecond and sqlite-vec/
Chroma/pgvector would be dependencies bought for no measurable benefit.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from ce import store
from ce.exit_codes import IndexingError
from ce.models import Piece

DEFAULT_INDEX_PATH = Path("data/index.db")


# ---------------------------------------------------------------------------
# Embeddings (OpenAI) — same no-SDK, DI-Protocol shape as WP-02/WP-04's
# LLMClient/TranscriptionClient: one JSON POST doesn't justify an SDK
# dependency, and tests inject a fake rather than hitting the real API.
# ---------------------------------------------------------------------------


class EmbeddingsClient(Protocol):
    def embed(self, text: str, *, model: str) -> list[float]: ...


class OpenAIEmbeddingsClient:
    _URL = "https://api.openai.com/v1/embeddings"

    def __init__(self, *, api_key: str | None = None, timeout: float = 60.0) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._timeout = timeout

    def embed(self, text: str, *, model: str) -> list[float]:
        if not self._api_key:
            raise IndexingError("OPENAI_API_KEY is not set", hint="ce doctor")
        response = httpx.post(
            self._URL,
            json={"model": model, "input": text},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]


# ---------------------------------------------------------------------------
# Schema + serialization
# ---------------------------------------------------------------------------


def connect(index_path: Path) -> sqlite3.Connection:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS piece_embeddings (
            piece_id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            status TEXT NOT NULL,
            published_at TEXT,
            model TEXT NOT NULL,
            embedding BLOB NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _to_blob(vector: list[float]) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


@dataclass(frozen=True)
class IndexedPiece:
    piece_id: str
    project: str
    status: str
    published_at: datetime | None
    embedding: np.ndarray


def upsert(
    conn: sqlite3.Connection,
    piece: Piece,
    project: str,
    embedding: list[float],
    model: str,
) -> None:
    conn.execute(
        """
        INSERT INTO piece_embeddings (piece_id, project, status, published_at, model, embedding)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(piece_id) DO UPDATE SET
            project=excluded.project,
            status=excluded.status,
            published_at=excluded.published_at,
            model=excluded.model,
            embedding=excluded.embedding
        """,
        (
            piece.id,
            project,
            piece.status.value,
            piece.published.at.isoformat() if piece.published else None,
            model,
            _to_blob(embedding),
        ),
    )


def all_rows(conn: sqlite3.Connection) -> list[IndexedPiece]:
    rows = conn.execute(
        "SELECT piece_id, project, status, published_at, embedding FROM piece_embeddings"
    ).fetchall()
    return [
        IndexedPiece(
            piece_id=piece_id,
            project=project,
            status=status,
            published_at=datetime.fromisoformat(published_at) if published_at else None,
            embedding=_from_blob(blob),
        )
        for piece_id, project, status, published_at, blob in rows
    ]


# ---------------------------------------------------------------------------
# rebuild() — `ce index rebuild` (TDD 12 WP-06)
# ---------------------------------------------------------------------------


def rebuild(
    data_root: Path,
    index_path: Path,
    *,
    embeddings_client: EmbeddingsClient,
    model: str,
) -> int:
    """Deletes `index_path` and reconstructs it entirely from `data/`
    (ADR-002's rebuildability requirement). Returns the number of pieces
    indexed. A piece with no `article.md` yet (not drafted) or an empty one
    is skipped — there's nothing to embed.
    """
    index_path.unlink(missing_ok=True)
    conn = connect(index_path)
    count = 0
    try:
        for project in store.list_projects(data_root):
            for piece in store.list_pieces(data_root, project.slug):
                article_path = (
                    store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
                )
                if not article_path.exists():
                    continue
                text = article_path.read_text(encoding="utf-8")
                if not text.strip():
                    continue
                embedding = embeddings_client.embed(text, model=model)
                upsert(conn, piece, project.slug, embedding, model)
                count += 1
        conn.commit()
    finally:
        conn.close()
    return count
