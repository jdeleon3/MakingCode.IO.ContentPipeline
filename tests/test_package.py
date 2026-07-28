"""WP-13 acceptance (TDD 10.8, 12): the packager + REVIEW.html.

Done-when: `outbox/<piece-id>/` matches the layout named by TDD 9/§7 (this
session's own resolution of the WP-13 Done-when line's stale "v3 §4"
reference -- see `package/builder.py`'s module docstring); `REVIEW.html`
opens from `file://` with no network and no console errors; copy buttons
work; counters turn red past the limit; the screenshot review checklist is
present and lists every image; the Sharing Debugger link is pre-filled;
the Generate-command button emits valid `ce posted` invocations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import pytest

from ce.config import load_platform_config
from ce.exit_codes import CEError
from ce.models import Brief, BriefDemand, GroundingStrength, Piece, PostPlatform, Project, Rendition
from ce.package import builder, review_html

_PLATFORM_CONFIG_DIR = Path(__file__).parent.parent / "config" / "platforms"
NOW = datetime(2026, 7, 28, tzinfo=UTC)


def _platform_configs():
    return {
        name: load_platform_config(_PLATFORM_CONFIG_DIR / f"{name}.yml")
        for name in ("linkedin", "facebook", "youtube")
    }


def _project(slug: str = "test-proj") -> Project:
    return Project(slug=slug, title="Test Project", started_at=NOW.date())


def _brief(project: str = "test-proj") -> Brief:
    return Brief(
        id="br-01",
        project=project,
        archetype="why_this_project",
        title="DuckDB's memory limit is not what the docs imply",
        angle="counter-position",
        demand=BriefDemand(recurrence=3, signals=[]),
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.31,
        weakest_point="n=1",
    )


def _piece(project: str = "test-proj", slug: str = "duckdb-memory") -> Piece:
    return Piece(
        id="pc-0001",
        brief_id="br-01",
        project=project,
        slug=slug,
        created_at=NOW,
        article_path=Path("article.md"),
    )


_UTM = "?utm_source={platform}&utm_medium=social&utm_campaign={slug}"


def _utm_url(platform: str, slug: str = "duckdb-memory") -> str:
    return f"https://example.com/blog/{slug}?utm_source={platform}&utm_medium=social&utm_campaign={slug}"


def _linkedin_rendition() -> Rendition:
    return Rendition(
        platform=PostPlatform.LINKEDIN,
        body="A" * 50 + ".",  # ends on a sentence boundary within hook_chars=200, no URL
        first_comment=f"Full article: {_utm_url('linkedin')}",
        prompt_version=1,
        generated_at=NOW,
    )


def _facebook_rendition() -> Rendition:
    return Rendition(
        platform=PostPlatform.FACEBOOK,
        body=f"Read the whole thing: {_utm_url('facebook')}",
        prompt_version=1,
        generated_at=NOW,
    )


def _youtube_rendition() -> Rendition:
    return Rendition(
        platform=PostPlatform.YOUTUBE,
        body=f"Watch the build. Full writeup: {_utm_url('youtube')} " + "x" * 100,
        title="DuckDB's memory limit, live",
        chapters=["00:00 Intro", "01:30 Setup", "05:00 The crash"],
        prompt_version=1,
        generated_at=NOW,
    )


def _write_fixture(
    data_root: Path,
    *,
    renditions: list[Rendition],
    with_hero: bool = True,
    with_thumbnail: bool = True,
    with_staged_input_only: bool = False,
) -> tuple[Project, Brief, Piece]:
    from ce import store

    project = _project()
    brief = _brief()
    piece = _piece()
    store.write_project(data_root, project)
    store.write_briefs(data_root, project.slug, [brief])
    store.write_piece(data_root, project.slug, piece)
    for rendition in renditions:
        store.write_rendition(data_root, project.slug, piece.id, rendition)

    assets_dir = store.piece_dir(data_root, project.slug, piece.id) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    if with_hero:
        (assets_dir / "hero.jpg").write_bytes(b"fake-hero-bytes")
    if with_thumbnail:
        (assets_dir / "thumbnail.png").write_bytes(b"fake-thumbnail-bytes")
    if with_staged_input_only:
        (assets_dir / "hero-source.jpg").write_bytes(b"fake-hero-source-bytes")
        (assets_dir / "thumbnail-bg.png").write_bytes(b"fake-thumbnail-bg-bytes")

    return project, brief, piece


# ---------------------------------------------------------------------------
# builder.py -- image copying
# ---------------------------------------------------------------------------


def test_copy_images_excludes_staged_inputs(tmp_path):
    data_root = tmp_path / "data"
    _write_fixture(
        data_root, renditions=[_linkedin_rendition()], with_hero=True, with_staged_input_only=True
    )

    dest = tmp_path / "outbox" / "pc-0001"
    copied = builder._copy_images(data_root, "test-proj", "pc-0001", dest)

    assert sorted(copied) == ["assets/hero.jpg", "assets/thumbnail.png"]
    assert (dest / "assets" / "hero.jpg").exists()
    assert not (dest / "assets" / "hero-source.jpg").exists()
    assert not (dest / "assets" / "thumbnail-bg.png").exists()


def test_copy_images_with_no_assets_dir_returns_empty(tmp_path):
    data_root = tmp_path / "data"
    _write_fixture(
        data_root, renditions=[_linkedin_rendition()], with_hero=False, with_thumbnail=False
    )
    (data_root / "projects" / "test-proj" / "pieces" / "pc-0001" / "assets").rmdir()

    dest = tmp_path / "outbox" / "pc-0001"
    copied = builder._copy_images(data_root, "test-proj", "pc-0001", dest)

    assert copied == []


# ---------------------------------------------------------------------------
# builder.py -- package() orchestration
# ---------------------------------------------------------------------------


def test_package_raises_without_any_rendition(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project, brief, piece = _write_fixture(data_root, renditions=[])

    with pytest.raises(CEError, match="ce render"):
        builder.package(
            piece,
            brief,
            project,
            data_root=data_root,
            outbox_root=tmp_path / "outbox",
            config=make_engine_config(),
            platform_configs=_platform_configs(),
        )


def test_package_only_includes_platforms_that_were_rendered(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project, brief, piece = _write_fixture(data_root, renditions=[_linkedin_rendition()])

    result = builder.package(
        piece,
        brief,
        project,
        data_root=data_root,
        outbox_root=tmp_path / "outbox",
        config=make_engine_config(),
        platform_configs=_platform_configs(),
    )

    assert result.platforms == ["linkedin"]
    html = result.review_html_path.read_text(encoding="utf-8")
    assert 'data-platform="linkedin"' in html
    assert 'data-platform="facebook"' not in html
    assert 'data-platform="youtube"' not in html


def test_package_picks_youtube_thumbnail_and_linkedin_hero_image(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project, brief, piece = _write_fixture(
        data_root, renditions=[_linkedin_rendition(), _youtube_rendition()]
    )

    result = builder.package(
        piece,
        brief,
        project,
        data_root=data_root,
        outbox_root=tmp_path / "outbox",
        config=make_engine_config(),
        platform_configs=_platform_configs(),
    )

    html = result.review_html_path.read_text(encoding="utf-8")
    # LinkedIn's platform section should reference the hero image, YouTube's
    # the thumbnail -- assert ordering within each platform's <section> block
    # rather than just "both strings appear somewhere".
    linkedin_section = html.split('data-platform="linkedin"')[1].split("</section>")[0]
    youtube_section = html.split('data-platform="youtube"')[1].split("</section>")[0]
    assert "assets/hero.jpg" in linkedin_section
    assert "assets/thumbnail.png" in youtube_section


def test_package_facebook_debugger_url_is_urlencoded(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project, brief, piece = _write_fixture(data_root, renditions=[_facebook_rendition()])

    result = builder.package(
        piece,
        brief,
        project,
        data_root=data_root,
        outbox_root=tmp_path / "outbox",
        config=make_engine_config(),
        platform_configs=_platform_configs(),
    )

    html = result.review_html_path.read_text(encoding="utf-8")
    assert "developers.facebook.com/tools/debug/?q=" in html
    # The pre-filled query value round-trips back to the real UTM'd URL.
    debugger_href = html.split('href="https://developers.facebook.com/tools/debug/?q=')[1].split(
        '"'
    )[0]
    assert unquote(debugger_href) == _utm_url("facebook")


def test_package_writes_outbox_layout(tmp_path, make_engine_config):
    """TDD 9: `ce package <piece-id> -> outbox/<piece-id>/ + REVIEW.html`."""
    data_root = tmp_path / "data"
    project, brief, piece = _write_fixture(data_root, renditions=[_linkedin_rendition()])
    outbox_root = tmp_path / "outbox"

    result = builder.package(
        piece,
        brief,
        project,
        data_root=data_root,
        outbox_root=outbox_root,
        config=make_engine_config(),
        platform_configs=_platform_configs(),
    )

    assert result.outbox_dir == outbox_root / "pc-0001"
    assert result.review_html_path == outbox_root / "pc-0001" / "REVIEW.html"
    assert result.review_html_path.exists()


# ---------------------------------------------------------------------------
# review_html.py -- pure rendering
# ---------------------------------------------------------------------------


def test_review_html_checklist_lists_every_image(tmp_path):
    html = review_html.render(
        piece_id="pc-0001",
        title="A piece",
        canonical_url="https://example.com/blog/a-piece",
        published_url=None,
        published_at=None,
        generated_at="2026-07-26T09:04:11+00:00",
        images=["assets/hero.jpg", "assets/thumbnail.png", "assets/codecard-fix.png"],
        platforms=[],
    )

    # The manual-review checklist renders each image as an <li> -- distinct
    # from a per-platform image, which is a <div> (see the template) -- so
    # counting <li class="image-item"> tags isolates the checklist itself.
    assert html.count('<li class="image-item">') == 3
    for path in ("assets/hero.jpg", "assets/thumbnail.png", "assets/codecard-fix.png"):
        assert f'src="{path}"' in html
        assert path in html  # also present as the checkbox label text


def test_review_html_includes_the_residual_risk_warning():
    html = review_html.render(
        piece_id="pc-0001",
        title="A piece",
        canonical_url="https://example.com/blog/a-piece",
        published_url=None,
        published_at=None,
        generated_at=None,
        images=[],
        platforms=[],
    )

    assert "not automatically scanned for secrets" in html
    assert "tokens, customer data, notifications, and open tabs" in html


def test_review_html_no_images_staged_has_no_broken_img_tags():
    html = review_html.render(
        piece_id="pc-0001",
        title="A piece",
        canonical_url="https://example.com/blog/a-piece",
        published_url=None,
        published_at=None,
        generated_at=None,
        images=[],
        platforms=[],
    )

    assert "<img" not in html
    assert "No images staged" in html


def test_review_html_shows_published_url_when_set():
    html = review_html.render(
        piece_id="pc-0001",
        title="A piece",
        canonical_url="https://example.com/blog/a-piece",
        published_url="https://example.com/blog/a-piece",
        published_at="2026-07-26T11:00:00+00:00",
        generated_at=None,
        images=[],
        platforms=[],
    )

    assert "not yet published" not in html
    assert "2026-07-26T11:00:00+00:00" in html


def test_review_html_youtube_section_has_title_and_chapters():
    section = review_html.PlatformSection(
        name="youtube",
        body="Description text with the URL in the hook.",
        max_chars=5000,
        title="A short title",
        title_max_chars=60,
        chapters=["00:00 Intro", "01:30 Setup"],
    )

    html = review_html.render(
        piece_id="pc-0001",
        title="A piece",
        canonical_url="https://example.com/blog/a-piece",
        published_url=None,
        published_at=None,
        generated_at=None,
        images=[],
        platforms=[section],
    )

    assert "A short title" in html
    assert "00:00 Intro" in html
    assert "01:30 Setup" in html
    assert 'data-limit="60"' in html  # title counter's limit


# ---------------------------------------------------------------------------
# Real-browser acceptance (TDD 12 WP-13 Done-when): opens from `file://` with
# no network and no console errors; copy buttons work; counters turn red
# past the limit; checklist lists every image; Sharing Debugger link is
# pre-filled; Generate-command emits valid `ce posted` invocations.
#
# Playwright + chromium are present on this dev machine (`ce doctor`) --
# unlike WP-11's codecard/thumbnail renderers, which had no real binary to
# exercise automatically at the time they were built, this WP's own
# Done-when line is explicitly about browser behavior (console errors, live
# JS, clipboard interaction) that no string-matching assertion against the
# rendered HTML can actually prove. Skips gracefully (not a hard failure) if
# a future environment lacks chromium, same shape as WP-11's binary checks.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        try:
            instance = pw.chromium.launch()
        except Exception as exc:  # pragma: no cover -- exercised only when chromium is missing
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()


def test_review_html_full_acceptance_in_a_real_browser(tmp_path, make_engine_config, browser):
    data_root = tmp_path / "data"
    over_limit_body = "A" * 3100 + "."  # deliberately past linkedin.yml's max_chars=3000
    linkedin = Rendition(
        platform=PostPlatform.LINKEDIN,
        body=over_limit_body,
        first_comment=f"Full article: {_utm_url('linkedin')}",
        prompt_version=1,
        generated_at=NOW,
    )
    project, brief, piece = _write_fixture(
        data_root, renditions=[linkedin, _facebook_rendition(), _youtube_rendition()]
    )

    result = builder.package(
        piece,
        brief,
        project,
        data_root=data_root,
        outbox_root=tmp_path / "outbox",
        config=make_engine_config(),
        platform_configs=_platform_configs(),
    )

    console_errors: list[str] = []
    page_errors: list[str] = []
    page = browser.new_page()
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on("requestfailed", lambda req: console_errors.append(f"request failed: {req.url}"))

    page.goto(result.review_html_path.resolve().as_uri())

    assert console_errors == [], console_errors
    assert page_errors == [], page_errors

    # -- the manual review checklist lists every image --
    assert page.locator("li.image-item").count() == len(result.image_paths)
    assert len(result.image_paths) > 0

    # -- counters turn red past the limit: already-over-limit content is red
    #    on load, and content that starts under the limit turns red once
    #    edited past it (a genuinely live counter, not a static compute) --
    linkedin_counter = page.locator('.counter[data-for="linkedin-body"]')
    assert "over" in (linkedin_counter.get_attribute("class") or "")
    assert linkedin_counter.text_content().startswith(str(len(over_limit_body)))

    youtube_counter = page.locator('.counter[data-for="youtube-title"]')
    assert "over" not in (youtube_counter.get_attribute("class") or "")
    page.fill("#youtube-title", "x" * 100)  # youtube's title limit is 60
    assert "over" in (youtube_counter.get_attribute("class") or "")

    # -- Sharing Debugger link is pre-filled with the real UTM'd URL --
    debugger_href = page.locator("a.debugger-link").get_attribute("href")
    assert debugger_href.startswith("https://developers.facebook.com/tools/debug/?q=")
    assert unquote(debugger_href.split("?q=")[1]) == _utm_url("facebook")

    # -- copy buttons work: clicking never throws (console/page error checked
    #    below) and always resolves to visible feedback, whichever of the
    #    Clipboard API / execCommand fallback paths the browser allows on a
    #    `file://` origin --
    copy_btn = page.locator('button[data-copy="linkedin-body"]')
    copy_btn.click()
    page.wait_for_timeout(200)
    assert copy_btn.text_content() in ("Copied!", "Copy failed")
    assert console_errors == [], console_errors
    assert page_errors == [], page_errors

    # -- Generate-command button emits valid `ce posted` invocations, only
    #    for platforms whose URL field was actually filled in --
    page.fill("#url-linkedin", "https://linkedin.com/posts/123")
    page.fill("#url-youtube", "https://youtu.be/abc123")
    page.click("#generate-btn")
    generated = page.locator("#generated-commands").text_content()
    assert "ce posted pc-0001 --platform linkedin --url https://linkedin.com/posts/123" in generated
    assert "ce posted pc-0001 --platform youtube --url https://youtu.be/abc123" in generated
    assert "facebook" not in generated

    page.close()
    assert console_errors == [], console_errors
    assert page_errors == [], page_errors
