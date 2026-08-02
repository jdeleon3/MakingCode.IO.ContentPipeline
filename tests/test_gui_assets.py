"""Operator-requested (post-WP-22): `/pieces/<id>/assets/stage|stage-text|
unstage` let the operator stage `ce assets`' hand-placed inputs (hero image,
thumbnail background, evidence snippets, Mermaid diagrams) through the
browser instead of the filesystem. Singleton kinds (hero, thumbnail_bg)
replace whatever was staged before; multi-file kinds (evidence, diagram) add
alongside what's already there. Evidence snippets can also be pasted
directly (filename + text) rather than uploaded as an existing file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ce import store  # noqa: E402
from ce.gui.app import create_app  # noqa: E402
from ce.models import Piece, Project  # noqa: E402


def _project(slug: str) -> Project:
    return Project(slug=slug, title=f"Title for {slug}", started_at=datetime(2026, 7, 1).date())


def _piece(piece_id: str) -> Piece:
    return Piece(
        id=piece_id,
        brief_id="br-01",
        project="proj",
        slug="a-slug",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        article_path=Path("article.md"),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


@pytest.fixture
def piece(client):
    """Not just the fixture setup -- also proves the piece exists via the
    real store helpers `client`'s cwd now points at."""
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))
    return "pc-0001"


def _piece_dir() -> Path:
    return store.piece_dir(Path("data"), "proj", "pc-0001")


# ---------------------------------------------------------------------------
# stage (file upload)
# ---------------------------------------------------------------------------


def test_stage_hero_writes_the_file_and_shows_up_on_the_piece_page(client, piece):
    resp = client.post(
        f"/pieces/{piece}/assets/stage/hero",
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
    )

    assert resp.status_code == 200
    assert resp.json()["filename"] == "hero-source.png"
    assert (_piece_dir() / "assets" / "hero-source.png").exists()

    page = client.get(f"/pieces/{piece}")
    assert "hero-source.png" in page.text


