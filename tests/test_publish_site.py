"""WP-14 acceptance (TDD 10.9, 12): `publish/site.py`.

Done-when: `--dry-run` prints the frontmatter and file plan without writing
(CLI-level coverage in `test_cli.py`); edit check blocks an unedited article
with exit 4; OG tag assertion fails loudly if tags are missing; canonical
URL polling times out cleanly at 120s.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ce import store
from ce.exit_codes import PreconditionUnmet, PublishError
from ce.models import Brief, BriefDemand, GroundingStrength, Piece, PieceStatus, Project
from ce.publish import site

NOW = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)


def _project(slug: str = "test-proj") -> Project:
    return Project(slug=slug, title="Test Project", started_at=NOW.date(), tags=["duckdb", "etl"])


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


def _piece(project: str = "test-proj", slug: str = "duckdb-memory", generated_at=NOW) -> Piece:
    return Piece(
        id="pc-0001",
        brief_id="br-01",
        project=project,
        slug=slug,
        created_at=NOW,
        article_path=Path("article.md"),
        generated_at=generated_at,
    )


_ARTICLE = (
    "# DuckDB's memory limit is not what the docs imply\n"
    "\n"
    "The join spilled to disk exactly once, on the 40GB run.\n"
    "\n"
    "## What happened\n"
    "\n"
    "More detail here.\n"
)

_OG_HTML_COMPLETE = """<html><head>
<meta property="og:title" content="A title" />
<meta property="og:description" content="A description" />
<meta property="og:image" content="https://example.com/img.png" />
</head></html>"""


# ---------------------------------------------------------------------------
# _extract_title_and_body / _description_from_body (TDD 10.9 step 3)
# ---------------------------------------------------------------------------


def test_extract_title_and_body_strips_the_leading_heading():
    title, body = site._extract_title_and_body(_ARTICLE)

    assert title == "DuckDB's memory limit is not what the docs imply"
    assert not body.startswith("#")
    assert "The join spilled to disk" in body
    assert "## What happened" in body  # sub-headings stay in the body


def test_extract_title_and_body_with_no_heading_returns_empty_title():
    title, body = site._extract_title_and_body("Just a paragraph, no heading.")

    assert title == ""
    assert body == "Just a paragraph, no heading."


def test_description_skips_headings_and_blank_lines():
    body = "\n## Subheading\n\nThe real first sentence goes here.\n\nMore text."

    assert site._description_from_body(body) == "The real first sentence goes here."


def test_description_truncates_past_max_chars():
    long_line = "x" * 200
    description = site._description_from_body(long_line, max_chars=155)

    assert len(description) == 155
    assert description.endswith("…")


# ---------------------------------------------------------------------------
# plan() -- pure frontmatter/file-plan build
# ---------------------------------------------------------------------------


def test_plan_builds_frontmatter_with_no_canonical_key(tmp_path):
    data_root = tmp_path / "data"
    built = site.plan(
        _piece(),
        _brief(),
        _project(),
        _ARTICLE,
        data_root=data_root,
        site_url="https://example.com",
    )

    assert built.frontmatter["title"] == "DuckDB's memory limit is not what the docs imply"
    assert built.frontmatter["pubDate"] == date.today()
    assert built.frontmatter["tags"] == ["duckdb", "etl"]
    assert (
        "canonical" not in built.frontmatter
    )  # BaseHead.astro computes this; see module docstring
    assert built.canonical_url == "https://example.com/blog/duckdb-memory"
    assert built.content_path == Path("src/content/blog/duckdb-memory.md")
    assert "heroImage" not in built.frontmatter
    assert built.hero_source is None


def test_plan_includes_hero_image_when_staged(tmp_path):
    data_root = tmp_path / "data"
    piece = _piece()
    assets_dir = store.piece_dir(data_root, "test-proj", piece.id) / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "hero.jpg").write_bytes(b"fake-hero-bytes")

    built = site.plan(
        piece, _brief(), _project(), _ARTICLE, data_root=data_root, site_url="https://example.com"
    )

    assert built.frontmatter["heroImage"] == "../../assets/blog/duckdb-memory.jpg"
    assert built.hero_dest == Path("src/assets/blog/duckdb-memory.jpg")
    assert built.hero_source == assets_dir / "hero.jpg"


def test_plan_content_text_has_no_duplicate_heading():
    built = site.plan(
        _piece(),
        _brief(),
        _project(),
        _ARTICLE,
        data_root=Path("unused"),
        site_url="https://example.com",
    )

    # The title lives in frontmatter; BlogPostLayout.astro renders it as the
    # page's own <h1> -- a leading `# ` in the body would duplicate it.
    body_after_frontmatter = built.content_text.split("---\n", 2)[2]
    assert not body_after_frontmatter.lstrip().startswith("# ")


# ---------------------------------------------------------------------------
# assert_edited (ADR-008)
# ---------------------------------------------------------------------------


def test_assert_edited_blocks_an_unedited_article(tmp_path):
    article_path = tmp_path / "article.md"
    article_path.write_text("draft", encoding="utf-8")
    piece = _piece(generated_at=datetime.now(UTC) + timedelta(days=1))  # "future" generation

    with pytest.raises(PreconditionUnmet, match="has not been edited"):
        site.assert_edited(piece, article_path)


def test_assert_edited_passes_when_mtime_is_newer(tmp_path):
    piece = _piece(generated_at=datetime.now(UTC) - timedelta(days=1))
    article_path = tmp_path / "article.md"
    article_path.write_text("edited draft", encoding="utf-8")  # mtime = now, after generated_at

    site.assert_edited(piece, article_path)  # must not raise


def test_assert_edited_bypassed_by_no_edit_check(tmp_path):
    article_path = tmp_path / "article.md"
    article_path.write_text("draft", encoding="utf-8")
    piece = _piece(generated_at=datetime.now(UTC) + timedelta(days=1))

    site.assert_edited(piece, article_path, no_edit_check=True)  # must not raise


# ---------------------------------------------------------------------------
# assert_verified (TDD 10.9 step 2 / G4)
# ---------------------------------------------------------------------------


def test_assert_verified_blocks_when_verification_json_missing(tmp_path):
    piece = _piece()
    with pytest.raises(PreconditionUnmet, match="does not exist"):
        site.assert_verified(piece, tmp_path / "verification.json")


def test_assert_verified_blocks_when_claims_failed(tmp_path):
    from ce.models import VerificationSummary

    path = tmp_path / "verification.json"
    path.write_text("{}", encoding="utf-8")
    piece = _piece()
    piece.verification = VerificationSummary(claims_checked=3, claims_failed=1, ran_at=NOW)

    with pytest.raises(PreconditionUnmet, match="has not passed"):
        site.assert_verified(piece, path)


def test_assert_verified_passes_when_all_claims_passed(tmp_path):
    from ce.models import VerificationSummary

    path = tmp_path / "verification.json"
    path.write_text("{}", encoding="utf-8")
    piece = _piece()
    piece.verification = VerificationSummary(claims_checked=3, claims_failed=0, ran_at=NOW)

    site.assert_verified(piece, path)  # must not raise


# ---------------------------------------------------------------------------
# assert_og_tags_present (TDD 10.9 step 7)
# ---------------------------------------------------------------------------


def test_assert_og_tags_present_passes_when_all_three_present():
    site.assert_og_tags_present(_OG_HTML_COMPLETE, "https://example.com/blog/x")  # no raise


@pytest.mark.parametrize(
    "html,missing_name",
    [
        ("<html><head></head></html>", "og:title"),
        ('<meta property="og:title" content="T"/>', "og:description"),
        (
            '<meta property="og:title" content="T"/><meta property="og:image" content=""/>',
            "og:image",
        ),
    ],
)
def test_assert_og_tags_present_fails_loudly_when_a_tag_is_missing_or_empty(html, missing_name):
    with pytest.raises(PublishError, match=missing_name):
        site.assert_og_tags_present(html, "https://example.com/blog/x")


# ---------------------------------------------------------------------------
# poll_canonical_url (TDD 10.9 step 6 -- "times out cleanly at 120s")
# ---------------------------------------------------------------------------


def test_poll_default_timeout_matches_tdd_120s():
    assert site.POLL_TIMEOUT_SEC == 120


class _QueueHttpClient:
    def __init__(self, responses):
        self._queue = list(responses)
        self.calls = 0

    def get(self, url):
        self.calls += 1
        if len(self._queue) > 1:
            return self._queue.pop(0)
        return self._queue[0]


def test_poll_returns_as_soon_as_it_sees_200():
    client = _QueueHttpClient([site.HttpResponse(200, "<html>ok</html>")])
    sleeps: list[float] = []

    response = site.poll_canonical_url(
        "https://example.com/blog/x",
        client,
        timeout_sec=10,
        interval_sec=1,
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )

    assert response.status_code == 200
    assert sleeps == []
    assert client.calls == 1


def test_poll_retries_through_404_then_succeeds():
    client = _QueueHttpClient([site.HttpResponse(404, ""), site.HttpResponse(200, "ok")])
    sleeps: list[float] = []
    clock_values = iter([0.0, 0.0, 1.0, 1.0])

    response = site.poll_canonical_url(
        "https://example.com/blog/x",
        client,
        timeout_sec=10,
        interval_sec=1,
        sleep=sleeps.append,
        clock=lambda: next(clock_values),
    )

    assert response.status_code == 200
    assert sleeps == [1]


def test_poll_times_out_cleanly_and_never_hangs():
    """A fake clock that jumps straight past the deadline proves the loop
    terminates -- no real 120s wait, no real network call."""
    client = _QueueHttpClient([site.HttpResponse(404, "")])
    clock_values = iter([0.0, 0.0, 200.0])  # start, first check, deadline blown
    sleeps: list[float] = []

    with pytest.raises(PublishError, match="did not return 200 within 10s"):
        site.poll_canonical_url(
            "https://example.com/blog/x",
            client,
            timeout_sec=10,
            interval_sec=1,
            sleep=sleeps.append,
            clock=lambda: next(clock_values),
        )


def test_poll_treats_connection_failure_as_not_ready_not_a_crash():
    client = _QueueHttpClient([None, site.HttpResponse(200, "ok")])
    clock_values = iter([0.0, 0.0, 0.0])

    response = site.poll_canonical_url(
        "https://example.com/blog/x",
        client,
        timeout_sec=10,
        interval_sec=1,
        sleep=lambda _: None,
        clock=lambda: next(clock_values),
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# publish() -- full pipeline against a real local git repo (same "genuine
# git, no fake" approach WP-05's significance fixture uses) + a fake HTTP
# client (no real network, no real 120s wait).
# ---------------------------------------------------------------------------


def _init_site_repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(  # noqa: S603, S607
        ["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True
    )
    repo = tmp_path / "site"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)  # noqa: S603, S607
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)  # noqa: S603, S607
    (repo / "README.md").write_text("site\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)  # noqa: S603, S607
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603, S607
        ["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True
    )
    return repo


def _write_fixture(data_root: Path, *, with_hero: bool = True) -> tuple[Project, Brief, Piece]:
    project = _project()
    brief = _brief()
    piece = _piece(generated_at=datetime.now(UTC) - timedelta(days=1))
    store.write_project(data_root, project)
    store.write_briefs(data_root, project.slug, [brief])
    store.write_piece(data_root, project.slug, piece)

    article_path = store.piece_dir(data_root, project.slug, piece.id) / "article.md"
    article_path.write_text(_ARTICLE, encoding="utf-8")  # written after generated_at -> "edited"

    from ce.models import VerificationSummary

    piece.verification = VerificationSummary(claims_checked=2, claims_failed=0, ran_at=NOW)
    store.write_piece(data_root, project.slug, piece)
    store.verification_json_path(data_root, project.slug, piece.id).write_text(
        "{}", encoding="utf-8"
    )

    if with_hero:
        assets_dir = store.piece_dir(data_root, project.slug, piece.id) / "assets"
        assets_dir.mkdir(parents=True)
        (assets_dir / "hero.jpg").write_bytes(b"fake-hero-bytes")

    return project, brief, piece


def test_publish_end_to_end_commits_pushes_and_records_the_published_url(tmp_path):
    data_root = tmp_path / "data"
    project, brief, piece = _write_fixture(data_root)
    site_repo = _init_site_repo(tmp_path)

    http_client = _QueueHttpClient(
        [site.HttpResponse(404, ""), site.HttpResponse(200, _OG_HTML_COMPLETE)]
    )

    result = site.publish(
        piece,
        brief,
        project,
        data_root=data_root,
        site_repo=site_repo,
        site_url="https://example.com",
        http_client=http_client,
        poll_timeout_sec=5,
        poll_interval_sec=0,
        sleep=lambda _: None,
    )

    assert result.published.url == "https://example.com/blog/duckdb-memory"
    assert result.status == PieceStatus.PUBLISHED

    content_file = site_repo / "src" / "content" / "blog" / "duckdb-memory.md"
    assert content_file.exists()
    assert "heroImage: ../../assets/blog/duckdb-memory.jpg" in content_file.read_text(
        encoding="utf-8"
    )
    assert (site_repo / "src" / "assets" / "blog" / "duckdb-memory.jpg").exists()

    # committed and pushed -- working tree is clean against its upstream
    status = subprocess.run(  # noqa: S603, S607
        ["git", "status", "--porcelain"], cwd=site_repo, capture_output=True, text=True, check=True
    )
    assert status.stdout.strip() == ""

    reloaded = store.read_piece(data_root, project.slug, piece.id)
    assert reloaded.published.url == "https://example.com/blog/duckdb-memory"
    assert reloaded.status == PieceStatus.PUBLISHED


def test_publish_raises_loudly_when_og_tags_never_appear(tmp_path):
    data_root = tmp_path / "data"
    project, brief, piece = _write_fixture(data_root, with_hero=False)
    site_repo = _init_site_repo(tmp_path)

    http_client = _QueueHttpClient([site.HttpResponse(200, "<html><head></head></html>")])

    with pytest.raises(PublishError, match="og:"):
        site.publish(
            piece,
            brief,
            project,
            data_root=data_root,
            site_repo=site_repo,
            site_url="https://example.com",
            http_client=http_client,
            poll_timeout_sec=5,
            poll_interval_sec=0,
            sleep=lambda _: None,
        )

    reloaded = store.read_piece(data_root, project.slug, piece.id)
    assert reloaded.published is None  # step 8 never ran


def test_publish_blocks_before_touching_git_when_article_is_unedited(tmp_path):
    data_root = tmp_path / "data"
    project = _project()
    brief = _brief()
    piece = _piece(generated_at=datetime.now(UTC) + timedelta(days=1))  # "future" -> unedited
    store.write_project(data_root, project)
    store.write_briefs(data_root, project.slug, [brief])
    store.write_piece(data_root, project.slug, piece)
    (store.piece_dir(data_root, project.slug, piece.id) / "article.md").write_text(
        _ARTICLE, encoding="utf-8"
    )
    site_repo = tmp_path / "site-not-a-repo"  # never touched -- proves the check runs first

    with pytest.raises(PreconditionUnmet):
        site.publish(
            piece,
            brief,
            project,
            data_root=data_root,
            site_repo=site_repo,
            site_url="https://example.com",
            http_client=_QueueHttpClient([]),
        )

    assert not site_repo.exists()
