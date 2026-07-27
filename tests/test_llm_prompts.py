"""WP-02 acceptance: prompt frontmatter loading and StrictUndefined rendering (TDD 10.1)."""

from pathlib import Path

import pytest

from ce.exit_codes import PromptError
from ce.llm.prompts import load_prompt, render_prompt

PROMPTS_DIR = Path("prompts")


def test_load_prompt_parses_frontmatter_and_sections():
    template = load_prompt("_wp02_echo", PROMPTS_DIR)
    assert template.id == "_wp02_echo"
    assert template.version == 1
    assert template.tier == "cheap"
    assert template.output_schema is None
    assert template.inputs == ["message"]
    assert "{{ message }}" in template.user
    assert "throwaway test prompt" in template.system


def test_load_prompt_with_schema_resolves_relative_to_prompts_dir():
    template = load_prompt("_wp02_structured", PROMPTS_DIR)
    assert template.output_schema == PROMPTS_DIR / "_schemas" / "_wp02_structured.schema.json"
    assert template.output_schema.exists()


def test_load_missing_prompt_raises_PromptError():
    with pytest.raises(PromptError, match="could not read"):
        load_prompt("does-not-exist", PROMPTS_DIR)


def test_load_prompt_missing_frontmatter_raises_PromptError(tmp_path):
    (tmp_path / "bare.md").write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(PromptError, match="frontmatter"):
        load_prompt("bare", tmp_path)


def test_load_prompt_missing_required_field_raises_PromptError(tmp_path):
    (tmp_path / "incomplete.md").write_text(
        "---\nid: incomplete\nversion: 1\n---\n\n<user>hi</user>\n", encoding="utf-8"
    )
    with pytest.raises(PromptError, match="tier"):
        load_prompt("incomplete", tmp_path)


def test_render_prompt_fills_vars():
    template = load_prompt("_wp02_echo", PROMPTS_DIR)
    system, user = render_prompt(template, {"message": "hello world"})
    assert user.strip() == "hello world"
    assert system  # non-empty, from <system>


def test_render_prompt_missing_var_raises_PromptError():
    template = load_prompt("_wp02_echo", PROMPTS_DIR)
    with pytest.raises(PromptError):
        render_prompt(template, {})
