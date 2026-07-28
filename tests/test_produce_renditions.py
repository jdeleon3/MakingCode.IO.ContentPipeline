"""WP-12 acceptance (TDD 10.6, 12): per-platform rendition generation +
mechanical validation.

Done-when: every mechanical validation in §10.6 has a passing test with a
deliberately-violating fixture -- over-length, URL in LinkedIn body,
markdown surviving into LinkedIn, unicode styling, YouTube title >60,
chapters not starting at 00:00. One regeneration attempt on violation, then
exit 1 (`RenditionError`, whose `exit_code` is `Exit.ERROR` -- see
`exit_codes.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ce import store
from ce.config import load_platform_config
from ce.exit_codes import RenditionError
from ce.llm.gateway import Gateway, ProviderResponse
from ce.models import Piece
from ce.produce import renditions as renditions_module

NOW = datetime(2026, 7, 28, tzinfo=UTC)

_SITE_URL = "https://example.com"
_UTM_TEMPLATE = "?utm_source={platform}&utm_medium=social&utm_campaign={slug}"


def _utm(platform: str, slug: str = "test-piece") -> str:
    return f"{_SITE_URL}/blog/{slug}?utm_source={platform}&utm_medium=social&utm_campaign={slug}"


def _piece(slug: str = "test-piece") -> Piece:
    return Piece(
        id="pc-0001",
        brief_id="br-01",
        project="test-proj",
        slug=slug,
        created_at=NOW,
        article_path=Path("article.md"),
    )


def _load_cfg(name: str):
    return load_platform_config(Path("config/platforms") / f"{name}.yml")


class FakeLLMClient:
    """Returns each response in `contents`, in call order -- same shape as
    `test_produce_writer.py`'s fake."""

    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.calls: list[dict] = []

    def complete(self, *, model, system, user, max_tokens):
        self.calls.append({"model": model, "system": system, "user": user})
        return ProviderResponse(content=self._contents.pop(0), in_tokens=100, out_tokens=200)


def _gateway(
    tmp_path: Path, make_engine_config, contents: list[str]
) -> tuple[Gateway, FakeLLMClient]:
    client = FakeLLMClient(contents)
    gateway = Gateway(
        make_engine_config(),
        data_root=tmp_path / "data",
        prompts_dir=Path("prompts"),
        client=client,
    )
    return gateway, client


def _linkedin_content(body: str, first_comment: str | None = None) -> str:
    first_comment = first_comment or f"Full article: {_utm('linkedin')}"
    return f"{body}\n---\n{first_comment}"


def _facebook_content(body: str | None = None) -> str:
    return body if body is not None else f"Check it out: {_utm('facebook')}"


def _youtube_content(
    *,
    title: str = "A short, clean title",
    description: str | None = None,
    chapters: list[str] | None = None,
) -> str:
    description = description if description is not None else f"Watch here: {_utm('youtube')}"
    chapters = chapters if chapters is not None else ["00:00 Intro", "01:30 Main", "05:00 Wrap up"]
    chapters_block = "\n".join(chapters)
    return f"TITLE: {title}\nDESCRIPTION:\n{description}\nCHAPTERS:\n{chapters_block}"


def _render(tmp_path, gateway, platforms: dict, piece=None):
    return renditions_module.render(
        piece or _piece(),
        "## Article\n\nSome article content.",
        data_root=tmp_path / "data",
        gateway=gateway,
        platform_configs=platforms,
        site_url=_SITE_URL,
        utm_template=_UTM_TEMPLATE,
        now=NOW,
    )


# ---------------------------------------------------------------------------
# Canonical / UTM URLs
# ---------------------------------------------------------------------------


def test_canonical_url_matches_piece_yml_shape():
    """TDD 5.2's own `piece.yml` example: `published.url` is
    `site_url + "/blog/" + slug` -- the pre-publish canonical URL renditions
    compute must match that shape exactly, since WP-14 will publish there."""
    assert (
        renditions_module.canonical_url("https://example.com", "duckdb-memory-limit-reality")
        == "https://example.com/blog/duckdb-memory-limit-reality"
    )


def test_canonical_url_strips_trailing_slash():
    assert renditions_module.canonical_url("https://example.com/", "a-piece") == (
        "https://example.com/blog/a-piece"
    )


def test_utm_url_appends_template_per_platform():
    url = renditions_module.utm_url(
        "https://example.com/blog/a-piece", _UTM_TEMPLATE, platform="linkedin", slug="a-piece"
    )
    assert (
        url
        == "https://example.com/blog/a-piece?utm_source=linkedin&utm_medium=social&utm_campaign=a-piece"
    )


