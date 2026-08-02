"""`ce publish site <piece-id> [--dry-run]` (TDD 10.9, 12 WP-14) -- ships
`article.md` into `identity.site_repo`'s Astro content collection, then
proves Facebook/Twitter can actually see the result before renditions get
packaged (TDD 10.9 step 7's own reasoning: Facebook caches its first
scrape, so a broken OG tag caught *after* packaging is too late).

Follows TDD 10.9's eight steps in order: edit-check (ADR-008) -> verified
gate (G4) -> build frontmatter -> copy the hero asset -> commit+push ->
poll the canonical URL for a 200 -> assert OG tags -> write
`piece.published`.

**Frontmatter has no `canonical` field**, unlike TDD 10.9's literal list
(`title`, `description`, `pubDate`, `tags`, `heroImage`, `canonical`).
Inspected the real site repo (`identity.site_repo`, an Astro project) this
session: its `content.config.ts` blog schema has no `canonical` key, and
`src/components/BaseHead.astro` already computes
`new URL(Astro.url.pathname, Astro.site)` for `<link rel="canonical">` and
every `og:*`/`twitter:*` tag from the page's own route -- a frontmatter
value would be redundant at best, silently dropped at worst (the schema's
`z.object()` strips unknown keys by default). The canonical URL this
module actually needs (to poll, and to write `piece.published.url`) is
computed the same way WP-12's `produce/renditions.py::canonical_url` already
does -- `site_url + "/blog/" + slug` -- reusing that helper rather than a
second copy.

**No `description` field exists anywhere in the data model** (`Piece`,
`Brief`, `Project`) to carry an OG description. Same shape as WP-08's
"one-line summary" gap: uses the article body's first non-blank,
non-heading line, truncated to `_DESCRIPTION_MAX_CHARS`.

**`heroImage` is written only when the piece staged one** (WP-11's
`assets/hero.<ext>`), copied into the site repo's `src/assets/blog/` and
namespaced by the piece's slug (`<slug>.<ext>`) -- the site's own asset
directory is shared across every published piece, so a fixed `hero.<ext>`
name would collide on the second post. `[...id].astro` in the site repo
already derives `ogImage` from `heroImage` at build time via `getImage()`,
so nothing here needs to touch `ogImage` directly.

**Inline body images follow the same copy-and-rewrite treatment as the hero
(post-WP-14 bug fix).** `article.md`'s body may reference a piece's own
staged/rendered assets with `![alt](assets/<file>)` -- the same
`assets/<file>` relative-path convention ADR-006's `REVIEW.html` already
uses (`package/review_html.py`). Before this fix, that literal path was
written straight into the site repo's markdown unchanged: the referenced
file was never copied there, and even if it had been, a bare `assets/...`
path doesn't resolve against `src/content/blog/<slug>.md` the way Astro
needs (confirmed against the real site repo's two published posts --
neither uses a body image, only `heroImage` -- and its
`src/content.config.ts`/`astro.config.mjs`, which resolve relative
Markdown image paths against the content file's own location, same as the
`image()` schema helper already does for `heroImage`). `_rewrite_body_images`
finds each such reference, asserts the source file exists in the piece's
own `assets/` dir (a clear `PublishError` if not -- a missing image should
never silently ship as a broken link), copies it to
`src/assets/blog/<slug>-<file>` (slug-namespaced for the same collision
reason as the hero), and rewrites the body to
`../../assets/blog/<slug>-<file>`. Absolute URLs (`http(s)://`) and
site-absolute paths (leading `/`) are left untouched -- neither is a piece
asset.

**`--no-edit-check` is a parameter on `publish()`, not a CLI flag.** ADR-008
says the bypass exists "for testing only" but never says which command
surfaces it, and TDD 9's own CLI contract line for this exact command --
`ce publish site <piece-id> [--dry-run]` -- lists no such flag. Honoring
the literal contract: the bypass exists for this module's own test suite to
call directly, not as an operator-facing escape hatch.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from ce import store
from ce.exit_codes import CEError, PreconditionUnmet, PublishError
from ce.models import Brief, Piece, PieceStatus, Project, PublishedInfo
from ce.produce.renditions import canonical_url

# Astro content-collection layout inside `identity.site_repo` (inspected
# this session -- `src/content.config.ts`'s `blog` collection).
_CONTENT_DIR = Path("src/content/blog")
_ASSET_DIR = Path("src/assets/blog")
_HERO_GLOB = "hero.*"

_DESCRIPTION_MAX_CHARS = 155  # common OG/meta-description soft limit

# TDD 10.9 step 6: "poll ... max 120s". Public (not `_`-prefixed) so tests
# can assert the real default without hardcoding `120` a second time --
# same reasoning as `produce/renditions.py::YOUTUBE_TITLE_MAX_CHARS`.
POLL_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 5.0

_REQUIRED_OG_TAGS = ("og:title", "og:description", "og:image")

# `![alt](assets/<file>)` -- ADR-006's own "images referenced by relative
# path" convention (already used by `package/review_html.py`), reused here
# so an operator only has to learn one way to reference a piece's own asset
# from within `article.md`.
_BODY_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(assets/([^)\s]+)\)")


# ---------------------------------------------------------------------------
# HTTP client seam (DI, same shape as harvest/research.py's SearchClient/
# FetchClient Protocols) -- real network calls in `HttpxClient`, fakes in tests.
# ---------------------------------------------------------------------------


@dataclass
class HttpResponse:
    status_code: int
    text: str


class HttpClient(Protocol):
    def get(self, url: str) -> HttpResponse | None:
        """Returns `None` on any connection-level failure (DNS, timeout,
        refused) -- during polling that means "not ready yet", not an error.
        A real non-200 response (404 before the Pages build lands, 5xx) is
        *not* a connection failure and must come back as a `HttpResponse`,
        not `None`, so the poll loop can tell the two apart."""
        ...


class HttpxClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def get(self, url: str) -> HttpResponse | None:
        try:
            response = httpx.get(url, timeout=self._timeout, follow_redirects=True)
        except httpx.HTTPError:
            return None
        return HttpResponse(status_code=response.status_code, text=response.text)


# ---------------------------------------------------------------------------
# Preconditions (TDD 10.9 steps 1-2)
# ---------------------------------------------------------------------------


def assert_edited(piece: Piece, article_path: Path, *, no_edit_check: bool = False) -> None:
    """ADR-008: `article.md`'s mtime must be newer than `piece.generated_at`."""
    if no_edit_check:
        return
    if piece.generated_at is None:
        raise PreconditionUnmet(
            f"{piece.id} has no generated_at -- run `ce produce {piece.id}` first"
        )
    mtime = datetime.fromtimestamp(article_path.stat().st_mtime, tz=UTC)
    if mtime <= piece.generated_at:
        raise PreconditionUnmet(
            f"{article_path} has not been edited since it was generated "
            f"(mtime {mtime.isoformat()} <= generated_at {piece.generated_at.isoformat()}) "
            "-- ADR-008: edit the draft, then re-run `ce publish site`"
        )


