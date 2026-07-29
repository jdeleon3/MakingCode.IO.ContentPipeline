"""WP-21 acceptance: `/pieces/<id>` shows `article.md` in an editable
textarea that saves straight back to that file (bumping its mtime past
`piece.generated_at`, satisfying ADR-008's edit check with zero
special-casing); renders every `grades.json` attempt in order with
per-dimension scores and top fixes; clearly states when a piece hasn't been
verified yet rather than showing a blank or misleading section.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ce import store  # noqa: E402
from ce.gui.app import create_app  # noqa: E402
from ce.models import GradeAttempt, GradeScores, Piece, Project, VerificationSummary  # noqa: E402


def _project(slug: str) -> Project:
    return Project(slug=slug, title=f"Title for {slug}", started_at=date(2026, 7, 1))


def _piece(piece_id: str, *, generated_at: datetime | None = None, verified: bool = False) -> Piece:
    return Piece(
        id=piece_id,
        brief_id="br-01",
        project="proj",
        slug="a-slug",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        article_path=Path("article.md"),
        generated_at=generated_at,
        grades=[
            GradeAttempt(
                attempt=1,
                total=8.2,
                scores=GradeScores(
                    hook=8,
                    evidence=9,
                    specificity=8,
                    voice=7,
                    cta=9,
                ),
            )
        ]
        if generated_at
        else [],
        verification=(
            VerificationSummary(claims_checked=3, claims_failed=1, ran_at=datetime.now(UTC))
            if verified
            else None
        ),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


def test_404s_for_a_piece_not_on_disk(client):
    resp = client.get("/pieces/pc-9999")
    assert resp.status_code == 404


def test_shows_article_in_an_editable_textarea(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    piece = _piece("pc-0001", generated_at=datetime(2026, 7, 1, tzinfo=UTC))
    store.write_piece(data_root, "proj", piece)
    article_path = store.piece_dir(data_root, "proj", "pc-0001") / "article.md"
    article_path.write_text("# Hello\n\nBody text.", encoding="utf-8")

    resp = client.get("/pieces/pc-0001")

    assert resp.status_code == 200
    assert "# Hello" in resp.text
    assert "<textarea" in resp.text


def test_no_article_yet_shows_a_clear_hint_not_a_blank_page(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))

    resp = client.get("/pieces/pc-0001")

    assert resp.status_code == 200
    assert "Not drafted yet" in resp.text
    assert "ce produce pc-0001" in resp.text


def test_saving_the_article_writes_the_real_file_and_bumps_its_mtime_past_generated_at(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    generated_at = datetime.now(UTC)
    piece = _piece("pc-0001", generated_at=generated_at)
    store.write_piece(data_root, "proj", piece)
    article_path = store.piece_dir(data_root, "proj", "pc-0001") / "article.md"
    article_path.write_text("original", encoding="utf-8")

    # `generated_at` is "now"; sleep past filesystem mtime resolution so a
    # fresh write is unambiguously later, the same race a manual edit right
    # after `ce produce` finishes would also have to clear.
    time.sleep(0.05)
    resp = client.post("/pieces/pc-0001/article", json={"content": "edited body"})

    assert resp.status_code == 200
    assert article_path.read_text(encoding="utf-8") == "edited body"
    mtime = datetime.fromtimestamp(article_path.stat().st_mtime, tz=UTC)
    assert mtime > generated_at


def test_grade_history_renders_every_attempt_with_scores(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    piece = _piece("pc-0001", generated_at=datetime(2026, 7, 1, tzinfo=UTC))
    store.write_piece(data_root, "proj", piece)
    grades_log = {
        "attempts": [
            {
                "attempt": 1,
                "total": 7.1,
                "scores": {"hook": 6, "evidence": 8, "specificity": 7, "voice": 7, "cta": 7.5},
                "draft_prompt_version": 1,
                "grade_prompt_version": 1,
                "top_fixes": [
                    {
                        "dimension": "hook",
                        "issue": "buries the lede",
                        "suggested_change": "open with the failure",
                        "impact": "high",
                    }
                ],
            },
            {
                "attempt": 2,
                "total": 8.6,
                "scores": {"hook": 9, "evidence": 8, "specificity": 8.5, "voice": 8, "cta": 9},
                "draft_prompt_version": 2,
                "grade_prompt_version": 1,
                "top_fixes": [],
            },
        ]
    }
    store.grades_json_path(data_root, "proj", "pc-0001").write_text(
        json.dumps(grades_log), encoding="utf-8"
    )

    resp = client.get("/pieces/pc-0001")

    assert resp.status_code == 200
    assert "buries the lede" in resp.text
    assert "7.1" in resp.text
    assert "8.6" in resp.text
    attempt1_pos = resp.text.index(">1<")
    attempt2_pos = resp.text.index(">2<")
    assert attempt1_pos < attempt2_pos


def test_unverified_piece_clearly_states_it_has_not_been_verified(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    piece = _piece("pc-0001", generated_at=datetime(2026, 7, 1, tzinfo=UTC), verified=False)
    store.write_piece(data_root, "proj", piece)

    resp = client.get("/pieces/pc-0001")

    assert resp.status_code == 200
    assert "Not yet verified" in resp.text
    assert "ce verify pc-0001" in resp.text


def test_verified_piece_shows_verification_summary_and_claims(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    piece = _piece("pc-0001", generated_at=datetime(2026, 7, 1, tzinfo=UTC), verified=True)
    store.write_piece(data_root, "proj", piece)
    verification = {
        "claims": [
            {
                "text": "DuckDB caps memory at 80% by default",
                "claim_class": "grounded",
                "ref": "abc1234",
                "source_url": None,
                "passed": True,
                "reason": "resolves to 'abc1234'",
            },
            {
                "text": "This is the fastest approach available",
                "claim_class": "unverifiable",
                "ref": None,
                "source_url": None,
                "passed": False,
                "reason": "classified unverifiable by claim_extract",
            },
        ]
    }
    store.verification_json_path(data_root, "proj", "pc-0001").write_text(
        json.dumps(verification), encoding="utf-8"
    )

    resp = client.get("/pieces/pc-0001")

    assert resp.status_code == 200
    assert "claims checked" in resp.text.lower()
    assert "DuckDB caps memory at 80% by default" in resp.text
    assert "unverifiable" in resp.text


def test_action_buttons_reuse_the_runs_console_commands(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    piece = _piece("pc-0001", generated_at=datetime(2026, 7, 1, tzinfo=UTC))
    store.write_piece(data_root, "proj", piece)
    article_path = store.piece_dir(data_root, "proj", "pc-0001") / "article.md"
    article_path.write_text("body", encoding="utf-8")

    resp = client.get("/pieces/pc-0001")

    assert resp.status_code == 200
    assert 'data-command="verify"' in resp.text
    assert 'data-command="assets"' in resp.text
    assert 'data-command="render"' in resp.text