# ---------------------------------------------------------------------------
# Pure validation helpers
# ---------------------------------------------------------------------------


def test_markdown_markers_detects_each_kind():
    assert renditions_module._markdown_markers("plain text") == []
    assert "**bold**" in renditions_module._markdown_markers("this is **bold** text")
    assert "_italic_" in renditions_module._markdown_markers("this is _italic_ text")
    assert "# heading" in renditions_module._markdown_markers("# A heading\nbody")
    assert "[text](url)" in renditions_module._markdown_markers("see [this](https://x.test)")


def test_markdown_markers_does_not_flag_snake_case():
    """`_italic_` detection must not false-positive on ordinary
    underscore-separated identifiers like `my_variable_name`."""
    assert renditions_module._markdown_markers("call my_function_name() here") == []


def test_validate_chapters_requires_zero_start():
    violations = renditions_module._validate_chapters(["00:05 Intro", "01:00 Main"])
    assert any("00:00" in v for v in violations)


def test_validate_chapters_requires_ascending_order():
    violations = renditions_module._validate_chapters(["00:00 Intro", "00:00 Also intro"])
    assert any("ascend" in v for v in violations)


def test_validate_chapters_accepts_well_formed_list():
    assert renditions_module._validate_chapters(["00:00 Intro", "01:30 Main", "05:00 Wrap"]) == []


def test_parse_two_part_splits_on_dash_separator():
    body, comment = renditions_module._parse_two_part("body text\n---\ncomment text")
    assert body == "body text"
    assert comment == "comment text"


def test_parse_two_part_without_separator_returns_none_comment():
    body, comment = renditions_module._parse_two_part("just a body, no separator")
    assert body == "just a body, no separator"
    assert comment is None


def test_parse_youtube_response_extracts_all_three_sections():
    content = _youtube_content(title="My Title", chapters=["00:00 Intro", "01:00 Body"])
    title, description, chapters = renditions_module._parse_youtube_response(content)
    assert title == "My Title"
    assert "Watch here" in description
    assert chapters == ["00:00 Intro", "01:00 Body"]


# ---------------------------------------------------------------------------
# Happy path -- render() end to end, real prompt files, fake LLM client
# ---------------------------------------------------------------------------


def test_render_linkedin_writes_rendition_yaml(tmp_path, make_engine_config):
    body = "A clean hook that ends with a period. More body content follows here."
    gateway, client = _gateway(tmp_path, make_engine_config, [_linkedin_content(body)])

    result = _render(tmp_path, gateway, {"linkedin": _load_cfg("linkedin")})

    assert len(client.calls) == 1
    assert len(result) == 1
    assert result[0].body == body
    assert _utm("linkedin") in result[0].first_comment

    reloaded = store.read_rendition(tmp_path / "data", "test-proj", "pc-0001", "linkedin")
    assert reloaded.body == body


def test_render_facebook_writes_rendition_yaml(tmp_path, make_engine_config):
    gateway, client = _gateway(tmp_path, make_engine_config, [_facebook_content()])

    result = _render(tmp_path, gateway, {"facebook": _load_cfg("facebook")})

    assert len(client.calls) == 1
    assert result[0].first_comment is None
    assert _utm("facebook") in result[0].body


def test_render_youtube_writes_title_and_chapters(tmp_path, make_engine_config):
    gateway, client = _gateway(tmp_path, make_engine_config, [_youtube_content()])

    result = _render(tmp_path, gateway, {"youtube": _load_cfg("youtube")})

    assert len(client.calls) == 1
    assert result[0].title == "A short, clean title"
    assert result[0].chapters == ["00:00 Intro", "01:30 Main", "05:00 Wrap up"]


def test_render_multiple_platforms_in_one_call(tmp_path, make_engine_config):
    gateway, client = _gateway(
        tmp_path,
        make_engine_config,
        [
            _linkedin_content("A clean hook that ends with a period. Rest of the post."),
            _facebook_content(),
            _youtube_content(),
        ],
    )

    result = _render(
        tmp_path,
        gateway,
        {
            "linkedin": _load_cfg("linkedin"),
            "facebook": _load_cfg("facebook"),
            "youtube": _load_cfg("youtube"),
        },
    )

    assert len(client.calls) == 3
    assert [r.platform.value for r in result] == ["linkedin", "facebook", "youtube"]
    for platform in ("linkedin", "facebook", "youtube"):
        assert store.rendition_yaml_path(
            tmp_path / "data", "test-proj", "pc-0001", platform
        ).exists()