def assert_verified(piece: Piece, verification_json_path: Path) -> None:
    """TDD 10.9 step 2: `verification.json` must exist and have passed (G4)."""
    if not verification_json_path.exists():
        raise PreconditionUnmet(
            f"{verification_json_path} does not exist -- run `ce verify {piece.id}` first"
        )
    if piece.verification is None or piece.verification.claims_failed > 0:
        raise PreconditionUnmet(
            f"{piece.id} has not passed claim verification -- run `ce verify {piece.id}`"
        )


# ---------------------------------------------------------------------------
# Frontmatter / content transform (TDD 10.9 step 3)
# ---------------------------------------------------------------------------


def _extract_title_and_body(article_text: str) -> tuple[str, str]:
    """`article_draft`'s own prompt contract (prompts/article_draft.md)
    guarantees a single leading `# Title` heading. The site's
    `BlogPostLayout.astro` already renders `{title}` as an `<h1>` from
    frontmatter, so the heading is stripped here rather than duplicated in
    the published body."""
    lines = article_text.lstrip("\n").splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).lstrip("\n")
    return "", article_text


def _description_from_body(body: str, *, max_chars: int = _DESCRIPTION_MAX_CHARS) -> str:
    candidate = next(
        (
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ),
        "",
    )
    if len(candidate) <= max_chars:
        return candidate
    return candidate[: max_chars - 1].rstrip() + "…"


