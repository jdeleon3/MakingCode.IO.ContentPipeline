"""Shared HTML template rendering for `codecard.py`/`thumbnail.py` — both
build a small standalone HTML page that Playwright then screenshots,
styled from `config/brand.css` so every asset matches the site (TDD 10.7).

`autoescape=True` here (unlike `llm/prompts.py`'s plain-text prompt
rendering) because template variables land inside HTML: an unescaped code
snippet or piece title containing `<`/`&` would otherwise corrupt the
page Playwright renders, not just look wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def render_html(
    template_name: str, *, templates_dir: Path, brand_css_path: Path, **template_vars: Any
) -> str:
    env = Environment(
        loader=FileSystemLoader(templates_dir), autoescape=True, undefined=StrictUndefined
    )
    template = env.get_template(template_name)
    brand_css = brand_css_path.read_text(encoding="utf-8") if brand_css_path.exists() else ""
    return template.render(brand_css=brand_css, **template_vars)