# ---------------------------------------------------------------------------
# Deliberately-violating fixtures (TDD 12 WP-12 Done-when, one per bullet)
# ---------------------------------------------------------------------------


def test_over_length_fails_after_one_regeneration_attempt(tmp_path, make_engine_config):
    over_length_body = "This hook sentence is fine. " + ("Filler content. " * 200)
    bad = _linkedin_content(over_length_body)
    gateway, client = _gateway(tmp_path, make_engine_config, [bad, bad])

    with pytest.raises(RenditionError, match="max_chars"):
        _render(tmp_path, gateway, {"linkedin": _load_cfg("linkedin")})

    assert len(client.calls) == 2  # initial attempt + exactly one regeneration


def test_url_in_linkedin_body_fails_after_one_regeneration_attempt(tmp_path, make_engine_config):
    body_with_url = f"Check this out: {_utm('linkedin')} -- it changed everything."
    bad = _linkedin_content(body_with_url)
    gateway, client = _gateway(tmp_path, make_engine_config, [bad, bad])

    with pytest.raises(RenditionError, match="links_in_body"):
        _render(tmp_path, gateway, {"linkedin": _load_cfg("linkedin")})

    assert len(client.calls) == 2


def test_markdown_surviving_into_linkedin_fails_after_one_regeneration_attempt(
    tmp_path, make_engine_config
):
    body_with_markdown = "This is a **bold** claim that should have been plain text."
    bad = _linkedin_content(body_with_markdown)
    gateway, client = _gateway(tmp_path, make_engine_config, [bad, bad])

    with pytest.raises(RenditionError, match="markdown"):
        _render(tmp_path, gateway, {"linkedin": _load_cfg("linkedin")})

    assert len(client.calls) == 2


def test_unicode_styling_fails_after_one_regeneration_attempt(tmp_path, make_engine_config):
    body_with_unicode = "This post uses 𝗯𝗼𝗹𝗱 unicode styling instead of plain text."
    bad = _linkedin_content(body_with_unicode)
    gateway, client = _gateway(tmp_path, make_engine_config, [bad, bad])

    with pytest.raises(RenditionError, match="unicode"):
        _render(tmp_path, gateway, {"linkedin": _load_cfg("linkedin")})

    assert len(client.calls) == 2


def test_youtube_title_over_60_chars_fails_after_one_regeneration_attempt(
    tmp_path, make_engine_config
):
    long_title = "A" * 61
    bad = _youtube_content(title=long_title)
    gateway, client = _gateway(tmp_path, make_engine_config, [bad, bad])

    with pytest.raises(RenditionError, match=r"title is \d+ chars"):
        _render(tmp_path, gateway, {"youtube": _load_cfg("youtube")})

    assert len(client.calls) == 2


def test_youtube_chapters_not_starting_at_zero_fails_after_one_regeneration_attempt(
    tmp_path, make_engine_config
):
    bad = _youtube_content(chapters=["00:05 Intro", "01:30 Main", "05:00 Wrap"])
    gateway, client = _gateway(tmp_path, make_engine_config, [bad, bad])

    with pytest.raises(RenditionError, match="00:00"):
        _render(tmp_path, gateway, {"youtube": _load_cfg("youtube")})

    assert len(client.calls) == 2


# ---------------------------------------------------------------------------
# The regeneration path itself: violation on attempt 1, fixed on attempt 2
# ---------------------------------------------------------------------------


def test_regeneration_succeeds_when_second_attempt_fixes_the_violation(
    tmp_path, make_engine_config
):
    over_length_body = "This hook sentence is fine. " + ("Filler content. " * 200)
    fixed_body = "This hook sentence is fine. Short and under the limit."
    bad = _linkedin_content(over_length_body)
    good = _linkedin_content(fixed_body)
    gateway, client = _gateway(tmp_path, make_engine_config, [bad, good])

    result = _render(tmp_path, gateway, {"linkedin": _load_cfg("linkedin")})

    assert len(client.calls) == 2
    assert "max_chars" in client.calls[1]["system"]  # prior_violation was appended for the retry
    assert result[0].body == fixed_body


def test_raised_error_names_the_platform(tmp_path, make_engine_config):
    bad = _facebook_content(body=f"This is **bold** markdown. {_utm('facebook')}")
    gateway, _client = _gateway(tmp_path, make_engine_config, [bad, bad])

    with pytest.raises(RenditionError, match=r"^facebook:"):
        _render(tmp_path, gateway, {"facebook": _load_cfg("facebook")})
