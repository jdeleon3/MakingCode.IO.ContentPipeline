"""`ce brief select` + the draft/grade/revise writer loop (TDD 10.5, 12 WP-09).

Two public entry points:

- `select_brief()` — promotes a `Brief` to a `Piece`. `ce brief select
  <brief-id>` (TDD 9) takes no `--project`, so the brief has to be found
  by scanning every project (`store.find_brief`); refuses `dropped` briefs
  via `harvest/inventory.py::assert_selectable`, the same check WP-08 built
  for exactly this call site.
- `produce()` — TDD 10.5's loop: draft once, then grade/revise up to
  `max_attempts` times, stopping early once the weighted total clears
  `min_grade`. Writes `article.md`, `grades.json` (full per-attempt detail,
  including prompt versions — TDD 12's Done-when line), and the summary
  embedded on `piece.yml#grades`.

`total` is computed in code from the model's per-dimension `scores` and
`config.produce.grade_weights`, never trusted to the model — same
deterministic-bookkeeping split WP-08 used for `Brief.id`/`dedupe_max_similarity`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from ce import store
from ce.exit_codes import CEError
from ce.harvest.git import GitHarvest
from ce.harvest.inventory import assert_selectable
from ce.harvest.research import ResearchHarvest
from ce.index import EmbeddingsClient, cosine_similarity
from ce.llm.gateway import Gateway
from ce.models import Brief, BriefStatus, Capture, GradeAttempt, GradeScores, Piece, Project

# TDD 10.5 asks for a "platform-agnostic length target" without a number or
# a config field. Picked once here rather than adding an engine.yml field
# for a single hardcoded prompt input; revisit if per-project tuning turns
# out to matter.
_LENGTH_TARGET = "900-1500 words"

_VOICE_CHUNK_MIN_CHARS = 40  # skip stray blank/near-empty paragraphs
_VOICE_TOP_K = 5

_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------------------
# ce brief select
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug or "untitled"


def select_brief(brief_id: str, *, data_root: Path, now: datetime | None = None) -> Piece:
    """Promotes `brief_id` to a `Piece` (TDD 9: `ce brief select <brief-id>
    → creates a Piece, returns piece-id`). Refuses a `dropped` brief."""
    found = store.find_brief(data_root, brief_id)
    if found is None:
        raise CEError(f"brief {brief_id!r} not found")
    project, brief = found
    assert_selectable(brief)

    piece = Piece(
        id=store.generate_piece_id(data_root, project.slug),
        brief_id=brief.id,
        project=project.slug,
        slug=_slugify(brief.title),
        created_at=now or datetime.now(UTC),
        article_path=Path("article.md"),
    )
    store.write_piece(data_root, project.slug, piece)

    briefs = store.read_briefs(data_root, project.slug)
    for b in briefs:
        if b.id == brief.id:
            b.status = BriefStatus.SELECTED
    store.write_briefs(data_root, project.slug, briefs)

    return piece


# ---------------------------------------------------------------------------
# Prompt context assembly
# ---------------------------------------------------------------------------


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _capture_transcript_text(project_root: Path, capture: Capture) -> str:
    """Full raw + clean transcript text for one cited capture (TDD 11:
    `article_draft` "receives raw + clean transcripts") — not just the
    brief-time `note`/`quote` MATCH already condensed onto the evidence
    entry. Mirrors `harvest/inventory.py::_format_captures_context`'s
    raw+clean read, but for one cited capture rather than every capture in
    the project.
    """
    if capture.derived is None:
        return ""
    parts = []
    if capture.derived.transcript_raw:
        raw_path = project_root / capture.derived.transcript_raw
        if raw_path.exists():
            parts.append(f"RAW: {raw_path.read_text(encoding='utf-8')}")
    if capture.derived.transcript_clean:
        clean_path = project_root / capture.derived.transcript_clean
        if clean_path.exists():
            parts.append(f"CLEAN: {clean_path.read_text(encoding='utf-8')}")
    return "\n".join(parts)


def _resolve_commit_summary(base_ref: str, git_harvest: GitHarvest) -> str | None:
    """Matches a full or short SHA against `git.json`'s commits, same
    short-SHA-prefix rule `harvest/inventory.py::_find_unresolvable_citations`
    uses to validate citations at MATCH time."""
    for repo in git_harvest.repos:
        for commit in repo.commits:
            if commit.sha == base_ref or (
                len(base_ref) >= 7 and commit.sha.lower().startswith(base_ref.lower())
            ):
                return commit.summary
    return None


def _format_evidence_context(
    brief: Brief,
    *,
    data_root: Path,
    project: Project,
    git_harvest: GitHarvest,
    research_harvest: ResearchHarvest,
) -> str:
    """Resolves each `evidence.ref` back to its real source material (TDD
    10.5: "cited evidence in full"; TDD 11: article_draft "receives raw +
    clean transcripts") — a capture ref to its transcript, a commit SHA to
    `git.json`'s (already-condensed, never-raw-diff) summary, a research
    URL to `research.json`'s summary. Scoped to only what this brief cites,
    not the whole harvest (unlike WP-08's inventory context, which needs
    everything in order to choose *what* to cite in the first place).
    """
    if not brief.evidence:
        return "(no cited evidence)"

    project_root = store.project_dir(data_root, project.slug)
    captures_by_id = {c.id: c for c in store.list_captures(data_root, project.slug)}
    research_by_url = {s.url: s for s in research_harvest.sources}

    blocks = []
    for e in brief.evidence:
        base_ref = e.ref.split("@", 1)[0]
        header = f"[{e.kind}] {e.ref}"
        if e.note:
            header += f" — {e.note}"

        if base_ref in captures_by_id:
            body = _capture_transcript_text(project_root, captures_by_id[base_ref])
        else:
            body = _resolve_commit_summary(base_ref, git_harvest)
            if body is None and e.ref in research_by_url:
                body = research_by_url[e.ref].summary

        if not body:
            # Cited at MATCH time but doesn't resolve now (harvest re-run,
            # edited/deleted capture, etc.) -- fall back to whatever MATCH
            # itself captured rather than dropping the citation entirely.
            body = e.quote or "(source no longer resolves)"

        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


def _voice_chunks(voice_dir: Path) -> list[str]:
    """Paragraph-level chunks from every `voice/*.md` file. `voice/` is a
    hand-maintained corpus of prior writing (TDD §7); best-effort like
    WP-08's sweeps/inbound context if it's empty or missing."""
    if not voice_dir.exists():
        return []
    chunks: list[str] = []
    for path in sorted(voice_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for para in text.split("\n\n"):
            stripped = para.strip()
            if len(stripped) >= _VOICE_CHUNK_MIN_CHARS:
                chunks.append(stripped)
    return chunks


def _top_voice_chunks(
    chunks: list[str],
    query: str,
    *,
    embeddings_client: EmbeddingsClient,
    model: str,
    k: int = _VOICE_TOP_K,
) -> list[str]:
    """Top-`k` chunks by cosine similarity to `query` (TDD 10.5: "voice RAG,
    top-5 chunks from voice/"). Brute-force, re-embedded on every call, no
    persistent index — same ADR-003 bet as `gates/dedupe.py`, and a voice
    corpus for one operator's own writing is smaller still.
    """
    if not chunks:
        return []
    query_vec = np.asarray(embeddings_client.embed(query, model=model))
    scored = [
        (
            cosine_similarity(query_vec, np.asarray(embeddings_client.embed(chunk, model=model))),
            chunk,
        )
        for chunk in chunks
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:k]]


def _format_voice_context(chunks: list[str]) -> str:
    if not chunks:
        return "(no voice samples on file)"
    return "\n\n---\n\n".join(chunks)


def _format_weights_context(weights: GradeScores) -> str:
    return (
        f"Weights: hook={weights.hook}, evidence={weights.evidence}, "
        f"specificity={weights.specificity}, voice={weights.voice}, cta={weights.cta}"
    )


def _weighted_total(scores: GradeScores, weights: GradeScores) -> float:
    return (
        scores.hook * weights.hook
        + scores.evidence * weights.evidence
        + scores.specificity * weights.specificity
        + scores.voice * weights.voice
        + scores.cta * weights.cta
    )


def _format_fixes(fixes: list[dict[str, str]]) -> str:
    """Defensively re-sorts by impact rather than trusting the model's
    array order — same "don't trust the model for bookkeeping it might get
    wrong" stance as WP-08's brief ids/dedupe scores."""
    if not fixes:
        return "(no fixes -- grade already cleared the bar)"
    ranked = sorted(fixes, key=lambda f: _IMPACT_RANK.get(f["impact"], len(_IMPACT_RANK)))
    return "\n".join(
        f"- [{f['impact']}] ({f['dimension']}) {f['issue']}\n  fix: {f['suggested_change']}"
        for f in ranked
    )


def _load_grade_schema(prompts_dir: Path) -> dict[str, Any]:
    schema_path = prompts_dir / "_schemas" / "grade.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# grades.json — full per-attempt detail (TDD 12 WP-09 Done-when: "records
# every attempt with prompt versions"). piece.yml#grades stays the terser
# TDD 5.2 summary (attempt/total/scores only); this is the richer sibling.
# ---------------------------------------------------------------------------


class TopFix(BaseModel):
    dimension: str
    issue: str
    suggested_change: str
    impact: str


class GradeAttemptRecord(BaseModel):
    attempt: int
    total: float
    scores: GradeScores
    draft_prompt_version: int
    grade_prompt_version: int
    top_fixes: list[TopFix] = Field(default_factory=list)


class GradesLog(BaseModel):
    attempts: list[GradeAttemptRecord] = Field(default_factory=list)


def _write_grades_log(path: Path, log: GradesLog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(log.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# produce() — TDD 10.5 / 12 WP-09 public interface
# ---------------------------------------------------------------------------


@dataclass
class VoiceRagSettings:
    embeddings_client: EmbeddingsClient
    embeddings_model: str
    voice_dir: Path = Path("voice")


def produce(
    piece: Piece,
    brief: Brief,
    project: Project,
    *,
    data_root: Path,
    gateway: Gateway,
    git_harvest: GitHarvest,
    research_harvest: ResearchHarvest,
    min_grade: float,
    max_attempts: int,
    grade_weights: GradeScores,
    voice: VoiceRagSettings,
    brand_brief_path: Path = Path("config/brand-brief.md"),
    cache: bool = True,
    now: datetime | None = None,
) -> Piece:
    """Draft, grade and revise `piece` (TDD 10.5) until the weighted total
    clears `min_grade` or `max_attempts` is reached, writes `article.md` +
    `grades.json`, sets `piece.generated_at` (ADR-008), and returns the
    updated `Piece`. Always overwrites on re-run — no partial-resume state
    to skip, same accepted gap as `ce harvest --force`.

    `git_harvest`/`research_harvest` are read from `harvest/git.json` /
    `harvest/research.json` by the caller (`ce produce` runs as a separate
    invocation from `ce harvest`, so there's no in-memory harvest left over
    — see `harvest.git.read_git_harvest`/`harvest.research.read_research_harvest`).
    """
    evidence_context = _format_evidence_context(
        brief,
        data_root=data_root,
        project=project,
        git_harvest=git_harvest,
        research_harvest=research_harvest,
    )
    voice_query = f"{brief.title}\n{brief.angle}"
    voice_chunks = _top_voice_chunks(
        _voice_chunks(voice.voice_dir),
        voice_query,
        embeddings_client=voice.embeddings_client,
        model=voice.embeddings_model,
    )

    draft_result = gateway.complete(
        "article_draft",
        {
            "brand_brief": _read_optional_text(brand_brief_path) or "(no brand brief on file)",
            "voice_context": _format_voice_context(voice_chunks),
            "brief_title": brief.title,
            "brief_angle": brief.angle,
            "archetype": brief.archetype.value,
            "weakest_point": brief.weakest_point,
            "evidence_context": evidence_context,
            "length_target": _LENGTH_TARGET,
        },
        tier="default",
        cache=cache,
    )
    draft = draft_result.content
    draft_prompt_version = draft_result.prompt_version

    schema = _load_grade_schema(gateway.prompts_dir)
    weights_context = _format_weights_context(grade_weights)

    grades: list[GradeAttempt] = []
    records: list[GradeAttemptRecord] = []

    for attempt in range(1, max_attempts + 1):
        grade_result = gateway.complete(
            "article_grade",
            {
                "article": draft,
                "evidence_context": evidence_context,
                "weights_context": weights_context,
            },
            schema=schema,
            tier="reasoning",
            cache=cache,
        )
        scores = GradeScores(**grade_result.parsed["scores"])
        total = _weighted_total(scores, grade_weights)
        top_fixes = [TopFix(**f) for f in grade_result.parsed["top_fixes"]]

        grades.append(GradeAttempt(attempt=attempt, total=total, scores=scores))
        records.append(
            GradeAttemptRecord(
                attempt=attempt,
                total=total,
                scores=scores,
                draft_prompt_version=draft_prompt_version,
                grade_prompt_version=grade_result.prompt_version,
                top_fixes=top_fixes,
            )
        )

        if total >= min_grade:
            break

        revise_result = gateway.complete(
            "article_revise",
            {"article": draft, "fixes": _format_fixes(grade_result.parsed["top_fixes"])},
            tier="default",
            cache=cache,
        )
        draft = revise_result.content
        draft_prompt_version = revise_result.prompt_version

    article_dir = store.piece_dir(data_root, project.slug, piece.id)
    article_dir.mkdir(parents=True, exist_ok=True)
    (article_dir / piece.article_path).write_text(draft, encoding="utf-8")
    _write_grades_log(
        store.grades_json_path(data_root, project.slug, piece.id), GradesLog(attempts=records)
    )

    piece.grades = grades
    piece.generated_at = now or datetime.now(UTC)
    store.write_piece(data_root, project.slug, piece)
    return piece
