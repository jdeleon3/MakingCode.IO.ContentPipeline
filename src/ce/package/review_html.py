"""Renders `REVIEW.html` (TDD 10.8) -- a single self-contained file (ADR-006):
inlined CSS/JS, images referenced by relative path so the outbox folder is
portable, no network requests, no server, no localStorage.

Pure rendering only: every input is already-resolved data (`builder.py`'s
job is gathering it from `data/`); this module never touches the
filesystem beyond loading its own template + `config/brand.css`.

Reuses `ce.assets._render.render_html` for the Jinja setup rather than
re-deriving it -- same "load a template, inline brand.css, render" operation
`codecard.py`/`thumbnail.py` already do, just producing a page instead of a
screenshot input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ce.assets._render import render_html

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_DEFAULT_BRAND_CSS_PATH = Path("config/brand.css")

# TDD 10.8 point 5: Facebook gets a pre-filled Sharing Debugger link so the
# operator refreshes FB's OG-tag cache before the first share (v2 §5,
# referenced from 6.2's residual-risk note on scraped-cache staleness).
FACEBOOK_DEBUGGER_URL = "https://developers.facebook.com/tools/debug/?q={url}"

# TDD 10.8 point 2's exact residual-risk wording (6.2) -- quoted verbatim,
# not paraphrased, since this is the operator-facing safety notice for a gap
# no tool in this pipeline closes (screenshots are scanned by nothing).
SCREENSHOT_WARNING = (
    "Screenshots are not automatically scanned for secrets. Open each at "
    "full size and check for tokens, customer data, notifications, and "
    "open tabs."
)

_PLATFORM_LABELS = {"linkedin": "LinkedIn", "facebook": "Facebook", "youtube": "YouTube"}

# Per-platform posting-order checklist (TDD 10.8 point 3: "a posting-order
# checklist"). No TDD example exists for the exact steps -- this session's
# own reasonable sequence per platform, not derived from a spec. LinkedIn's
# order matters mechanically (a link in the body suppresses reach, hence
# `links_in_body: false` -- config/platforms/linkedin.yml); Facebook's
# debugger-first step matters because FB caches the first scrape of a URL
# (6.2); YouTube's is just upload order.
_POSTING_STEPS = {
    "linkedin": [
        "Publish the post text below -- no link in the body.",
        "Immediately add the first comment with the link.",
        "Attach the image below when creating the post.",
    ],
    "facebook": [
        "Run the Sharing Debugger first (link below) to refresh the OG cache.",
        "Publish the post -- the link goes inline in the body.",
        "Attach the image below if it isn't auto-pulled from the link preview.",
    ],
    "youtube": [
        "Upload the video.",
        "Paste the title.",
        "Paste the description (chapters are already included in it).",
        "Set the custom thumbnail image below.",
    ],
}


@dataclass
class PlatformSection:
    """Everything one platform's REVIEW.html section needs to render.

    `body` is the LinkedIn/Facebook post text *or* the YouTube description
    -- `Rendition.body` already carries that dual meaning (see models.py's
    comment on `Rendition`), kept here rather than split into two fields.
    """

    name: str  # "linkedin" | "facebook" | "youtube"
    body: str
    max_chars: int
    first_comment: str | None = None  # LinkedIn only
    title: str | None = None  # YouTube only
    title_max_chars: int | None = None  # YouTube only
    chapters: list[str] = field(default_factory=list)  # YouTube only
    image_path: str | None = None  # relative to REVIEW.html, e.g. "assets/hero.png"
    debugger_url: str | None = None  # Facebook only

    @property
    def label(self) -> str:
        return _PLATFORM_LABELS[self.name]

    @property
    def posting_steps(self) -> list[str]:
        return _POSTING_STEPS[self.name]

    @property
    def chapters_text(self) -> str:
        return "\n".join(self.chapters)


def render(
    *,
    piece_id: str,
    title: str,
    canonical_url: str,
    published_url: str | None,
    published_at: str | None,
    generated_at: str | None,
    images: list[str],
    platforms: list[PlatformSection],
    post_platforms: tuple[str, ...] = ("linkedin", "facebook", "youtube"),
    templates_dir: Path = _TEMPLATES_DIR,
    brand_css_path: Path = _DEFAULT_BRAND_CSS_PATH,
) -> str:
    return render_html(
        "review.html.j2",
        templates_dir=templates_dir,
        brand_css_path=brand_css_path,
        piece_id=piece_id,
        title=title,
        canonical_url=canonical_url,
        published_url=published_url,
        published_at=published_at,
        generated_at=generated_at,
        images=images,
        platforms=platforms,
        post_platforms=list(post_platforms),
        screenshot_warning=SCREENSHOT_WARNING,
        # Plain Jinja2 (unlike Flask's) has no `tojson` filter -- serialise
        # here and mark `|safe` in the template rather than pull in an
        # extension for two small values.
        piece_id_json=json.dumps(piece_id),
        post_platforms_json=json.dumps(list(post_platforms)),
    )
