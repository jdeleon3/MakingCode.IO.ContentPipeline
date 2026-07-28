"""`ce package <piece-id>` (TDD 10.8, 12 WP-13) -- assembles `outbox/<id>/`.

TDD 9's own CLI contract line is the only place the output layout is named
precisely: `ce package <piece-id> -> outbox/<piece-id>/ + REVIEW.html`. The
WP-13 Done-when line's "matches the v3 §4 layout" points at
`docs/DIY-Content-Engine-v3-Spec.md` (the product spec this TDD supersedes,
TDD's own header line 6) -- but that document's actual §4 is "Reversal #1 --
build YouTube now, not later" (a narrative section, not a directory tree);
the only outbox-shaped thing anywhere in that document is one line in its
pipeline diagram, `OUTPUT: outbox/<slug>/REVIEW.html`. Same situation as
WP-12's `Rendition` schema and WP-11's asset input paths: no literal layout
exists to copy, so this session built the smallest thing that satisfies
ADR-006 (`REVIEW.html` + relatively-pathed images, portable, no network) and
TDD 9/§7 (keyed by piece-id, not slug) --

    outbox/<piece-id>/
      REVIEW.html
      assets/<every staged output image, copied as-is>

Article text and rendition YAML are deliberately **not** copied into the
outbox -- ADR-006's whole point is that `REVIEW.html` is the single
self-contained deliverable; the renditions' text already lives inside it as
copy boxes, and the site article isn't posted from here at all (`ce publish
site`, WP-14, ships it separately).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from ce import store
from ce.config import EngineConfig, PlatformConfig
from ce.exit_codes import CEError
from ce.models import Brief, Piece, Project, Rendition
from ce.package import review_html
from ce.produce.renditions import YOUTUBE_TITLE_MAX_CHARS, canonical_url, utm_url

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# `assets/__init__.py` (WP-11) stages hand-placed *inputs* -- hero-source.*,
# thumbnail-bg.* -- in the same flat `assets/` directory as its rendered
# *outputs* (there's no separate inputs/outputs split in that WP). Only the
# outputs belong in the outbox; a raw hero-source screenshot the operator
# hasn't reviewed yet has no business in a review packet.
_STAGED_INPUT_PREFIXES = ("hero-source", "thumbnail-bg")

# Which staged output image a platform's REVIEW.html section shows, in
# priority order. No per-platform asset tagging exists anywhere in the data
# model (see WP-11's deviations log in STATUS.md) -- this is this session's
# own, documented heuristic, not a TDD rule: YouTube's `thumbnail.png` is a
# literal dims match for `config/platforms/youtube.yml` (1280x720); LinkedIn
# and Facebook prefer the hero image (the "real artifact" screenshot, the
# strongest asset per TDD's own v3 §5 table) and fall back to the thumbnail
# only if no hero was staged, rather than showing no image at all.
_PLATFORM_IMAGE_PRIORITY: dict[str, tuple[str, ...]] = {
    "youtube": ("thumbnail.png",),
    "linkedin": ("hero.png", "hero.jpg", "hero.jpeg", "hero.webp", "thumbnail.png"),
    "facebook": ("hero.png", "hero.jpg", "hero.jpeg", "hero.webp", "thumbnail.png"),
}


@dataclass
class PackageResult:
    outbox_dir: Path
    review_html_path: Path
    image_paths: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)


def outbox_dir(outbox_root: Path, piece_id: str) -> Path:
    return outbox_root / piece_id


def _is_staged_output_image(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXTENSIONS and not path.name.startswith(
        _STAGED_INPUT_PREFIXES
    )


def _copy_images(data_root: Path, project_slug: str, piece_id: str, dest_dir: Path) -> list[str]:
    """Copies every staged output image into `dest_dir/assets/`, returning
    each one's path relative to `dest_dir` (i.e. what `REVIEW.html`'s
    `<img src>` / checklist entries reference)."""
    assets_dir = store.piece_dir(data_root, project_slug, piece_id) / "assets"
    if not assets_dir.exists():
        return []

    dest_assets_dir = dest_dir / "assets"
    dest_assets_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for path in sorted(p for p in assets_dir.iterdir() if p.is_file()):
        if not _is_staged_output_image(path):
            continue
        shutil.copy2(path, dest_assets_dir / path.name)
        copied.append(f"assets/{path.name}")
    return copied


def _read_renditions(data_root: Path, project_slug: str, piece_id: str) -> dict[str, Rendition]:
    directory = store.renditions_dir(data_root, project_slug, piece_id)
    if not directory.exists():
        return {}
    return {
        path.stem: store.read_rendition(data_root, project_slug, piece_id, path.stem)
        for path in sorted(directory.glob("*.yml"))
    }


def _platform_section(
    name: str, rendition: Rendition, cfg: PlatformConfig, *, url: str, image_paths: list[str]
) -> review_html.PlatformSection:
    image_path = next(
        (
            f"assets/{candidate}"
            for candidate in _PLATFORM_IMAGE_PRIORITY[name]
            if f"assets/{candidate}" in image_paths
        ),
        None,
    )
    debugger_url = (
        review_html.FACEBOOK_DEBUGGER_URL.format(url=quote(url, safe=""))
        if name == "facebook"
        else None
    )
    return review_html.PlatformSection(
        name=name,
        body=rendition.body,
        max_chars=cfg.max_chars,
        first_comment=rendition.first_comment,
        title=rendition.title,
        title_max_chars=YOUTUBE_TITLE_MAX_CHARS if name == "youtube" else None,
        chapters=rendition.chapters,
        image_path=image_path,
        debugger_url=debugger_url,
    )


def package(
    piece: Piece,
    brief: Brief,
    project: Project,
    *,
    data_root: Path,
    outbox_root: Path,
    config: EngineConfig,
    platform_configs: dict[str, PlatformConfig],
) -> PackageResult:
    """Assembles `outbox/<piece.id>/` -- `REVIEW.html` + copied asset images.

    Requires at least one rendition (`ce render` output) to already exist;
    packaging a piece with zero rendered platforms would produce a
    `REVIEW.html` with nothing to review, which defeats the point.
    """
    renditions = _read_renditions(data_root, project.slug, piece.id)
    if not renditions:
        raise CEError(f"no renditions found for {piece.id} -- run `ce render {piece.id}` first")

    dest = outbox_dir(outbox_root, piece.id)
    dest.mkdir(parents=True, exist_ok=True)
    image_paths = _copy_images(data_root, project.slug, piece.id, dest)

    base_url = canonical_url(config.identity.site_url, piece.slug)

    sections = []
    for name in ("linkedin", "facebook", "youtube"):
        rendition = renditions.get(name)
        if rendition is None:
            continue
        cfg = platform_configs.get(name)
        if cfg is None:
            raise CEError(f"no platform config loaded for {name!r}")
        url = utm_url(base_url, config.utm.template, platform=name, slug=piece.slug)
        sections.append(_platform_section(name, rendition, cfg, url=url, image_paths=image_paths))

    html = review_html.render(
        piece_id=piece.id,
        title=brief.title,
        canonical_url=base_url,
        published_url=piece.published.url if piece.published else None,
        published_at=piece.published.at.isoformat() if piece.published else None,
        generated_at=piece.generated_at.isoformat() if piece.generated_at else None,
        images=image_paths,
        platforms=sections,
    )

    review_html_path = dest / "REVIEW.html"
    review_html_path.write_text(html, encoding="utf-8")

    return PackageResult(
        outbox_dir=dest,
        review_html_path=review_html_path,
        image_paths=image_paths,
        platforms=[s.name for s in sections],
    )
