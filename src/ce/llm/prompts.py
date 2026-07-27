"""Prompt loading & rendering (TDD 10.1, ADR-004).

Every LLM call loads a prompt from `prompts/<id>.md`: YAML frontmatter
declaring id/version/tier/schema, then `<system>`/`<user>` sections rendered
with Jinja2's `StrictUndefined` — a template referencing a var the caller
didn't supply is a load-time error, not a silently blank section in a
paid API call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, UndefinedError

from ce.exit_codes import PromptError

# Frontmatter is the YAML between the first `---` fence and the next one;
# everything after is the body that holds the `<system>`/`<user>` sections.
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

_ENV = Environment(undefined=StrictUndefined)


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: int
    tier: str  # reasoning | default | cheap (TDD 10.1)
    output_schema: Path | None
    inputs: list[str]
    system: str
    user: str


def _extract_section(body: str, tag: str) -> str:
    pattern = re.compile(rf"<{tag}>\n?(.*?)\n?</{tag}>", re.DOTALL)
    match = pattern.search(body)
    return match.group(1) if match else ""


def load_prompt(prompt_id: str, prompts_dir: Path = Path("prompts")) -> PromptTemplate:
    """Load and parse `prompts/<prompt_id>.md`. Does not render — see `render_prompt`."""
    path = prompts_dir / f"{prompt_id}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"could not read prompt {prompt_id!r}: {exc}") from exc

    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise PromptError(f"prompt {prompt_id!r} ({path}) is missing YAML frontmatter")

    frontmatter_text, body = match.groups()
    try:
        meta = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise PromptError(f"prompt {prompt_id!r}: invalid frontmatter YAML: {exc}") from exc

    try:
        version = int(meta["version"])
        tier = str(meta["tier"])
    except KeyError as exc:
        raise PromptError(
            f"prompt {prompt_id!r}: frontmatter missing required field {exc}"
        ) from exc

    output_schema_rel = meta.get("output_schema")
    output_schema = (prompts_dir / output_schema_rel) if output_schema_rel else None

    return PromptTemplate(
        id=str(meta.get("id", prompt_id)),
        version=version,
        tier=tier,
        output_schema=output_schema,
        inputs=list(meta.get("inputs", [])),
        system=_extract_section(body, "system"),
        user=_extract_section(body, "user"),
    )


def render_prompt(template: PromptTemplate, vars: dict[str, Any]) -> tuple[str, str]:
    """Render the `<system>`/`<user>` sections. Raises `PromptError` on a missing var."""
    try:
        system = _ENV.from_string(template.system).render(**vars) if template.system else ""
        user = _ENV.from_string(template.user).render(**vars)
    except UndefinedError as exc:
        raise PromptError(f"prompt {template.id!r}: {exc}") from exc
    return system, user
