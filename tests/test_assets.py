"""WP-11 acceptance (TDD 10.7, 12): the asset pipeline.

Done-when: Mermaid source renders to PNG at correct dims; code card
renders at 2x and is legible at 50%; thumbnail is 1280x720; `--only
diagram` runs just that; missing `mermaid-cli` produces a clear error,
not a stack trace.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ce import assets as assets_module
from ce import store
from ce.assets import codecard, diagram, thumbnail
from ce.exit_codes import AssetError
from ce.models import (
    Brief,
    BriefArchetype,
    BriefDemand,
    GroundingStrength,
    Piece,
    Project,
    PublishableLevel,
    RepoRef,
)

NOW = date(2026, 7, 28)


def _project(slug: str = "test-proj") -> Project:
    return Project(
        slug=slug,
        title="Streaming ETL with DuckDB",
        started_at=NOW,
        repos=[RepoRef(name=slug, path=Path("/code") / slug, publishable=PublishableLevel.FULL)],
    )


def _brief(project: str = "test-proj") -> Brief:
    return Brief(
        id="br-01",
        project=project,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="DuckDB's memory limit is not what the docs imply",
        angle="counter-position",
        demand=BriefDemand(recurrence=3, signals=[]),
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.31,
        weakest_point="n=1",
    )


def _piece(project: str = "test-proj") -> Piece:
    from datetime import UTC, datetime

    return Piece(
        id="pc-0001",
        brief_id="br-01",
        project=project,
        slug="a-piece",
        created_at=datetime.now(UTC),
        article_path=Path("article.md"),
    )


class FakeDiagramRenderer:
    def __init__(self):
        self.calls: list[dict] = []

    def render(self, mermaid_source: str, output_path: Path, *, width: int) -> None:
        self.calls.append(
            {"mermaid_source": mermaid_source, "output_path": output_path, "width": width}
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")


class FakeScreenshotRenderer:
    def __init__(self):
        self.calls: list[dict] = []

    def screenshot_html(
        self, html: str, output_path: Path, *, width: int, height: int, device_scale_factor: int
    ) -> None:
        self.calls.append(
            {
                "html": html,
                "output_path": output_path,
                "width": width,
                "height": height,
                "device_scale_factor": device_scale_factor,
            }
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")


class ExplodingScreenshotRenderer:
    """Proves a kind was never invoked -- used for `--only diagram`."""

    def screenshot_html(self, *args, **kwargs) -> None:
        raise AssertionError("screenshot renderer should not have been called")


# ---------------------------------------------------------------------------
# diagram.py
# ---------------------------------------------------------------------------


def test_mermaid_cli_renderer_missing_binary_is_a_clear_error(monkeypatch, tmp_path):
    """WP-11 Done-when: missing mermaid-cli produces a clear error, not a
    stack trace."""
    monkeypatch.setattr(diagram.shutil, "which", lambda name: None)

    with pytest.raises(AssetError, match="mermaid-cli"):
        diagram.MermaidCliRenderer().render("graph TD; A-->B;", tmp_path / "out.png", width=1600)


def test_render_diagrams_calls_renderer_with_correct_width(tmp_path):
    project = _project()
    piece = _piece()
    diagrams_dir = store.piece_dir(tmp_path, project.slug, piece.id) / "assets" / "diagrams"
    diagrams_dir.mkdir(parents=True)
    (diagrams_dir / "flow.mmd").write_text("graph TD; A-->B;", encoding="utf-8")
    renderer = FakeDiagramRenderer()

    result = assets_module.generate(
        piece,
        _brief(),
        data_root=tmp_path,
        only="diagram",
        diagram_renderer=renderer,
        screenshot_renderer=ExplodingScreenshotRenderer(),
    )

    assert len(renderer.calls) == 1
    assert renderer.calls[0]["width"] == diagram.DEFAULT_WIDTH
    assert renderer.calls[0]["output_path"].name == "flow.png"
    assert len(result.produced) == 1
    assert not result.skipped


# ---------------------------------------------------------------------------
# codecard.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected_lang",
    [("snippet.py", "python"), ("snippet.js", "javascript"), ("snippet.xyz", "text")],
)
def test_lang_for_maps_known_extensions(filename, expected_lang):
    assert codecard.lang_for(Path(filename)) == expected_lang


def test_playwright_renderer_missing_package_is_a_clear_error(tmp_path):
    """WP-11 Done-when's "clear error, not a stack trace" applies equally
    to the Playwright seam -- this dev environment genuinely has no
    playwright installed (confirmed via `ce doctor`), so this exercises
    the real import-failure path, not a mock."""
    with pytest.raises(AssetError, match="playwright"):
        codecard.PlaywrightScreenshotRenderer().screenshot_html(
            "<html></html>", tmp_path / "out.png", width=100, height=100, device_scale_factor=2
        )


def test_codecard_render_uses_device_scale_factor_2_and_platform_dims():
    """WP-11 Done-when: "code card renders at 2x" -- 2x pixel density at a
    given CSS size is what "legible at 50%" means (the 50% legibility
    itself is a visual property no automated test can assert)."""
    renderer = FakeScreenshotRenderer()

    codecard.render(
        "print('hi')", "python", Path("/tmp/card.png"), renderer=renderer, platform="linkedin"
    )

    [call] = renderer.calls
    assert call["device_scale_factor"] == 2
    assert (call["width"], call["height"]) == codecard._PLATFORM_DIMS["linkedin"]
    assert "print(&#39;hi&#39;)" in call["html"] or "print('hi')" in call["html"]


def test_codecard_render_defaults_to_site_dims_for_unknown_platform():
    renderer = FakeScreenshotRenderer()

    codecard.render(
        "x = 1", "python", Path("/tmp/card.png"), renderer=renderer, platform="not-a-real-platform"
    )

    [call] = renderer.calls
    assert (call["width"], call["height"]) == codecard._PLATFORM_DIMS["site"]


# ---------------------------------------------------------------------------
# thumbnail.py
# ---------------------------------------------------------------------------


def test_thumbnail_render_is_1280x720_at_2x():
    """WP-11 Done-when: thumbnail is 1280x720."""
    renderer = FakeScreenshotRenderer()

    thumbnail.render("My Title", Path("/tmp/thumb.png"), renderer=renderer)

    [call] = renderer.calls
    assert (call["width"], call["height"]) == (1280, 720)
    assert call["device_scale_factor"] == 2
    assert "My Title" in call["html"]


def test_thumbnail_render_embeds_background_as_data_uri(tmp_path):
    bg_path = tmp_path / "bg.png"
    bg_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    renderer = FakeScreenshotRenderer()

    thumbnail.render(
        "My Title", tmp_path / "thumb.png", renderer=renderer, background_image_path=bg_path
    )

    [call] = renderer.calls
    assert "data:image/png;base64," in call["html"]


def test_thumbnail_render_without_background_omits_bg_image():
    renderer = FakeScreenshotRenderer()

    thumbnail.render("My Title", Path("/tmp/thumb.png"), renderer=renderer)

    [call] = renderer.calls
    assert "data:image" not in call["html"]


# ---------------------------------------------------------------------------
# assets/__init__.py -- generate() orchestration
# ---------------------------------------------------------------------------


def test_generate_with_no_staged_inputs_produces_only_the_thumbnail(tmp_path):
    """Thumbnail is the one kind that always has an input (the brief's
    title needs nothing staged) -- diagram/codecard/hero are all no-ops
    with nothing staged."""
    result = assets_module.generate(
        _piece(),
        _brief(),
        data_root=tmp_path,
        diagram_renderer=FakeDiagramRenderer(),
        screenshot_renderer=FakeScreenshotRenderer(),
    )

    assert len(result.produced) == 1
    assert result.produced[0].name == "thumbnail.png"
    assert len(result.skipped) == 3  # diagram, codecard, hero


def test_generate_only_diagram_never_touches_the_screenshot_renderer(tmp_path):
    """WP-11 Done-when: --only diagram runs just that."""
    piece = _piece()
    diagrams_dir = store.piece_dir(tmp_path, piece.project, piece.id) / "assets" / "diagrams"
    diagrams_dir.mkdir(parents=True)
    (diagrams_dir / "a.mmd").write_text("graph TD; A-->B;", encoding="utf-8")

    result = assets_module.generate(
        piece,
        _brief(),
        data_root=tmp_path,
        only="diagram",
        diagram_renderer=FakeDiagramRenderer(),
        screenshot_renderer=ExplodingScreenshotRenderer(),
    )

    assert len(result.produced) == 1
    assert result.produced[0].name == "a.png"


def test_generate_unknown_only_kind_raises(tmp_path):
    with pytest.raises(AssetError, match="unknown --only"):
        assets_module.generate(
            _piece(),
            _brief(),
            data_root=tmp_path,
            only="bogus",
            diagram_renderer=FakeDiagramRenderer(),
            screenshot_renderer=FakeScreenshotRenderer(),
        )


def test_generate_codecard_renders_one_card_per_evidence_file(tmp_path):
    piece = _piece()
    evidence_dir = store.piece_dir(tmp_path, piece.project, piece.id) / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "fix.py").write_text("def fix(): pass", encoding="utf-8")
    (evidence_dir / "query.sql").write_text("SELECT 1;", encoding="utf-8")

    result = assets_module.generate(
        piece,
        _brief(),
        data_root=tmp_path,
        only="codecard",
        diagram_renderer=ExplodingScreenshotRenderer(),
        screenshot_renderer=FakeScreenshotRenderer(),
    )

    names = sorted(p.name for p in result.produced)
    assert names == ["codecard-fix.png", "codecard-query.png"]


def test_generate_hero_copies_staged_source_file(tmp_path):
    piece = _piece()
    assets_dir = store.piece_dir(tmp_path, piece.project, piece.id) / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "hero-source.jpg").write_bytes(b"fake-jpeg-bytes")

    result = assets_module.generate(
        piece,
        _brief(),
        data_root=tmp_path,
        only="hero",
        diagram_renderer=ExplodingScreenshotRenderer(),
        screenshot_renderer=ExplodingScreenshotRenderer(),
    )

    [produced] = result.produced
    assert produced.name == "hero.jpg"
    assert produced.read_bytes() == b"fake-jpeg-bytes"


def test_generate_hero_missing_source_is_skipped_not_an_error(tmp_path):
    result = assets_module.generate(
        _piece(),
        _brief(),
        data_root=tmp_path,
        only="hero",
        diagram_renderer=ExplodingScreenshotRenderer(),
        screenshot_renderer=ExplodingScreenshotRenderer(),
    )

    assert result.produced == []
    assert "hero" in result.skipped[0]
