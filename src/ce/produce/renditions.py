"""`ce render <piece-id> [--platform P]...` -- per-platform copy adaptation
(TDD 10.6, 12 WP-12).

For each requested platform, calls `rendition_<platform>` and then runs
**mechanical validation** against `config/platforms/<platform>.yml` (never
LLM-judged -- TDD 10.6's own heading). A violation gets exactly one
regeneration attempt with the specific failure appended to the prompt as
`prior_violation`; if the retry still fails, `RenditionError` is raised
(exit 1) rather than a third attempt or a silent skip.

LinkedIn and Facebook share the same "one text body, optionally a first
comment" shape (`links_in_body` in `PlatformConfig` decides whether the
body must exclude the URL and carry a separate `first_comment`, vs. include
it inline). YouTube's rendition is structurally different -- a title,
description, and chapter list, not a single body -- so it gets its own
prompt output format and parser rather than being force-fit into the
two-part shape.

**Canonical URL, ahead of publishing.** Nothing here waits on `ce publish
site` (WP-14) to exist first -- WP-12 runs *before* WP-13/14 in the
pipeline (TDD 12.1's dependency graph: WP-09 -> WP-12 -> WP-13, separately
from WP-09 -> WP-10 -> WP-14), so `piece.published.url` is never set yet at
render time. The canonical URL is instead computed deterministically from
`config.identity.site_url` + the piece's slug, matching the exact shape
WP-14 will actually publish to (TDD 5.2's own `piece.yml` example:
`https://example.com/blog/duckdb-memory-limit-reality` is
`site_url + "/blog/" + slug`). UTM parameters are appended per
`config.utm.template` (TDD 8), one per platform.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from ce import store
from ce.config import PlatformConfig
from ce.exit_codes import RenditionError
from ce.llm.gateway import Gateway
from ce.models import Piece, PostPlatform, Rendition

DEFAULT_PLATFORMS: tuple[str, ...] = ("linkedin", "facebook", "youtube")

# TDD §11: "YouTube: len(title) <= 60" -- a fixed number in the Done-when
# line itself, not a config field (unlike max_chars/hook_chars, which are
# genuinely per-platform). Same "hardcode a single literal rather than add
# a config field for one use site" call as writer.py's `_LENGTH_TARGET`.
# Public (not `_`-prefixed) because `package/builder.py` (WP-13) needs the
# same number to label the title copy box's character counter in
# REVIEW.html -- one source of truth rather than a second hardcoded 60.
YOUTUBE_TITLE_MAX_CHARS = 60

_MAX_REGENERATION_ATTEMPTS = 1  # TDD 10.6: "one regeneration attempt ... then exit 1"

_URL_RE = re.compile(r"https?://\S+")
_BOLD_RE = re.compile(r"\*\*[^\n*]+\*\*")
_ITALIC_RE = re.compile(r"(?<!\w)_[^_\n]+_(?!\w)")
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_LINK_RE = re.compile(r"\[[^\]\n]+\]\([^)\n]+\)")
_SENTENCE_END_RE = re.compile(r"[.!?]")
_CHAPTER_LINE_RE = re.compile(r"^(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<label>\S.*)$")
_YOUTUBE_RESPONSE_RE = re.compile(
    r"TITLE:\s*(?P<title>.+?)\s*\n"
    r"DESCRIPTION:\s*\n(?P<description>.*?)\n"
    r"CHAPTERS:\s*\n(?P<chapters>.*)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Canonical / UTM URLs
# ---------------------------------------------------------------------------


def canonical_url(site_url: str, slug: str) -> str:
    return f"{site_url.rstrip('/')}/blog/{slug}"


def utm_url(base_url: str, template: str, *, platform: str, slug: str) -> str:
    return base_url + template.format(platform=platform, slug=slug)


# ---------------------------------------------------------------------------
# Mechanical validation (TDD 10.6 -- not LLM-judged)
# ---------------------------------------------------------------------------


def _markdown_markers(text: str) -> list[str]:
    markers = []
    if _BOLD_RE.search(text):
        markers.append("**bold**")
    if _ITALIC_RE.search(text):
        markers.append("_italic_")
    if _HEADING_RE.search(text):
        markers.append("# heading")
    if _LINK_RE.search(text):
        markers.append("[text](url)")
    return markers


def _validate_common(body: str, cfg: PlatformConfig) -> list[str]:
    violations = []
    if len(body) > cfg.max_chars:
        violations.append(f"body is {len(body)} chars, exceeds max_chars={cfg.max_chars}")
    if not cfg.supports_markdown:
        markers = _markdown_markers(body)
        if markers:
            violations.append(f"markdown syntax survived: {', '.join(markers)}")
    if not cfg.allow_unicode_styling and not body.isascii():
        violations.append("body contains non-ASCII unicode styling characters")
    return violations


def _validate_linkedin_or_facebook(
    body: str, first_comment: str | None, cfg: PlatformConfig, url: str
) -> list[str]:
    violations = _validate_common(body, cfg)

    if not cfg.links_in_body:
        if _URL_RE.search(body):
            violations.append("body contains a URL but links_in_body is false")
        if not first_comment or not first_comment.strip():
            violations.append("first_comment is required when links_in_body is false")
        elif url not in first_comment:
            violations.append(f"first_comment does not contain the UTM'd canonical URL {url!r}")
    elif url not in body:
        violations.append(f"body must contain the UTM'd canonical URL {url!r}")

    if cfg.name == "linkedin":
        hook = body[: cfg.hook_chars]
        if _URL_RE.search(hook):
            violations.append(f"first {cfg.hook_chars} chars (the hook) contain a URL")
        if not _SENTENCE_END_RE.search(hook):
            violations.append(
                f"first {cfg.hook_chars} chars (the hook) don't end at a sentence boundary"
            )

    return violations


def _parse_chapter_seconds(timestamp: str) -> int:
    parts = [int(p) for p in timestamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds


def _validate_chapters(chapters: list[str]) -> list[str]:
    if not chapters:
        return ["at least one chapter is required"]

    violations = []
    # (original line, parsed seconds) only for lines that parsed -- keeping
    # these paired (rather than two separately-filtered lists) avoids
    # misaligning the ascending-order check when a malformed line in the
    # middle would otherwise shift every later line out of sync.
    parsed: list[tuple[str, int]] = []
    for line in chapters:
        match = _CHAPTER_LINE_RE.match(line.strip())
        if match is None:
            violations.append(f"chapter line {line!r} is not in 'MM:SS Label' format")
            continue
        parsed.append((line, _parse_chapter_seconds(match.group("ts"))))

    if parsed and parsed[0][1] != 0:
        violations.append(f"first chapter must start at 00:00, got {parsed[0][0]!r}")
    for (_prev_line, prev_sec), (cur_line, cur_sec) in zip(parsed, parsed[1:], strict=False):
        if cur_sec <= prev_sec:
            violations.append(f"chapter {cur_line!r} does not ascend from the previous timestamp")

    return violations


def _validate_youtube(
    title: str, description: str, chapters: list[str], cfg: PlatformConfig, url: str
) -> list[str]:
    violations = _validate_common(description, cfg)

    if len(title) > YOUTUBE_TITLE_MAX_CHARS:
        violations.append(f"title is {len(title)} chars, exceeds {YOUTUBE_TITLE_MAX_CHARS}")
    if not title.strip():
        violations.append("title is empty")

    hook = description[: cfg.hook_chars]
    if url not in hook:
        violations.append(
            f"first {cfg.hook_chars} chars of the description don't contain the canonical URL"
        )

    violations.extend(_validate_chapters(chapters))
    return violations


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_two_part(content: str) -> tuple[str, str | None]:
    parts = re.split(r"\n-{3}\n", content.strip(), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return content.strip(), None


def _parse_youtube_response(content: str) -> tuple[str, str, list[str]]:
    match = _YOUTUBE_RESPONSE_RE.search(content.strip())
    if match is None:
        return "", content.strip(), []
    title = match.group("title").strip()
    description = match.group("description").strip()
    chapters = [line.strip() for line in match.group("chapters").splitlines() if line.strip()]
    return title, description, chapters


# ---------------------------------------------------------------------------
# Per-platform render + retry
# ---------------------------------------------------------------------------


def _render_linkedin_or_facebook(
    article: str, *, gateway: Gateway, cfg: PlatformConfig, url: str, cache: bool, now: datetime
) -> Rendition:
    prior_violation = ""
    for _attempt in range(_MAX_REGENERATION_ATTEMPTS + 1):
        vars_ = {
            "article": article,
            "canonical_url_utm": url,
            "max_chars": cfg.max_chars,
            "prior_violation": prior_violation,
        }
        if cfg.name == "linkedin":
            vars_["hook_chars"] = (
                cfg.hook_chars
            )  # rendition_linkedin.md is the only one that needs it

        result = gateway.complete(f"rendition_{cfg.name}", vars_, tier="default", cache=cache)

        if cfg.name == "linkedin":
            body, first_comment = _parse_two_part(result.content)
        else:
            body, first_comment = result.content.strip(), None
        violations = _validate_linkedin_or_facebook(body, first_comment, cfg, url)
        if not violations:
            return Rendition(
                platform=PostPlatform(cfg.name),
                body=body,
                first_comment=first_comment,
                prompt_version=result.prompt_version,
                generated_at=now,
            )
        prior_violation = "; ".join(violations)

    raise RenditionError(f"{cfg.name}: {prior_violation}")


def _render_youtube(
    article: str, *, gateway: Gateway, cfg: PlatformConfig, url: str, cache: bool, now: datetime
) -> Rendition:
    prior_violation = ""
    for _attempt in range(_MAX_REGENERATION_ATTEMPTS + 1):
        result = gateway.complete(
            "rendition_youtube",
            {
                "article": article,
                "canonical_url": url,
                "title_max_chars": YOUTUBE_TITLE_MAX_CHARS,
                "description_hook_chars": cfg.hook_chars,
                "prior_violation": prior_violation,
            },
            tier="default",
            cache=cache,
        )
        title, description, chapters = _parse_youtube_response(result.content)
        violations = _validate_youtube(title, description, chapters, cfg, url)
        if not violations:
            return Rendition(
                platform=PostPlatform.YOUTUBE,
                body=description,
                title=title,
                chapters=chapters,
                prompt_version=result.prompt_version,
                generated_at=now,
            )
        prior_violation = "; ".join(violations)

    raise RenditionError(f"youtube: {prior_violation}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render(
    piece: Piece,
    article: str,
    *,
    data_root: Path,
    gateway: Gateway,
    platform_configs: dict[str, PlatformConfig],
    site_url: str,
    utm_template: str,
    cache: bool = True,
    now: datetime | None = None,
) -> list[Rendition]:
    """Renders and mechanically validates `article` for every platform in
    `platform_configs`, writing each to `pieces/<id>/renditions/<platform>.yml`
    and returning the written `Rendition`s in the same order they were
    requested.
    """
    now = now or datetime.now(UTC)
    base_url = canonical_url(site_url, piece.slug)

    renditions: list[Rendition] = []
    for name, cfg in platform_configs.items():
        url = utm_url(base_url, utm_template, platform=name, slug=piece.slug)
        if name in ("linkedin", "facebook"):
            rendition = _render_linkedin_or_facebook(
                article, gateway=gateway, cfg=cfg, url=url, cache=cache, now=now
            )
        elif name == "youtube":
            rendition = _render_youtube(
                article, gateway=gateway, cfg=cfg, url=url, cache=cache, now=now
            )
        else:
            raise RenditionError(f"unknown platform {name!r}")

        store.write_rendition(data_root, piece.project, piece.id, rendition)
        renditions.append(rendition)

    return renditions
