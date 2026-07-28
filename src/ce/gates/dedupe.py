"""G3 — dedupe (TDD 6.3; bypassable with `--force`, unlike G1/G2).

Cosine similarity of a candidate's embedding against every *published*
piece in the index (`ce.index`) within `config.gates.dedupe.scope_days`.
Above `config.gates.dedupe.threshold`, `check()` raises with the colliding
piece named. Whether `--force` skips calling this gate at all is a
caller decision (WP-08/09's job) — same shape as G1/G2: once called, the
gate itself always enforces the threshold, no bypass logic lives here.

`max_similarity()` is exposed separately from `check()` because TDD 10.4
needs the raw score for `Brief.dedupe_max_similarity` even on briefs that
aren't blocked — recomputing it by re-deriving the same scan a second time
would just be duplicated work for the same answer.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np

from ce.exit_codes import GateBlocked
from ce.index import all_rows, cosine_similarity
from ce.models import PieceStatus


def max_similarity(
    embedding: np.ndarray,
    *,
    conn: sqlite3.Connection,
    scope_days: int,
    now: datetime | None = None,
) -> tuple[str, float] | None:
    """Highest cosine similarity between `embedding` and any published
    piece's embedding within `scope_days`. `None` if there's nothing
    published (yet) to compare against.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=scope_days)

    best: tuple[str, float] | None = None
    for row in all_rows(conn):
        if row.status != PieceStatus.PUBLISHED.value:
            continue
        # A published piece with no recorded `published_at` is a data
        # inconsistency (produce/publish always sets it) -- treated as
        # always in-scope rather than silently excluded from dedupe.
        if row.published_at is not None and row.published_at < cutoff:
            continue
        score = cosine_similarity(embedding, row.embedding)
        if best is None or score > best[1]:
            best = (row.piece_id, score)
    return best


def check(
    embedding: np.ndarray,
    *,
    conn: sqlite3.Connection,
    threshold: float,
    scope_days: int,
    now: datetime | None = None,
) -> None:
    match = max_similarity(embedding, conn=conn, scope_days=scope_days, now=now)
    if match is None:
        return
    piece_id, score = match
    if score >= threshold:
        raise GateBlocked(
            "G3",
            f"too similar to {piece_id!r} (cosine similarity {score:.2f} >= {threshold:.2f})",
        )
