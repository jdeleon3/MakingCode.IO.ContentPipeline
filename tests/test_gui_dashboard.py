"""WP-18 acceptance: `/` lists every project on disk with its status;
`/projects/<slug>` rolls up accurate capture/harvest/brief/piece counts, and
renders a clear "not harvested" state (not an error or a blank section) for a
project that hasn't been harvested yet.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ce import store  # noqa: E402
from ce.gui.app import create_app  # noqa: E402
from ce.models import (  # noqa: E402
    Brief,
    BriefArchetype,
    BriefDemand,
    BriefEvidence,
    Capture,
    CaptureMoment,
    CaptureType,
    GroundingStrength,
    Piece,
    Project,
    ProjectStatus,
)


def _project(slug: str, status: ProjectStatus = ProjectStatus.ACTIVE) -> Project:
    return Project(slug=slug, title=f"Title for {slug}", status=status, started_at=date(2026, 7, 1))


def _capture(slug: str, capture_id: str, ctype: CaptureType) -> Capture:
    return Capture(
        id=capture_id,
        project=slug,
        type=ctype,
        moment=CaptureMoment.IN_SITU,
        captured_at=datetime(2026, 7, 2, 9, 0, tzinfo=UTC),
        source_path=Path(f"captures/{capture_id}"),
    )


def _brief(slug: str, brief_id: str, status) -> Brief:
    return Brief(
        id=brief_id,
        project=slug,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title=f"Brief {brief_id}",
        angle="counter-position",
        demand=BriefDemand(recurrence=1),
        evidence=[BriefEvidence(kind="git", ref="abc1234")],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.1,
        weakest_point="n=1",
        status=status,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


def test_dashboard_lists_every_project_on_disk_with_status(client, tmp_path):
    data_root = Path("data")
    store.write_project(data_root, _project("proj-a", ProjectStatus.ACTIVE))
    store.write_project(data_root, _project("proj-b", ProjectStatus.HARVESTED))

    resp = client.get("/")

    assert resp.status_code == 200
    assert "Title for proj-a" in resp.text
    assert "Title for proj-b" in resp.text
    assert "active" in resp.text
    assert "harvested" in resp.text


def test_project_detail_shows_accurate_counts_at_every_stage(client, tmp_path):
    from ce.models import BriefStatus, PieceStatus

    data_root = Path("data")
    slug = "fixture-project"
    store.write_project(data_root, _project(slug))
    store.write_capture(data_root, _capture(slug, "cap-1", CaptureType.AUDIO))
    store.write_capture(data_root, _capture(slug, "cap-2", CaptureType.SCREENSHOT))

    hdir = store.harvest_dir(data_root, slug)
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / "git.json").write_text("{}", encoding="utf-8")
    (hdir / "research.json").write_text("{}", encoding="utf-8")
    (hdir / "inventory.md").write_text("# inventory", encoding="utf-8")

    store.write_briefs(
        data_root,
        slug,
        [
            _brief(slug, "br-01", BriefStatus.CANDIDATE),
            _brief(slug, "br-02", BriefStatus.DROPPED),
        ],
    )

    store.write_piece(
        data_root,
        slug,
        Piece(
            id="pc-0001",
            brief_id="br-01",
            project=slug,
            slug="my-piece",
            status=PieceStatus.DRAFTED,
            created_at=datetime(2026, 7, 3, 9, 0, tzinfo=UTC),
            article_path=Path("article.md"),
        ),
    )

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    assert "Captures (2)" in resp.text
    assert "Briefs (2)" in resp.text
    assert "Pieces (1)" in resp.text
    assert "candidate" in resp.text
    assert "dropped" in resp.text
    assert "drafted" in resp.text
    assert "Not harvested yet" not in resp.text


def test_project_with_no_harvest_yet_renders_clear_not_harvested_state(client, tmp_path):
    data_root = Path("data")
    slug = "unharvested-project"
    store.write_project(data_root, _project(slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    assert "Not harvested yet" in resp.text
    assert "Captures (0)" in resp.text
    assert "Briefs (0)" in resp.text
    assert "Pieces (0)" in resp.text


def test_project_detail_404s_for_a_project_not_on_disk(client):
    resp = client.get("/projects/does-not-exist")

    assert resp.status_code == 404
