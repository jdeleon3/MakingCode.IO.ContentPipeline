"""WP-22 acceptance: `/pieces/<id>/renditions` shows each platform's
`renditions/*.yml` in editable fields with a live character counter against
that platform's real `config/platforms/<p>.yml` limits; saving an edit
writes to the same file `ce render`/`ce package` read; the package preview
embeds the literal `outbox/<id>/REVIEW.html` `ce package` produced, not a
GUI-side reimplementation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ce import store  # noqa: E402
from ce.gui.app import create_app  # noqa: E402
from ce.models import Piece, PostPlatform, Project, Rendition  # noqa: E402

_LINKEDIN_YML = """\
name: linkedin
max_chars: 3000
hook_chars: 200
links_in_body: false
supports_markdown: false
allow_unicode_styling: false
line_break_style: double
assets:
  image: {w: 1200, h: 1200, formats: [png]}
extras:
  - first_comment
"""

_YOUTUBE_YML = """\
name: youtube
max_chars: 5000
hook_chars: 150
links_in_body: true
supports_markdown: false
allow_unicode_styling: true
line_break_style: single
assets:
  image: {w: 1280, h: 720, formats: [png]}
"""


def _project(slug: str) -> Project:
    return Project(slug=slug, title=f"Title for {slug}", started_at=date(2026, 7, 1))


def _piece(piece_id: str) -> Piece:
    return Piece(
        id=piece_id,
        brief_id="br-01",
        project="proj",
        slug="a-slug",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        article_path=Path("article.md"),
        generated_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


def _write_platform_configs(tmp_path: Path) -> None:
    platforms_dir = tmp_path / "config" / "platforms"
    platforms_dir.mkdir(parents=True)
    (platforms_dir / "linkedin.yml").write_text(_LINKEDIN_YML, encoding="utf-8")
    (platforms_dir / "youtube.yml").write_text(_YOUTUBE_YML, encoding="utf-8")


def test_404s_for_a_piece_not_on_disk(client):
    resp = client.get("/pieces/pc-9999/renditions")
    assert resp.status_code == 404


def test_no_renditions_yet_shows_a_clear_hint_per_platform(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))

    resp = client.get("/pieces/pc-0001/renditions")

    assert resp.status_code == 200
    assert "ce render pc-0001 --platform linkedin" in resp.text
    assert "ce render pc-0001 --platform facebook" in resp.text
    assert "ce render pc-0001 --platform youtube" in resp.text


def test_shows_rendition_body_and_counter_against_real_platform_max_chars(client, tmp_path):
    _write_platform_configs(tmp_path)
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))
    rendition = Rendition(
        platform=PostPlatform.LINKEDIN,
        body="Hello LinkedIn body",
        first_comment="See the post: https://example.com/blog/a-slug?utm_source=linkedin",
        prompt_version=1,
        generated_at=datetime.now(UTC),
    )
    store.write_rendition(data_root, "proj", "pc-0001", rendition)

    resp = client.get("/pieces/pc-0001/renditions")

    assert resp.status_code == 200
    assert "Hello LinkedIn body" in resp.text
    assert "See the post:" in resp.text
    # the counter reads the real max_chars from config/platforms/linkedin.yml
    # (3000 in this test's fixture), not a second hardcoded copy.
    assert 'data-max="3000"' in resp.text


def test_youtube_rendition_shows_title_and_chapters(client, tmp_path):
    _write_platform_configs(tmp_path)
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))
    rendition = Rendition(
        platform=PostPlatform.YOUTUBE,
        body="Description hook with https://example.com/blog/a-slug",
        title="A great video",
        chapters=["00:00 Intro", "01:30 Deep dive"],
        prompt_version=1,
        generated_at=datetime.now(UTC),
    )
    store.write_rendition(data_root, "proj", "pc-0001", rendition)

    resp = client.get("/pieces/pc-0001/renditions")

    assert resp.status_code == 200
    assert "A great video" in resp.text
    assert "00:00 Intro" in resp.text
    assert 'data-max="60"' in resp.text  # YouTube's fixed title limit


def test_saving_a_rendition_writes_the_real_file_and_preserves_metadata(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))
    generated_at = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    rendition = Rendition(
        platform=PostPlatform.FACEBOOK,
        body="original body",
        prompt_version=3,
        generated_at=generated_at,
    )
    store.write_rendition(data_root, "proj", "pc-0001", rendition)

    resp = client.post(
        "/pieces/pc-0001/renditions/facebook",
        json={"body": "edited body", "first_comment": None},
    )

    assert resp.status_code == 200
    saved = store.read_rendition(data_root, "proj", "pc-0001", "facebook")
    assert saved.body == "edited body"
    # metadata this GUI edit didn't touch stays exactly as `ce render` wrote it
    assert saved.prompt_version == 3
    assert saved.generated_at == generated_at


def test_saving_a_rendition_that_does_not_exist_yet_is_a_clear_404(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))

    resp = client.post("/pieces/pc-0001/renditions/linkedin", json={"body": "x"})

    assert resp.status_code == 404


def test_asset_previews_list_staged_images(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))
    assets_dir = store.piece_dir(data_root, "proj", "pc-0001") / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "hero.png").write_bytes(b"\x89PNG\r\n")

    resp = client.get("/pieces/pc-0001/renditions")

    assert resp.status_code == 200
    assert "hero.png" in resp.text
    assert "/pieces/pc-0001/assets/hero.png" in resp.text

    img_resp = client.get("/pieces/pc-0001/assets/hero.png")
    assert img_resp.status_code == 200


def test_no_package_yet_shows_a_clear_hint_not_an_iframe(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))

    resp = client.get("/pieces/pc-0001/renditions")

    assert resp.status_code == 200
    assert "Not packaged yet" in resp.text
    assert "<iframe" not in resp.text


def test_package_preview_embeds_the_literal_review_html(client, tmp_path):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))
    outbox = tmp_path / "outbox" / "pc-0001"
    outbox.mkdir(parents=True)
    (outbox / "REVIEW.html").write_text(
        "<html><body><h1>Real REVIEW.html</h1><img src='assets/hero.png'></body></html>",
        encoding="utf-8",
    )
    (outbox / "assets").mkdir()
    (outbox / "assets" / "hero.png").write_bytes(b"\x89PNG\r\n")

    resp = client.get("/pieces/pc-0001/renditions")
    assert resp.status_code == 200
    assert "<iframe" in resp.text
    assert "/pieces/pc-0001/renditions/review/" in resp.text

    review_resp = client.get("/pieces/pc-0001/renditions/review/")
    assert review_resp.status_code == 200
    assert "Real REVIEW.html" in review_resp.text

    asset_resp = client.get("/pieces/pc-0001/renditions/review/assets/hero.png")
    assert asset_resp.status_code == 200


def test_publish_and_posted_actions_reuse_the_runs_console(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_piece(data_root, "proj", _piece("pc-0001"))

    resp = client.get("/pieces/pc-0001/renditions")

    assert resp.status_code == 200
    assert 'data-command="package"' in resp.text
    assert "publish-btn" in resp.text
    assert "identity.site_repo" in resp.text
    assert 'class="posted-btn" data-platform="linkedin"' in resp.text
