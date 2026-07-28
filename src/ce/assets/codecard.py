"""Code snippet -> PNG card via Jinja HTML + Playwright (TDD 10.7).

`ScreenshotRenderer` is shared with `thumbnail.py` (both are "render this
HTML page, screenshot it at these dims" — the same operation with
different inputs) — defined here since this is the first of the two
Playwright consumers listed in TDD §7's file layout.

Not optional here, same reasoning as `diagram.py`'s `mermaid-cli` note:
this dev environment has no Playwright/chromium installed (`ce doctor`),
so tests inject a fake `ScreenshotRenderer`; the real
`PlaywrightScreenshotRenderer` is exercised only manually.

Per-platform code-card dimensions (`_PLATFORM_DIMS`) are a WP-11 stand-in:
TDD 10.7 asks for "per-platform dims" but `config/platforms/*.yml` isn't
built until WP-12 (its own Build line: "three platform configs"), which
doesn't exist yet — revisit once it does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ce.assets._render import render_html
from ce.exit_codes import AssetError

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_DEFAULT_BRAND_CSS_PATH = Path("config/brand.css")
DEVICE_SCALE_FACTOR = 2  # TDD 10.7: "All Playwright renders use deviceScaleFactor=2"

_LANG_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".sql": "sql",
    ".sh": "bash",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".toml": "toml",
    ".css": "css",
    ".html": "html",
}

_PLATFORM_DIMS = {
    "site": (1200, 800),
    "linkedin": (1200, 1200),
    "facebook": (1200, 630),
    "youtube": (1280, 720),
}
DEFAULT_PLATFORM = "site"


def lang_for(path: Path) -> str:
    return _LANG_BY_EXTENSION.get(path.suffix.lower(), "text")


class ScreenshotRenderer(Protocol):
    def screenshot_html(
        self, html: str, output_path: Path, *, width: int, height: int, device_scale_factor: int
    ) -> None: ...


class PlaywrightScreenshotRenderer:
    def screenshot_html(
        self,
        html: str,
        output_path: Path,
        *,
        width: int,
        height: int,
        device_scale_factor: int = DEVICE_SCALE_FACTOR,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise AssetError(
                "playwright is not installed",
                hint="pip install playwright && playwright install chromium, then `ce doctor`",
            ) from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=device_scale_factor,
                    )
                    page.set_content(html)
                    page.screenshot(path=str(output_path))
                finally:
                    browser.close()
        except Exception as exc:
            raise AssetError(f"playwright screenshot failed: {exc}") from exc


def render(
    snippet: str,
    lang: str,
    output_path: Path,
    *,
    renderer: ScreenshotRenderer,
    platform: str = DEFAULT_PLATFORM,
    templates_dir: Path = _TEMPLATES_DIR,
    brand_css_path: Path = _DEFAULT_BRAND_CSS_PATH,
) -> None:
    width, height = _PLATFORM_DIMS.get(platform, _PLATFORM_DIMS[DEFAULT_PLATFORM])
    html = render_html(
        "codecard.html.j2",
        templates_dir=templates_dir,
        brand_css_path=brand_css_path,
        snippet=snippet,
        lang=lang,
    )
    renderer.screenshot_html(
        html, output_path, width=width, height=height, device_scale_factor=DEVICE_SCALE_FACTOR
    )