def test_stage_hero_rejects_an_unsupported_extension(client, piece):
    resp = client.post(
        f"/pieces/{piece}/assets/stage/hero",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert resp.status_code == 400
    assert "unsupported extension" in resp.json()["detail"]
    assert not (_piece_dir() / "assets").exists() or not list(
        (_piece_dir() / "assets").glob("hero-source.*")
    )


def test_staging_a_second_hero_replaces_the_first_not_adds_to_it(client, piece):
    client.post(
        f"/pieces/{piece}/assets/stage/hero",
        files={"file": ("a.png", b"png-bytes", "image/png")},
    )
    client.post(
        f"/pieces/{piece}/assets/stage/hero",
        files={"file": ("b.jpg", b"jpg-bytes", "image/jpeg")},
    )

    staged = sorted(p.name for p in (_piece_dir() / "assets").glob("hero-source.*"))
    assert staged == ["hero-source.jpg"]


def test_diagram_requires_mmd_extension(client, piece):
    resp = client.post(
        f"/pieces/{piece}/assets/stage/diagram",
        files={"file": ("flow.png", b"not-a-diagram", "image/png")},
    )
    assert resp.status_code == 400


def test_diagram_upload_is_multi_file_not_singleton(client, piece):
    client.post(
        f"/pieces/{piece}/assets/stage/diagram",
        files={"file": ("a.mmd", b"graph TD; A-->B;", "text/plain")},
    )
    client.post(
        f"/pieces/{piece}/assets/stage/diagram",
        files={"file": ("b.mmd", b"graph TD; C-->D;", "text/plain")},
    )

    staged = sorted(p.name for p in (_piece_dir() / "assets" / "diagrams").glob("*.mmd"))
    assert staged == ["a.mmd", "b.mmd"]


def test_evidence_accepts_any_extension_and_keeps_every_file(client, piece):
    client.post(
        f"/pieces/{piece}/assets/stage/evidence",
        files={"file": ("fix.py", b"def fix(): pass", "text/plain")},
    )
    client.post(
        f"/pieces/{piece}/assets/stage/evidence",
        files={"file": ("query.sql", b"SELECT 1;", "text/plain")},
    )

    staged = sorted(p.name for p in (_piece_dir() / "evidence").iterdir())
    assert staged == ["fix.py", "query.sql"]


# ---------------------------------------------------------------------------
# stage-text (paste-to-create, evidence)
# ---------------------------------------------------------------------------


def test_stage_text_writes_a_pasted_snippet_identically_to_an_upload(client, piece):
    resp = client.post(
        f"/pieces/{piece}/assets/stage-text/evidence",
        json={"filename": "pasted.py", "content": "def pasted(): pass\n"},
    )

    assert resp.status_code == 200
    written = _piece_dir() / "evidence" / "pasted.py"
    assert written.read_text(encoding="utf-8") == "def pasted(): pass\n"

    page = client.get(f"/pieces/{piece}")
    assert "pasted.py" in page.text


def test_stage_text_and_upload_coexist_in_the_evidence_listing(client, piece):
    client.post(
        f"/pieces/{piece}/assets/stage/evidence",
        files={"file": ("fix.py", b"def fix(): pass", "text/plain")},
    )
    client.post(
        f"/pieces/{piece}/assets/stage-text/evidence",
        json={"filename": "pasted.py", "content": "x = 1\n"},
    )

    staged = sorted(p.name for p in (_piece_dir() / "evidence").iterdir())
    assert staged == ["fix.py", "pasted.py"]


# ---------------------------------------------------------------------------
# stage-text (paste-to-create, diagram)
# ---------------------------------------------------------------------------


def test_stage_text_writes_a_pasted_diagram_identically_to_an_upload(client, piece):
    resp = client.post(
        f"/pieces/{piece}/assets/stage-text/diagram",
        json={"filename": "flow.mmd", "content": "flowchart TD\n  A --> B\n"},
    )

    assert resp.status_code == 200
    written = _piece_dir() / "assets" / "diagrams" / "flow.mmd"
    assert written.read_text(encoding="utf-8") == "flowchart TD\n  A --> B\n"

    page = client.get(f"/pieces/{piece}")
    assert "flow.mmd" in page.text


def test_stage_text_enforces_the_diagram_extension(client, piece):
    resp = client.post(
        f"/pieces/{piece}/assets/stage-text/diagram",
        json={"filename": "flow.txt", "content": "flowchart TD\n  A --> B\n"},
    )

    assert resp.status_code == 400
    assert not (_piece_dir() / "assets" / "diagrams" / "flow.txt").exists()


# ---------------------------------------------------------------------------
# unstage
# ---------------------------------------------------------------------------


def test_unstage_removes_the_named_file_only(client, piece):
    client.post(
        f"/pieces/{piece}/assets/stage/evidence",
        files={"file": ("fix.py", b"def fix(): pass", "text/plain")},
    )
    client.post(
        f"/pieces/{piece}/assets/stage/evidence",
        files={"file": ("query.sql", b"SELECT 1;", "text/plain")},
    )

    resp = client.post(f"/pieces/{piece}/assets/unstage/evidence", json={"filename": "fix.py"})

    assert resp.status_code == 200
    staged = sorted(p.name for p in (_piece_dir() / "evidence").iterdir())
    assert staged == ["query.sql"]


def test_unstage_a_bogus_filename_404s_without_touching_anything_outside_the_kind_dir(
    client, piece
):
    client.post(
        f"/pieces/{piece}/assets/stage/evidence",
        files={"file": ("fix.py", b"def fix(): pass", "text/plain")},
    )

    resp = client.post(
        f"/pieces/{piece}/assets/unstage/evidence", json={"filename": "../../pyproject.toml"}
    )

    assert resp.status_code == 404
    assert (_piece_dir() / "evidence" / "fix.py").exists()


def test_unstage_unknown_kind_is_400(client, piece):
    resp = client.post(f"/pieces/{piece}/assets/unstage/bogus", json={"filename": "x"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# piece_detail's `staged` context
# ---------------------------------------------------------------------------


def test_piece_page_shows_empty_state_when_nothing_is_staged(client, piece):
    resp = client.get(f"/pieces/{piece}")

    assert resp.status_code == 200
    assert "Not staged." in resp.text
    assert "None staged." in resp.text
