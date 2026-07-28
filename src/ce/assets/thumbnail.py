"""Title (+ optional background screenshot) -> 1280x720 PNG thumbnail via
Jinja HTML + Playwright (TDD 10.7).

Reuses `codecard.py`'s `ScreenshotRenderer` Protocol/real implementation
rather than redefining an identical one — both modules do the same
"render this HTML, screenshot it" operation.

TDD 10.7 also lists an "optional face" input; not built here. There's no
capture mechanism anywhere in this codebase for a face photo (WP-04's
`ce capture screen` only knows screenshot/screencast), and WP-11's
Done-when line only requires "thumbnail is 1280x720" — face compositing
would be pure speculative scope. `background_image_path` covers the
"screenshot" half of TDD's input list; revisit "face" if a real capture
type for it gets built.
"""

from __future__ import annotations

import base64
from pathlib import Path

from ce.assets._render import render_html
from ce.assets.codecard import DEVICE_SCALE_FACTOR, ScreenshotRenderer

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_DEFAULT_BRAND_CSS_PATH = Path("config/brand.css")

WIDTH = 1280  # TDD 10.7: "1280x720"
HEIGHT = 720

_MIME_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _data_uri(path: Path) -> str | None:
    """Inlines the background image as base64 rather than a `<img src>`
    file path — `page.set_content()` has no base URL to resolve a relative
    path against, and a data URI sidesteps that entirely."""
    mime = _MIME_BY_EXTENSION.get(path.suffix.lower())
    if mime is None:
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def render(
    title: str,
    output_path: Path,
    *,
    renderer: ScreenshotRenderer,
    background_image_path: Path | None = None,
    templates_dir: Path = _TEMPLATES_DIR,
    brand_css_path: Path = _DEFAULT_BRAND_CSS_PATH,
) -> None:
    background_data_uri = None
    if background_image_path is not None and background_image_path.exists():
        background_data_uri = _data_uri(background_image_path)

    html = render_html(
        "thumbnail.html.j2",
        templates_dir=templates_dir,
        brand_css_path=brand_css_path,
        title=title,
        background_data_uri=background_data_uri,
    )
    renderer.screenshot_html(
        html, output_path, width=WIDTH, height=HEIGHT, device_scale_factor=DEVICE_SCALE_FACTOR
    )