def _find_hero_source(data_root: Path, project_slug: str, piece_id: str) -> Path | None:
    assets_dir = store.piece_dir(data_root, project_slug, piece_id) / "assets"
    if not assets_dir.exists():
        return None
    matches = sorted(p for p in assets_dir.glob(_HERO_GLOB) if p.is_file())
    return matches[0] if matches else None


def _rewrite_body_images(
    body: str, *, assets_dir: Path, piece_slug: str
) -> tuple[str, list[tuple[Path, Path]]]:
    """Rewrites every `![alt](assets/<file>)` in `body` to the
    `../../assets/blog/<slug>-<file>` path Astro needs to resolve it from
    `src/content/blog/<slug>.md`, and returns the (source, dest) copy pairs
    the caller still has to perform (dest relative to `identity.site_repo`).
    Raises `PublishError` naming the missing file rather than shipping a
    silently broken image link."""
    images: list[tuple[Path, Path]] = []

    def _replace(match: re.Match[str]) -> str:
        alt, filename = match.group(1), match.group(2)
        source = assets_dir / filename
        if not source.is_file():
            raise PublishError(
                f"article.md references assets/{filename}, but {source} does not exist "
                "-- stage it with `ce assets` or place it there by hand before publishing"
            )
        dest = _ASSET_DIR / f"{piece_slug}-{filename}"
        images.append((source, dest))
        return f"![{alt}](../../assets/blog/{piece_slug}-{filename})"

    return _BODY_IMAGE_RE.sub(_replace, body), images


@dataclass
class PublishPlan:
    content_path: Path  # relative to identity.site_repo
    content_text: str
    frontmatter: dict[str, Any]
    canonical_url: str
    hero_source: Path | None = None
    hero_dest: Path | None = None  # relative to identity.site_repo
    body_images: list[tuple[Path, Path]] = field(default_factory=list)  # (source, dest-relative)


def plan(
    piece: Piece,
    brief: Brief,
    project: Project,
    article_text: str,
    *,
    data_root: Path,
    site_url: str,
) -> PublishPlan:
    """Builds the frontmatter + file plan (TDD 10.9 step 3) without touching
    disk, git or the network -- the whole of `--dry-run`, and the first half
    of a real `publish()`."""
    title, body = _extract_title_and_body(article_text)
    title = title or brief.title

    frontmatter: dict[str, Any] = {
        "title": title,
        "description": _description_from_body(body),
        "pubDate": date.today(),
    }
    if project.tags:
        frontmatter["tags"] = list(project.tags)

    hero_source = _find_hero_source(data_root, project.slug, piece.id)
    hero_dest = None
    if hero_source is not None:
        hero_dest = _ASSET_DIR / f"{piece.slug}{hero_source.suffix.lower()}"
        frontmatter["heroImage"] = f"../../assets/blog/{hero_dest.name}"

    assets_dir = store.piece_dir(data_root, project.slug, piece.id) / "assets"
    body, body_images = _rewrite_body_images(body, assets_dir=assets_dir, piece_slug=piece.slug)

    content_text = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + body.rstrip()
        + "\n"
    )

    return PublishPlan(
        content_path=_CONTENT_DIR / f"{piece.slug}.md",
        content_text=content_text,
        frontmatter=frontmatter,
        canonical_url=canonical_url(site_url, piece.slug),
        hero_source=hero_source,
        hero_dest=hero_dest,
        body_images=body_images,
    )


# ---------------------------------------------------------------------------
# git commit + push (TDD 10.9 steps 4-5)
# ---------------------------------------------------------------------------


def _run_git(args: list[str], *, cwd: Path) -> None:
    proc = subprocess.run(  # noqa: S603
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise PublishError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()[-2000:]}")


def commit_and_push(site_repo: Path, *, paths: list[Path], message: str) -> None:
    _run_git(["add", *[str(p) for p in paths]], cwd=site_repo)
    _run_git(["commit", "-m", message], cwd=site_repo)
    _run_git(["push"], cwd=site_repo)


# ---------------------------------------------------------------------------
# Poll for the Cloudflare Pages build (TDD 10.9 step 6)
# ---------------------------------------------------------------------------


