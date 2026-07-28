"""WP-09 acceptance (TDD 10.5, 12): the draft/grade/revise writer loop.

Done-when: loop terminates on >=min_grade or max_attempts; grades.json
records every attempt with prompt versions; grade >=2 is a strict
improvement over attempt 1 on the fixture; article.md written;
piece.generated_at set.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ce import store
from ce.exit_codes import CEError, InventoryError
from ce.harvest.git import CommitRecord, GitHarvest, RedactionSummary, RepoHarvest
from ce.harvest.research import ResearchHarvest, ResearchSource, Stance
from ce.llm.gateway import Gateway, ProviderResponse
from ce.models import (
    Brief,
    BriefArchetype,
    BriefDemand,
    BriefEvidence,
    BriefStatus,
    Capture,
    CaptureDerived,
    CaptureMoment,
    CaptureType,
    GroundingStrength,
    Piece,
    Project,
    PublishableLevel,
    RepoRef,
)
from ce.produce import writer

NOW = datetime(2026, 7, 28, tzinfo=UTC)

_EMPTY_GIT_HARVEST = GitHarvest(repos=[])
_EMPTY_RESEARCH_HARVEST = ResearchHarvest(sources=[])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _project(slug: str = "test-proj") -> Project:
    return Project(
        slug=slug,
        title="Streaming ETL with DuckDB",
        started_at=date(2026, 7, 1),
        repos=[RepoRef(name=slug, path=Path("/code") / slug, publishable=PublishableLevel.FULL)],
    )


def _brief(
    *,
    brief_id: str = "br-01",
    status: BriefStatus = BriefStatus.CANDIDATE,
    project: str = "test-proj",
) -> Brief:
    return Brief(
        id=brief_id,
        project=project,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="DuckDB's memory limit is not what the docs imply",
        angle="counter-position",
        demand=BriefDemand(recurrence=3, signals=["HN thread"]),
        evidence=[
            BriefEvidence(kind="git", ref="a3f9c21", note="the OOM fix", quote=None),
            BriefEvidence(kind="audio", ref="cap-20260716-1423", quote="it just died, no warning"),
        ],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.31,
        weakest_point="n=1, single workload shape, 40GB",
        status=status,
    )


def _piece(*, project: str = "test-proj", brief_id: str = "br-01") -> Piece:
    return Piece(
        id="pc-0001",
        brief_id=brief_id,
        project=project,
        slug="duckdb-memory-limit-reality",
        created_at=NOW,
        article_path=Path("article.md"),
    )


class FakeLLMClient:
    """Returns each response in `contents`, in call order, verbatim — the
    caller decides whether a given response is plain markdown (draft/
    revise) or a JSON string (grade, schema-validated by the gateway)."""

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


def _grade_json(*, hook=9, evidence=9, specificity=9, voice=9, cta=9, fixes=None) -> str:
    return json.dumps(
        {
            "scores": {
                "hook": hook,
                "evidence": evidence,
                "specificity": specificity,
                "voice": voice,
                "cta": cta,
            },
            "top_fixes": fixes or [],
        }
    )


_WEAK_GRADE = _grade_json(
    hook=4,
    evidence=4,
    specificity=4,
    voice=4,
    cta=4,
    fixes=[
        {
            "dimension": "hook",
            "issue": "opens with a generic statement",
            "suggested_change": "open with the 40GB OOM instead",
            "impact": "high",
        }
    ],
)
_STRONG_GRADE = _grade_json(hook=9, evidence=9, specificity=9, voice=9, cta=9)


def _voice_settings(fake_embeddings_client, tmp_path: Path) -> writer.VoiceRagSettings:
    return writer.VoiceRagSettings(
        embeddings_client=fake_embeddings_client,
        embeddings_model="text-embedding-3-small",
        voice_dir=tmp_path / "voice",
    )


# ---------------------------------------------------------------------------
# select_brief (TDD 9: ce brief select)
# ---------------------------------------------------------------------------


def test_select_brief_creates_a_piece_and_marks_the_brief_selected(tmp_path):
    project = _project()
    store.write_project(tmp_path / "data", project)
    store.write_briefs(tmp_path / "data", project.slug, [_brief()])

    piece = writer.select_brief("br-01", data_root=tmp_path / "data", now=NOW)

    assert piece.id == "pc-0001"
    assert piece.brief_id == "br-01"
    assert piece.project == project.slug
    assert piece.slug == "duckdb-s-memory-limit-is-not-what-the-docs-imply"
    assert piece.created_at == NOW

    reloaded = store.read_piece(tmp_path / "data", project.slug, piece.id)
    assert reloaded == piece

    [reloaded_brief] = store.read_briefs(tmp_path / "data", project.slug)
    assert reloaded_brief.status == BriefStatus.SELECTED


def test_select_brief_refuses_a_dropped_brief(tmp_path):
    project = _project()
    store.write_project(tmp_path / "data", project)
    store.write_briefs(tmp_path / "data", project.slug, [_brief(status=BriefStatus.DROPPED)])

    with pytest.raises(InventoryError, match="dropped"):
        writer.select_brief("br-01", data_root=tmp_path / "data")


def test_select_brief_unknown_id_is_a_readable_error(tmp_path):
    with pytest.raises(CEError, match="not found"):
        writer.select_brief("br-99", data_root=tmp_path / "data")


# ---------------------------------------------------------------------------
# produce() — the draft/grade/revise loop
# ---------------------------------------------------------------------------


def test_produce_terminates_early_once_min_grade_clears(
    tmp_path, make_engine_config, fake_embeddings_client
):
    gateway, llm_client = _gateway(
        tmp_path,
        make_engine_config,
        contents=[
            "# Draft one\n\nThe join OOM'd at 40GB.",
            _WEAK_GRADE,
            "# Draft two\n\nOpens with the 40GB OOM directly.",
            _STRONG_GRADE,
        ],
    )
    piece = _piece()
    result = writer.produce(
        piece,
        _brief(),
        _project(),
        data_root=tmp_path / "data",
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        min_grade=8.0,
        max_attempts=3,
        grade_weights=make_engine_config().produce.grade_weights,
        voice=_voice_settings(fake_embeddings_client, tmp_path),
        now=NOW,
    )

    assert len(result.grades) == 2
    assert result.grades[1].total > result.grades[0].total  # strict improvement, Done-when
    assert result.grades[1].total >= 8.0
    assert result.generated_at == NOW
    # 1 draft + 2 grades + 1 revise = 4 calls; loop stopped before a third grade
    assert len(llm_client.calls) == 4

    article_path = store.piece_dir(tmp_path / "data", piece.project, piece.id) / "article.md"
    assert (
        article_path.read_text(encoding="utf-8")
        == "# Draft two\n\nOpens with the 40GB OOM directly."
    )


def test_produce_stops_at_max_attempts_without_clearing_min_grade(
    tmp_path, make_engine_config, fake_embeddings_client
):
    gateway, llm_client = _gateway(
        tmp_path,
        make_engine_config,
        contents=[
            "# Draft one",
            _WEAK_GRADE,
            "# Draft two",
            _WEAK_GRADE,
            "# Draft three",
            _WEAK_GRADE,
            "# Draft four",
        ],
    )
    result = writer.produce(
        _piece(),
        _brief(),
        _project(),
        data_root=tmp_path / "data",
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        min_grade=8.0,
        max_attempts=3,
        grade_weights=make_engine_config().produce.grade_weights,
        voice=_voice_settings(fake_embeddings_client, tmp_path),
        now=NOW,
    )

    assert len(result.grades) == 3
    assert all(g.total < 8.0 for g in result.grades)
    # 1 draft + 3 grades + 3 revises = 7 calls
    assert len(llm_client.calls) == 7


def test_produce_writes_grades_json_with_prompt_versions(
    tmp_path, make_engine_config, fake_embeddings_client
):
    gateway, _ = _gateway(tmp_path, make_engine_config, contents=["# Draft one", _STRONG_GRADE])
    piece = _piece()
    writer.produce(
        piece,
        _brief(),
        _project(),
        data_root=tmp_path / "data",
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        min_grade=8.0,
        max_attempts=3,
        grade_weights=make_engine_config().produce.grade_weights,
        voice=_voice_settings(fake_embeddings_client, tmp_path),
        now=NOW,
    )

    log_path = store.grades_json_path(tmp_path / "data", piece.project, piece.id)
    data = json.loads(log_path.read_text(encoding="utf-8"))

    assert len(data["attempts"]) == 1
    attempt = data["attempts"][0]
    assert attempt["attempt"] == 1
    assert attempt["draft_prompt_version"] == 1
    assert attempt["grade_prompt_version"] == 1
    assert "scores" in attempt and "total" in attempt


def test_produce_sets_generated_at_and_persists_piece(
    tmp_path, make_engine_config, fake_embeddings_client
):
    gateway, _ = _gateway(tmp_path, make_engine_config, contents=["# Draft one", _STRONG_GRADE])
    piece = _piece()

    writer.produce(
        piece,
        _brief(),
        _project(),
        data_root=tmp_path / "data",
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        min_grade=8.0,
        max_attempts=3,
        grade_weights=make_engine_config().produce.grade_weights,
        voice=_voice_settings(fake_embeddings_client, tmp_path),
        now=NOW,
    )

    reloaded = store.read_piece(tmp_path / "data", piece.project, piece.id)
    assert reloaded.generated_at == NOW
    assert len(reloaded.grades) == 1


def test_produce_respects_no_cache_flag(tmp_path, make_engine_config, fake_embeddings_client):
    """`--no-cache` (TDD 9) must reach every gateway.complete() call, not
    just the first."""
    gateway, _ = _gateway(tmp_path, make_engine_config, contents=["# Draft one", _STRONG_GRADE])
    seen_cache_flags = []
    original_complete = gateway.complete

    def spy(*args, **kwargs):
        seen_cache_flags.append(kwargs.get("cache", True))
        return original_complete(*args, **kwargs)

    gateway.complete = spy

    writer.produce(
        _piece(),
        _brief(),
        _project(),
        data_root=tmp_path / "data",
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        min_grade=8.0,
        max_attempts=3,
        grade_weights=make_engine_config().produce.grade_weights,
        voice=_voice_settings(fake_embeddings_client, tmp_path),
        cache=False,
        now=NOW,
    )

    assert seen_cache_flags == [False, False]


# ---------------------------------------------------------------------------
# Evidence context — resolves cited refs to real source material (TDD 10.5:
# "cited evidence in full"; TDD 11: article_draft "receives raw + clean
# transcripts"), not just the brief-time note/quote MATCH condensed onto
# the evidence entry.
# ---------------------------------------------------------------------------

SHA = "a3f9c210" + "0" * 32
CAP_ID = "cap-20260716-1423"


def _capture_with_transcripts(data_root: Path, project_slug: str) -> Capture:
    project_dir = store.project_dir(data_root, project_slug)
    raw_path = project_dir / "captures" / "audio" / "raw" / f"{CAP_ID}.txt"
    clean_path = project_dir / "captures" / "audio" / "transcript" / f"{CAP_ID}.md"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("uh, it just, it died. no oom message either", encoding="utf-8")
    clean_path.write_text("It just died — no OOM message, no warning.", encoding="utf-8")
    return Capture(
        id=CAP_ID,
        project=project_slug,
        type=CaptureType.AUDIO,
        moment=CaptureMoment.IN_SITU,
        captured_at=NOW,
        source_path=Path("captures/audio/raw") / f"{CAP_ID}.m4a",
        derived=CaptureDerived(
            transcript_raw=Path("captures/audio/raw") / f"{CAP_ID}.txt",
            transcript_clean=Path("captures/audio/transcript") / f"{CAP_ID}.md",
        ),
    )


def _git_harvest_with_commit() -> GitHarvest:
    return GitHarvest(
        repos=[
            RepoHarvest(
                repo="thing",
                range="2026-05-01..2026-07-27",
                total_commits=1,
                kept=1,
                dropped=0,
                commits=[
                    CommitRecord(
                        sha=SHA,
                        at=NOW,
                        msg="fix: resolve the OOM when the join spills to disk",
                        files_changed=2,
                        insertions=10,
                        deletions=5,
                        score=3,
                        reasons=["war_story"],
                        summary="Fixed an out-of-memory crash during a large join.",
                    )
                ],
                redaction=RedactionSummary(scanned=10, findings=0),
            )
        ]
    )


def test_evidence_context_resolves_capture_ref_to_real_transcript(tmp_path):
    data_root = tmp_path / "data"
    project = _project()
    capture = _capture_with_transcripts(data_root, project.slug)
    store.write_capture(data_root, capture)
    brief = Brief(
        id="br-01",
        project=project.slug,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="t",
        angle="a",
        demand=BriefDemand(recurrence=0, signals=[]),
        evidence=[BriefEvidence(kind="audio", ref=CAP_ID, quote="a short paraphrase")],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.0,
        weakest_point="n=1",
    )

    context = writer.format_evidence_context(
        brief,
        data_root=data_root,
        project=project,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
    )

    assert "It just died — no OOM message, no warning." in context  # clean transcript
    assert "uh, it just, it died" in context  # raw transcript
    assert "a short paraphrase" not in context  # real transcript wins over the brief's quote


def test_evidence_context_resolves_commit_ref_to_git_json_summary(tmp_path):
    data_root = tmp_path / "data"
    project = _project()
    brief = Brief(
        id="br-01",
        project=project.slug,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="t",
        angle="a",
        demand=BriefDemand(recurrence=0, signals=[]),
        evidence=[BriefEvidence(kind="git", ref=SHA[:7], note="the fix")],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.0,
        weakest_point="n=1",
    )

    context = writer.format_evidence_context(
        brief,
        data_root=data_root,
        project=project,
        git_harvest=_git_harvest_with_commit(),
        research_harvest=_EMPTY_RESEARCH_HARVEST,
    )

    assert "Fixed an out-of-memory crash during a large join." in context


def test_evidence_context_resolves_research_ref_to_research_json_summary(tmp_path):
    data_root = tmp_path / "data"
    project = _project()
    url = "https://example.com/duckdb-vs-spark"
    research_harvest = ResearchHarvest(
        sources=[
            ResearchSource(
                url=url,
                title="DuckDB vs Spark",
                fetched_at=NOW,
                summary="Confirms DuckDB is competitive under 100GB.",
                stance=Stance.SUPPORTS,
            )
        ]
    )
    brief = Brief(
        id="br-01",
        project=project.slug,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="t",
        angle="a",
        demand=BriefDemand(recurrence=0, signals=[]),
        evidence=[BriefEvidence(kind="research", ref=url)],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.0,
        weakest_point="n=1",
    )

    context = writer.format_evidence_context(
        brief,
        data_root=data_root,
        project=project,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=research_harvest,
    )

    assert "Confirms DuckDB is competitive under 100GB." in context


def test_evidence_context_falls_back_to_quote_when_ref_no_longer_resolves(tmp_path):
    data_root = tmp_path / "data"
    project = _project()
    brief = Brief(
        id="br-01",
        project=project.slug,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="t",
        angle="a",
        demand=BriefDemand(recurrence=0, signals=[]),
        evidence=[BriefEvidence(kind="git", ref="deadbeef", quote="the original MATCH-time quote")],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.0,
        weakest_point="n=1",
    )

    context = writer.format_evidence_context(
        brief,
        data_root=data_root,
        project=project,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
    )

    assert "the original MATCH-time quote" in context


def test_evidence_context_empty_evidence_list(tmp_path):
    data_root = tmp_path / "data"
    project = _project()
    brief = _brief()
    brief.evidence = []

    context = writer.format_evidence_context(
        brief,
        data_root=data_root,
        project=project,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
    )

    assert context == "(no cited evidence)"


# ---------------------------------------------------------------------------
# Voice RAG — top-k chunks by cosine similarity (TDD 10.5)
# ---------------------------------------------------------------------------


def test_voice_rag_prefers_chunks_sharing_vocabulary_with_the_query(fake_embeddings_client):
    chunks = [
        "DuckDB choked on a forty gigabyte join and ran out of memory.",
        "My favorite pasta recipe uses fresh basil and pine nuts.",
        "The streaming ETL pipeline OOM'd during a large join operation.",
    ]
    top = writer._top_voice_chunks(
        chunks,
        "DuckDB OOM during a large join",
        embeddings_client=fake_embeddings_client,
        model="m",
        k=2,
    )
    assert len(top) == 2
    assert "pasta" not in " ".join(top)


def test_voice_chunks_reads_paragraphs_from_every_md_file(tmp_path):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "a.md").write_text(
        "First paragraph is long enough to count.\n\n"
        "Second paragraph is also long enough to clear the minimum-chars floor.",
        encoding="utf-8",
    )
    (voice_dir / "b.md").write_text("short", encoding="utf-8")  # below the min-chars floor

    chunks = writer._voice_chunks(voice_dir)

    assert len(chunks) == 2
    assert "short" not in chunks


def test_voice_chunks_missing_directory_returns_empty(tmp_path):
    assert writer._voice_chunks(tmp_path / "no-such-voice-dir") == []
