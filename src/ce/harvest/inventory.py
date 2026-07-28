"""The MATCH step (TDD 10.4, 12 WP-08) — the most important component in
the system. Turns everything captured about a finished project (git
history, transcripts, friction notes, external research, demand signals,
back-catalog) into 6-8 candidate content briefs.

Two independent validation layers run on top of `brief_generate`'s raw
output, because a static JSON schema can't express either of them:

1. **Citation resolvability.** Every `evidence.ref` must name a real
   capture ID or commit SHA that was actually in this run's input —
   `jsonschema` can check *shape*, not whether a string happens to match
   one of this project's specific IDs. `_find_unresolvable_citations`
   checks that after generation; a miss triggers exactly one retry (with
   the specific bad refs fed back into the prompt), then `InventoryError`.
2. **Dedupe (G3) and weak-grounding enforcement.** Every brief gets a
   `dedupe_max_similarity` annotation against the published back-catalog,
   and any brief scoring at/above `config.gates.dedupe.threshold`, or
   generated with `grounding_strength: weak`, is force-set to
   `status: dropped` — never silently dropped from the list (the operator
   should still see why), just unselectable (`assert_selectable`).

`id`/`project`/`status`/`dedupe_max_similarity` are intentionally absent
from `briefs.schema.json` and assigned by this module after generation,
not trusted to the model — deterministic bookkeeping (sequential IDs, the
project this run is for) shouldn't depend on an LLM getting it right,
mirroring `store.generate_capture_id`'s collision-safe-in-code approach
from WP-04.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from ce import store
from ce.exit_codes import InventoryError
from ce.gates.dedupe import max_similarity
from ce.harvest.git import GitHarvest
from ce.harvest.research import ResearchHarvest
from ce.index import EmbeddingsClient
from ce.llm.gateway import Gateway
from ce.models import (
    Brief,
    BriefArchetype,
    BriefDemand,
    BriefEvidence,
    BriefStatus,
    Capture,
    CaptureType,
    GroundingStrength,
    PieceStatus,
    Project,
    PublishableLevel,
)

_RECENT_PUBLISHED_WINDOW_DAYS = 90


# ---------------------------------------------------------------------------
# Prompt context assembly — formatted to plain text in Python (not Jinja
# loops) so each block is independently unit-testable.
# ---------------------------------------------------------------------------


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _format_project_context(project: Project) -> str:
    lines = [
        f"Title: {project.title}",
        f"Hypothesis: {project.selection.hypothesis or '(none recorded)'}",
        f"Expected failure surface: {project.selection.expected_failure_surface or '(none recorded)'}",
        f"Demand signals at selection: {', '.join(project.selection.demand_signals) or '(none recorded)'}",
        f"Tags: {', '.join(project.tags) or '(none)'}",
    ]
    return "\n".join(lines)


def _format_git_context(git_harvest: GitHarvest, project: Project) -> str:
    """Redacts repo name and per-commit stats for `lessons-only` repos
    (TDD 6.1) — only the (already-redacted-at-source, see WP-05's
    `commit_summarize`) `summary` and a bare short SHA survive, since a
    SHA alone names neither a repo, a file, nor any code.
    """
    lessons_only_by_name = {
        r.name: r.publishable == PublishableLevel.LESSONS_ONLY for r in project.repos
    }
    blocks: list[str] = []
    for repo_harvest in git_harvest.repos:
        lessons_only = lessons_only_by_name.get(repo_harvest.repo, False)
        header = "Repo: (private, lessons-only)" if lessons_only else f"Repo: {repo_harvest.repo}"
        lines = [header]
        for c in repo_harvest.commits:
            short_sha = c.sha[:7]
            if lessons_only:
                lines.append(f"  - [{short_sha}] (score {c.score}) {c.summary}")
            else:
                lines.append(
                    f"  - [{short_sha}] (score {c.score}, +{c.insertions}/-{c.deletions}, "
                    f"{c.files_changed} files) {c.summary}"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "(no significant commits)"


def _format_captures_context(data_root: Path, project: Project, captures: list[Capture]) -> str:
    project_root = store.project_dir(data_root, project.slug)
    blocks: list[str] = []
    for c in captures:
        header = (
            f"Capture {c.id} ({c.type.value}, {c.moment.value}, {c.captured_at:%Y-%m-%d %H:%M})"
        )
        context_line = f"  context: {c.context or '(none)'}"
        if c.type == CaptureType.AUDIO and c.derived is not None:
            raw = ""
            clean = ""
            if c.derived.transcript_raw:
                raw_path = project_root / c.derived.transcript_raw
                raw = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
            if c.derived.transcript_clean:
                clean_path = project_root / c.derived.transcript_clean
                clean = clean_path.read_text(encoding="utf-8") if clean_path.exists() else ""
            blocks.append(f"{header}\n{context_line}\n  RAW: {raw}\n  CLEAN: {clean}")
        else:
            blocks.append(f"{header}\n{context_line}")
    return "\n\n".join(blocks) if blocks else "(no captures yet)"


def _format_research_context(research_harvest: ResearchHarvest) -> str:
    if not research_harvest.sources:
        return "(no external research)"
    return "\n".join(
        f"- [{s.stance.value}] {s.title} ({s.url}): {s.summary}" for s in research_harvest.sources
    )


def _first_nonblank_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def _recent_published_summaries(
    data_root: Path,
    *,
    within_days: int = _RECENT_PUBLISHED_WINDOW_DAYS,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Titles + a one-line summary of everything published in the last
    `within_days`, across every project — dedupe context (TDD 10.4), so
    the model doesn't propose a piece that's a near-repeat of one already
    live. `Piece` has no title of its own (TDD 5.2); the title comes from
    the `Brief` that spawned it, and the "summary" is pragmatically the
    article's first non-blank line — there's no dedicated summary field
    anywhere in the on-disk schema to draw from instead.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=within_days)
    results: list[dict[str, str]] = []
    for project in store.list_projects(data_root):
        briefs_by_id = {b.id: b for b in store.read_briefs(data_root, project.slug)}
        for piece in store.list_pieces(data_root, project.slug):
            if piece.status != PieceStatus.PUBLISHED or piece.published is None:
                continue
            if piece.published.at < cutoff:
                continue
            brief = briefs_by_id.get(piece.brief_id)
            title = brief.title if brief else piece.slug
            article_path = store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
            summary = (
                _first_nonblank_line(article_path.read_text(encoding="utf-8"))
                if article_path.exists()
                else ""
            )
            results.append({"title": title, "summary": summary})
    return results


def _format_recent_published_context(summaries: list[dict[str, str]]) -> str:
    if not summaries:
        return "(nothing published in this window)"
    return "\n".join(f"- {s['title']}: {s['summary']}" for s in summaries)


def _format_demand_context(data_root: Path) -> str:
    """Recent `sweeps/*.md` and hand-maintained `inbound.md` (TDD 10.4) —
    both optional; WP-16 (the sweep producer) isn't built yet, so this is
    best-effort, not a hard dependency."""
    parts = []
    inbound = _read_optional_text(data_root / "inbound.md")
    if inbound:
        parts.append(f"inbound.md:\n{inbound}")
    sweeps_dir = data_root / "sweeps"
    if sweeps_dir.exists():
        for sweep_path in sorted(sweeps_dir.glob("*.md"))[-4:]:
            text = _read_optional_text(sweep_path)
            if text:
                parts.append(f"{sweep_path.name}:\n{text}")
    return "\n\n".join(parts) if parts else "(no sweep/inbound signals recorded)"


# ---------------------------------------------------------------------------
# Schema + citation resolvability
# ---------------------------------------------------------------------------


def _load_item_schema(prompts_dir: Path) -> dict[str, Any]:
    schema_path = prompts_dir / "_schemas" / "briefs.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _build_array_schema(prompts_dir: Path, *, min_briefs: int, max_briefs: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": min_briefs,
        "maxItems": max_briefs,
        "items": _load_item_schema(prompts_dir),
    }


def _find_unresolvable_citations(
    briefs_data: list[dict[str, Any]], capture_ids: set[str], commit_shas: set[str]
) -> list[str]:
    unresolvable: list[str] = []
    for brief in briefs_data:
        for evidence in brief.get("evidence", []):
            ref = evidence.get("ref", "")
            base_ref = ref.split("@", 1)[0]
            if base_ref in capture_ids:
                continue
            if len(base_ref) >= 7 and any(
                sha.lower().startswith(base_ref.lower()) for sha in commit_shas
            ):
                continue
            unresolvable.append(ref)
    return unresolvable


def _format_retry_feedback(unresolvable: list[str]) -> str:
    refs = ", ".join(repr(r) for r in unresolvable)
    return (
        f"These evidence refs from your last attempt do not match any real "
        f"capture ID or commit SHA in the input: {refs}. Replace them with "
        f"real citations, or drop the claims they supported."
    )


# ---------------------------------------------------------------------------
# Dedupe (G3) + weak-grounding enforcement
# ---------------------------------------------------------------------------


def _embed_text_for_brief(brief_data: dict[str, Any]) -> str:
    return f"{brief_data['title']}\n\n{brief_data['angle']}"


@dataclass
class DedupeSettings:
    conn: sqlite3.Connection
    embeddings_client: EmbeddingsClient
    embeddings_model: str
    threshold: float
    scope_days: int
    now: datetime | None = None


def assert_selectable(brief: Brief) -> None:
    """`ce brief select` (WP-09) refuses a `dropped` brief (TDD 12 WP-08
    Done-when) — the actual CLI command belongs to WP-09 (it creates a
    `Piece`, out of this module's scope), but the refusal rule itself is
    inventory-level business logic and lives here, tested directly, same
    split WP-01 used for `ce project show`'s read/format logic.
    """
    if brief.status == BriefStatus.DROPPED:
        raise InventoryError(
            f"brief {brief.id!r} is dropped and cannot be selected",
            hint="weak grounding or too similar to a published piece; see risk_flags",
        )


# ---------------------------------------------------------------------------
# inventory.md — human-readable, ranked (TDD 10.4)
# ---------------------------------------------------------------------------

_GROUNDING_RANK = {
    GroundingStrength.STRONG: 0,
    GroundingStrength.MODERATE: 1,
    GroundingStrength.WEAK: 2,
}


def _sort_key(brief: Brief) -> tuple[int, int, int]:
    dropped = brief.status == BriefStatus.DROPPED
    return (dropped, -brief.demand.recurrence, _GROUNDING_RANK[brief.grounding_strength])


def format_inventory_md(briefs: list[Brief]) -> str:
    ranked = sorted(briefs, key=_sort_key)
    lines = ["# Content inventory", ""]
    for b in ranked:
        lines.append(f"## {b.title}")
        lines.append(
            f"- archetype: {b.archetype.value} | angle: {b.angle} | "
            f"status: {b.status.value} | grounding: {b.grounding_strength.value}"
        )
        lines.append(
            f"- platforms: {', '.join(p.value for p in b.target_platforms)} | "
            f"demand recurrence: {b.demand.recurrence} | "
            f"dedupe similarity: {b.dedupe_max_similarity:.2f}"
        )
        lines.append(f"- weakest point: {b.weakest_point}")
        if b.risk_flags:
            lines.append(f"- risk flags: {', '.join(b.risk_flags)}")
        lines.append(f"- evidence: {len(b.evidence)} citation(s)")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# generate() — TDD 10.4 / 12 WP-08 public interface
# ---------------------------------------------------------------------------


def generate(
    project: Project,
    git_harvest: GitHarvest,
    research_harvest: ResearchHarvest,
    captures: list[Capture],
    *,
    data_root: Path,
    gateway: Gateway,
    dedupe: DedupeSettings,
    min_briefs: int,
    max_briefs: int,
    brand_brief_path: Path = Path("config/brand-brief.md"),
) -> list[Brief]:
    """Runs the MATCH step end to end: assembles every input TDD 10.4
    names, calls `brief_generate` (retrying once if a citation doesn't
    resolve), annotates dedupe similarity, force-drops weak/too-similar
    briefs, and writes `briefs.yml` + `inventory.md`.
    """
    capture_ids = {c.id for c in captures}
    commit_shas = {c.sha for repo in git_harvest.repos for c in repo.commits}

    recent_published = _recent_published_summaries(data_root, now=dedupe.now)
    vars_ = {
        "brand_brief": _read_optional_text(brand_brief_path) or "(no brand brief on file)",
        "project_context": _format_project_context(project),
        "git_context": _format_git_context(git_harvest, project),
        "captures_context": _format_captures_context(data_root, project, captures),
        "friction": _read_optional_text(
            store.project_dir(data_root, project.slug) / "captures" / "friction.md"
        )
        or "(no friction notes)",
        "research_context": _format_research_context(research_harvest),
        "demand_context": _format_demand_context(data_root),
        "recent_published_context": _format_recent_published_context(recent_published),
        "archetypes": ", ".join(a.value for a in BriefArchetype),
        "retry_feedback": "",
    }

    schema = _build_array_schema(gateway.prompts_dir, min_briefs=min_briefs, max_briefs=max_briefs)

    result = gateway.complete("brief_generate", vars_, schema=schema, tier="reasoning")
    unresolvable = _find_unresolvable_citations(result.parsed, capture_ids, commit_shas)
    if unresolvable:
        vars_ = {**vars_, "retry_feedback": _format_retry_feedback(unresolvable)}
        result = gateway.complete(
            "brief_generate", vars_, schema=schema, tier="reasoning", cache=False
        )
        unresolvable = _find_unresolvable_citations(result.parsed, capture_ids, commit_shas)
        if unresolvable:
            raise InventoryError(
                f"brief_generate: unresolvable evidence citation(s) after one retry: "
                f"{', '.join(unresolvable)}"
            )

    briefs: list[Brief] = []
    for i, brief_data in enumerate(result.parsed, start=1):
        embedding = np.asarray(
            dedupe.embeddings_client.embed(
                _embed_text_for_brief(brief_data), model=dedupe.embeddings_model
            )
        )
        match = max_similarity(
            embedding, conn=dedupe.conn, scope_days=dedupe.scope_days, now=dedupe.now
        )
        similarity = match[1] if match else 0.0

        weak = brief_data["grounding_strength"] == GroundingStrength.WEAK.value
        blocked = match is not None and similarity >= dedupe.threshold
        status = BriefStatus.DROPPED if (weak or blocked) else BriefStatus.CANDIDATE
        risk_flags = list(brief_data["risk_flags"])
        if blocked:
            risk_flags.append(f"duplicate of {match[0]!r} (similarity {similarity:.2f})")

        briefs.append(
            Brief(
                id=f"br-{i:02d}",
                project=project.slug,
                dedupe_max_similarity=similarity,
                status=status,
                risk_flags=risk_flags,
                archetype=BriefArchetype(brief_data["archetype"]),
                title=brief_data["title"],
                angle=brief_data["angle"],
                target_platforms=brief_data["target_platforms"],
                demand=BriefDemand(**brief_data["demand"]),
                evidence=[BriefEvidence(**e) for e in brief_data["evidence"]],
                grounding_strength=GroundingStrength(brief_data["grounding_strength"]),
                weakest_point=brief_data["weakest_point"],
            )
        )

    store.write_briefs(data_root, project.slug, briefs)
    inventory_path = store.harvest_dir(data_root, project.slug) / "inventory.md"
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(format_inventory_md(briefs), encoding="utf-8")
    return briefs