def poll_canonical_url(
    url: str,
    http_client: HttpClient,
    *,
    timeout_sec: float = POLL_TIMEOUT_SEC,
    interval_sec: float = POLL_INTERVAL_SEC,
    sleep: Any = time.sleep,
    clock: Any = time.monotonic,
) -> HttpResponse:
    """Polls `url` until it returns 200, or raises `PublishError` once
    `timeout_sec` has elapsed -- "times out cleanly", not a hang."""
    deadline = clock() + timeout_sec
    last_status: int | None = None
    while True:
        response = http_client.get(url)
        if response is not None:
            last_status = response.status_code
            if response.status_code == 200:
                return response
        if clock() >= deadline:
            detail = f"last status {last_status}" if last_status is not None else "no response"
            raise PublishError(
                f"{url} did not return 200 within {timeout_sec:.0f}s ({detail}) "
                "-- Cloudflare Pages build may still be running"
            )
        sleep(interval_sec)


# ---------------------------------------------------------------------------
# OG tag assertion (TDD 10.9 step 7)
# ---------------------------------------------------------------------------


class _OgTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attr_dict = dict(attrs)
        prop = attr_dict.get("property")
        if prop and prop.startswith("og:"):
            self.tags[prop] = attr_dict.get("content") or ""


def assert_og_tags_present(html: str, url: str) -> None:
    parser = _OgTagParser()
    parser.feed(html)
    missing = [name for name in _REQUIRED_OG_TAGS if not parser.tags.get(name, "").strip()]
    if missing:
        raise PublishError(
            f"{url}: missing or empty OG tag(s): {', '.join(missing)} -- "
            "fix before packaging renditions (Facebook caches its first scrape)"
        )


# ---------------------------------------------------------------------------
# publish() -- the full pipeline (TDD 10.9, all 8 steps)
# ---------------------------------------------------------------------------


def publish(
    piece: Piece,
    brief: Brief,
    project: Project,
    *,
    data_root: Path,
    site_repo: Path,
    site_url: str,
    http_client: HttpClient,
    no_edit_check: bool = False,
    poll_timeout_sec: float = POLL_TIMEOUT_SEC,
    poll_interval_sec: float = POLL_INTERVAL_SEC,
    sleep: Any = time.sleep,
    clock: Any = time.monotonic,
    now: datetime | None = None,
) -> Piece:
    """Runs TDD 10.9's eight steps and returns the updated, persisted `Piece`."""
    article_path = store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
    if not article_path.exists():
        raise CEError(f"{article_path} does not exist -- run `ce produce {piece.id}` first")

    assert_edited(piece, article_path, no_edit_check=no_edit_check)
    assert_verified(piece, store.verification_json_path(data_root, project.slug, piece.id))

    article_text = article_path.read_text(encoding="utf-8")
    built_plan = plan(piece, brief, project, article_text, data_root=data_root, site_url=site_url)

    content_dest = site_repo / built_plan.content_path
    content_dest.parent.mkdir(parents=True, exist_ok=True)
    content_dest.write_text(built_plan.content_text, encoding="utf-8")

    committed_paths = [built_plan.content_path]
    if built_plan.hero_source is not None and built_plan.hero_dest is not None:
        hero_dest_abs = site_repo / built_plan.hero_dest
        hero_dest_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_plan.hero_source, hero_dest_abs)
        committed_paths.append(built_plan.hero_dest)

    for image_source, image_dest in built_plan.body_images:
        image_dest_abs = site_repo / image_dest
        image_dest_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_source, image_dest_abs)
        committed_paths.append(image_dest)

    commit_and_push(
        site_repo, paths=committed_paths, message=f"Publish: {built_plan.frontmatter['title']}"
    )

    response = poll_canonical_url(
        built_plan.canonical_url,
        http_client,
        timeout_sec=poll_timeout_sec,
        interval_sec=poll_interval_sec,
        sleep=sleep,
        clock=clock,
    )
    assert_og_tags_present(response.text, built_plan.canonical_url)

    piece.published = PublishedInfo(url=built_plan.canonical_url, at=now or datetime.now(UTC))
    piece.status = PieceStatus.PUBLISHED
    store.write_piece(data_root, project.slug, piece)
    return piece
