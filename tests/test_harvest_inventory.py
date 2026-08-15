"""WP-08 acceptance (TDD 10.4, 12): the MATCH step.

A fixture project yields 6-8 briefs covering >=4 archetypes; every
evidence citation resolves to a real capture ID or commit SHA (an
unresolvable one triggers exactly one retry, then fails the run);
weakest_point is required and non-empty; weak/too-similar briefs are
force-dropped and refused by `assert_selectable`; inventory.md is
readable and ranked.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ce import index as index_module
from ce import store
from ce.exit_codes import InventoryError
from ce.harvest import inventory
from ce.harvest.git import CommitRecord, GitHarvest, RedactionSummary, RepoHarvest
from ce.harvest.research import ResearchHarvest, ResearchSource, Stance
from ce.llm.gateway import Gateway, ProviderResponse
from ce.models import (
    Brief,
    BriefDemand,
    BriefStatus,
    Capture,
    CaptureMoment,
    CaptureType,
    GroundingStrength,
    Piece,
    PieceStatus,
    Project,
    PublishableLevel,
    PublishedInfo,
    RepoRef,
    Selection,
)

SHA_A = "a3f9c21" + "0" * 33
SHA_B = "b7e2f88" + "1" * 33
CAP_1 = "cap-20260716-1423"
CAP_2 = "cap-20260717-0900"
NOW = datetime(2026, 7, 27, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _project(publishable: PublishableLevel = PublishableLevel.FULL) -> Project:
    return Project(
        slug="test-proj",
        title="Streaming ETL with DuckDB",
        started_at=date(2026, 7, 1),
        repos=[RepoRef(name="thing", path=Path("/tmp/thing"), publishable=publishable)],
        selection=Selection(
            hypothesis="DuckDB replaces Spark for <100GB workloads",
            expected_failure_surface="memory limits on joins",
            demand_signals=["HN 3 threads"],
        ),
        tags=["duckdb", "etl"],
    )


def _git_harvest() -> GitHarvest:
    return GitHarvest(
        repos=[
            RepoHarvest(
                repo="thing",
                range="2026-05-01..2026-07-27",
                total_commits=5,
                kept=2,
                dropped=3,
                commits=[
                    CommitRecord(
                        sha=SHA_A,
                        at=NOW,
                        msg="fix: resolve the OOM when the join spills to disk",
                        files_changed=2,
                        insertions=10,
                        deletions=5,
                        score=3,
                        reasons=["war_story"],
                        summary="Fixed an out-of-memory crash during a large join.",
                    ),
                    CommitRecord(
                        sha=SHA_B,
                        at=NOW,
                        msg="Revert the streaming join",
                        files_changed=1,
                        insertions=0,
                        deletions=340,
                        score=6,
                        reasons=["reversal", "reversal"],
                        summary="Reverted the streaming join after it proved unreliable.",
                    ),
                ],
                redaction=RedactionSummary(scanned=10, findings=0),
            )
        ]
    )


def _captures() -> list[Capture]:
    return [
        Capture(
            id=CAP_1,
            project="test-proj",
            type=CaptureType.AUDIO,
            moment=CaptureMoment.IN_SITU,
            captured_at=NOW,
            source_path=Path("captures/audio/raw/1.wav"),
            context="hit the OOM on the 40GB join",
        ),
        Capture(
            id=CAP_2,
            project="test-proj",
            type=CaptureType.FRICTION,
            moment=CaptureMoment.IN_SITU,
            captured_at=NOW,
            source_path=Path("captures/friction.md"),
            context="the spill-to-disk never triggered, it just died",
        ),
    ]


def _research_harvest() -> ResearchHarvest:
    return ResearchHarvest(
        sources=[
            ResearchSource(
                url="https://example.com/duckdb-vs-spark",
                title="DuckDB vs Spark for mid-size data",
                fetched_at=NOW,
                summary="Confirms DuckDB is competitive under 100GB.",
                stance=Stance.SUPPORTS,
            )
        ]
    )


def _brief_dict(
    archetype: str,
    title: str,
    angle: str,
    evidence_refs: list[str],
    *,
    grounding: str = "strong",
    weakest_point: str = "n=1, single workload shape",
) -> dict:
    return {
        "archetype": archetype,
        "title": title,
        "angle": angle,
        "target_platforms": ["site", "linkedin"],
        "demand": {"recurrence": 2, "signals": ["HN thread"]},
        "evidence": [
            {"kind": "git" if "@" not in ref else "audio", "ref": ref} for ref in evidence_refs
        ],
        "grounding_strength": grounding,
        "weakest_point": weakest_point,
        "risk_flags": [],
    }


def _six_valid_briefs() -> list[dict]:
    return [
        _brief_dict("why_this_project", "Why DuckDB, why now", "origin story", [f"{CAP_1}@00:10"]),
        _brief_dict(
            "build_walkthrough", "Building the streaming pipeline", "walkthrough", [SHA_A[:7]]
        ),
        _brief_dict(
            "what_went_wrong", "The OOM that took a day to find", "war story", [SHA_A[:7], CAP_1]
        ),
        _brief_dict("i_was_wrong", "I reverted my own join logic", "reversal", [SHA_B[:7]]),
        _brief_dict("tool_review", "DuckDB vs Spark, honestly", "review", [f"{CAP_1}@01:00"]),
        _brief_dict(
            "specific_gotcha", "The spill-to-disk gotcha", "gotcha", [CAP_2], grounding="weak"
        ),
    ]


class FakeLLMClient:
    def __init__(self, responses: list[list[dict]]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, model, system, user, max_tokens):
        self.calls.append({"model": model, "system": system, "user": user})
        payload = self._responses.pop(0)
        return ProviderResponse(content=json.dumps(payload), in_tokens=100, out_tokens=200)


def _gateway(
    tmp_path: Path, make_engine_config, responses: list[list[dict]]
) -> tuple[Gateway, FakeLLMClient]:
    client = FakeLLMClient(responses)
    gateway = Gateway(
        make_engine_config(),
        data_root=tmp_path / "data",
        prompts_dir=Path("prompts"),
        client=client,
    )
    return gateway, client


def _dedupe(
    tmp_path: Path, fake_embeddings_client, *, threshold: float = 0.88
) -> inventory.DedupeSettings:
    conn = index_module.connect(tmp_path / "index.db")
    return inventory.DedupeSettings(
        conn=conn,
        embeddings_client=fake_embeddings_client,
        embeddings_model="text-embedding-3-small",
        threshold=threshold,
        scope_days=365,
        now=NOW,
    )


def _generate(
    tmp_path,
    make_engine_config,
    fake_embeddings_client,
    responses,
    *,
    project=None,
    git_harvest=None,
    research_harvest=None,
    captures=None,
    min_briefs=6,
    max_briefs=8,
    dedupe_threshold=0.88,
    brand_brief_path=None,
):
    gateway, llm_client = _gateway(tmp_path, make_engine_config, responses)
    project = project or _project()
    briefs = inventory.generate(
        project,
        git_harvest or _git_harvest(),
        research_harvest or _research_harvest(),
        captures if captures is not None else _captures(),
        data_root=tmp_path / "data",
        gateway=gateway,
        dedupe=_dedupe(tmp_path, fake_embeddings_client, threshold=dedupe_threshold),
        min_briefs=min_briefs,
        max_briefs=max_briefs,
        brand_brief_path=brand_brief_path or (tmp_path / "no-brand-brief.md"),
    )
    return briefs, llm_client


# ---------------------------------------------------------------------------
# Done-when: 6-8 briefs covering >=4 archetypes
# ---------------------------------------------------------------------------


def test_generate_yields_six_to_eight_briefs_covering_four_archetypes(
    tmp_path, make_engine_config, fake_embeddings_client
):
    briefs, llm_client = _generate(
        tmp_path, make_engine_config, fake_embeddings_client, responses=[_six_valid_briefs()]
    )

    assert 6 <= len(briefs) <= 8
    assert len({b.archetype for b in briefs}) >= 4
    assert len(llm_client.calls) == 1  # no retry needed -- all citations were valid


def test_ids_and_project_are_assigned_by_code_not_trusted_to_the_model(
    tmp_path, make_engine_config, fake_embeddings_client
):
    briefs, _ = _generate(
        tmp_path, make_engine_config, fake_embeddings_client, responses=[_six_valid_briefs()]
    )
    assert [b.id for b in briefs] == [f"br-{i:02d}" for i in range(1, len(briefs) + 1)]
    assert all(b.project == "test-proj" for b in briefs)


# ---------------------------------------------------------------------------
# Citation resolvability + retry (TDD 10.4 hard constraint)
# ---------------------------------------------------------------------------


def test_unresolvable_citation_triggers_exactly_one_retry_then_succeeds(
    tmp_path, make_engine_config, fake_embeddings_client
):
    bad_briefs = _six_valid_briefs()
    bad_briefs[0]["evidence"] = [{"kind": "git", "ref": "not-a-real-sha-or-capture"}]
    good_briefs = _six_valid_briefs()

    briefs, llm_client = _generate(
        tmp_path,
        make_engine_config,
        fake_embeddings_client,
        responses=[bad_briefs, good_briefs],
    )

    assert len(llm_client.calls) == 2
    assert (
        "not-a-real-sha-or-capture" in llm_client.calls[1]["system"] + llm_client.calls[1]["user"]
    )
    assert 6 <= len(briefs) <= 8


def test_unresolvable_citation_still_bad_after_retry_raises(
    tmp_path, make_engine_config, fake_embeddings_client
):
    bad_briefs = _six_valid_briefs()
    bad_briefs[0]["evidence"] = [{"kind": "git", "ref": "still-not-real"}]

    with pytest.raises(InventoryError, match="still-not-real"):
        _generate(
            tmp_path,
            make_engine_config,
            fake_embeddings_client,
            responses=[bad_briefs, bad_briefs],
        )


def test_find_unresolvable_citations_accepts_capture_ids_and_sha_prefixes():
    briefs_data = [
        {"evidence": [{"kind": "audio", "ref": f"{CAP_1}@01:00"}]},
        {"evidence": [{"kind": "git", "ref": SHA_A[:7]}]},
        {"evidence": [{"kind": "git", "ref": "0000000"}]},
    ]
    unresolvable = inventory._find_unresolvable_citations(
        briefs_data, capture_ids={CAP_1}, commit_shas={SHA_A}
    )
    assert unresolvable == ["0000000"]


# ---------------------------------------------------------------------------
# weakest_point non-empty (model-layer enforcement)
# ---------------------------------------------------------------------------


def test_brief_model_rejects_blank_weakest_point():
    with pytest.raises(ValueError, match="weakest_point"):
        Brief(
            id="br-01",
            project="test-proj",
            archetype="why_this_project",
            title="x",
            angle="y",
            demand=BriefDemand(recurrence=1, signals=[]),
            grounding_strength=GroundingStrength.STRONG,
            dedupe_max_similarity=0.0,
            weakest_point="   ",
        )


# ---------------------------------------------------------------------------
# weak grounding -> dropped + refused
# ---------------------------------------------------------------------------


def test_weak_grounding_is_force_dropped(tmp_path, make_engine_config, fake_embeddings_client):
    briefs, _ = _generate(
        tmp_path, make_engine_config, fake_embeddings_client, responses=[_six_valid_briefs()]
    )
    weak_brief = next(b for b in briefs if b.archetype.value == "specific_gotcha")
    assert weak_brief.grounding_strength == GroundingStrength.WEAK
    assert weak_brief.status == BriefStatus.DROPPED


def test_assert_selectable_refuses_dropped_brief():
    dropped = Brief(
        id="br-01",
        project="test-proj",
        archetype="specific_gotcha",
        title="x",
        angle="y",
        demand=BriefDemand(recurrence=0, signals=[]),
        grounding_strength=GroundingStrength.WEAK,
        dedupe_max_similarity=0.0,
        weakest_point="thin evidence",
        status=BriefStatus.DROPPED,
    )
    with pytest.raises(InventoryError, match="br-01"):
        inventory.assert_selectable(dropped)


def test_assert_selectable_allows_candidate_brief():
    candidate = Brief(
        id="br-02",
        project="test-proj",
        archetype="why_this_project",
        title="x",
        angle="y",
        demand=BriefDemand(recurrence=0, signals=[]),
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.0,
        weakest_point="thin evidence",
        status=BriefStatus.CANDIDATE,
    )
    inventory.assert_selectable(candidate)  # must not raise


# ---------------------------------------------------------------------------
# Dedupe (G3) blocking during inventory generation
# ---------------------------------------------------------------------------


def test_brief_too_similar_to_published_piece_is_dropped_and_flagged(
    tmp_path, make_engine_config, fake_embeddings_client
):
    conn = index_module.connect(tmp_path / "index.db")
    published_piece = Piece(
        id="pc-0099",
        brief_id="br-old",
        project="other-proj",
        slug="pc-0099",
        status=PieceStatus.PUBLISHED,
        created_at=NOW,
        article_path=Path("article.md"),
        published=PublishedInfo(url="https://example.com/x", at=NOW),
    )
    embedding = fake_embeddings_client.embed(
        "Why DuckDB, why now\n\norigin story", model="text-embedding-3-small"
    )
    index_module.upsert(conn, published_piece, "other-proj", embedding, "text-embedding-3-small")
    conn.commit()
    conn.close()

    briefs, _ = _generate(
        tmp_path, make_engine_config, fake_embeddings_client, responses=[_six_valid_briefs()]
    )

    matched = next(b for b in briefs if b.title == "Why DuckDB, why now")
    assert matched.status == BriefStatus.DROPPED
    assert matched.dedupe_max_similarity >= 0.88
    assert any("pc-0099" in flag for flag in matched.risk_flags)


def test_dedupe_max_similarity_recorded_even_when_not_blocked(
    tmp_path, make_engine_config, fake_embeddings_client
):
    briefs, _ = _generate(
        tmp_path, make_engine_config, fake_embeddings_client, responses=[_six_valid_briefs()]
    )
    assert all(0.0 <= b.dedupe_max_similarity <= 1.0 for b in briefs)


# ---------------------------------------------------------------------------
# lessons-only redaction in the assembled git context
# ---------------------------------------------------------------------------


def test_lessons_only_repo_redacts_name_and_stats_from_git_context():
    git_harvest = _git_harvest()
    lessons_project = _project(publishable=PublishableLevel.LESSONS_ONLY)

    context = inventory._format_git_context(git_harvest, lessons_project)

    assert "thing" not in context
    assert "+10/-5" not in context
    assert "Fixed an out-of-memory crash during a large join." in context  # summary survives


def test_full_repo_includes_name_and_stats():
    context = inventory._format_git_context(_git_harvest(), _project())
    assert "Repo: thing" in context
    assert "+10/-5" in context


# ---------------------------------------------------------------------------
# NOTE captures — expanded in full, like an audio transcript
# ---------------------------------------------------------------------------


def test_note_capture_expands_full_text_into_captures_context(tmp_path):
    project_root = store.project_dir(tmp_path, "test-proj")
    note_path = project_root / "captures" / "notes" / "cap-note.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# Retrospective\n\nThe router misfired on ambiguous names.")

    capture = Capture(
        id="cap-note",
        project="test-proj",
        type=CaptureType.NOTE,
        moment=CaptureMoment.RETRO,
        captured_at=NOW,
        source_path=Path("captures/notes/cap-note.md"),
        derived={"transcript_clean": Path("captures/notes/cap-note.md")},
        context="first-week retrospective",
    )

    context = inventory._format_captures_context(tmp_path, _project(), [capture])

    assert "The router misfired on ambiguous names." in context
    assert "note, retro" in context


# ---------------------------------------------------------------------------
# inventory.md — readable + ranked
# ---------------------------------------------------------------------------


def test_inventory_md_is_written_readable_and_ranks_dropped_last(
    tmp_path, make_engine_config, fake_embeddings_client
):
    briefs, _ = _generate(
        tmp_path, make_engine_config, fake_embeddings_client, responses=[_six_valid_briefs()]
    )
    inventory_path = store.harvest_dir(tmp_path / "data", "test-proj") / "inventory.md"
    assert inventory_path.exists()
    text = inventory_path.read_text(encoding="utf-8")

    assert "Why DuckDB, why now" in text
    assert "weakest point" in text.lower()

    order = [line for line in text.splitlines() if line.startswith("## ")]
    dropped_titles = {b.title for b in briefs if b.status == BriefStatus.DROPPED}
    first_dropped_index = next(
        (i for i, line in enumerate(order) if line[3:] in dropped_titles), len(order)
    )
    kept_after_dropped = [
        line for line in order[first_dropped_index + 1 :] if line[3:] not in dropped_titles
    ]
    assert kept_after_dropped == []  # no non-dropped brief appears after the first dropped one


def test_briefs_yml_is_written(tmp_path, make_engine_config, fake_embeddings_client):
    _generate(tmp_path, make_engine_config, fake_embeddings_client, responses=[_six_valid_briefs()])
    reloaded = store.read_briefs(tmp_path / "data", "test-proj")
    assert len(reloaded) == 6


def _brief(
    title: str, *, recurrence: int, grounding: GroundingStrength, status: BriefStatus
) -> Brief:
    return Brief(
        id=title,
        project="test-proj",
        archetype="why_this_project",
        title=title,
        angle="angle",
        demand=BriefDemand(recurrence=recurrence, signals=[]),
        grounding_strength=grounding,
        dedupe_max_similarity=0.0,
        weakest_point="thin",
        status=status,
    )


def test_format_inventory_md_ranks_by_recurrence_then_grounding_then_dropped_last():
    """Isolates `_sort_key`'s tie-break logic directly (bypassing
    `generate()`'s weak/dedupe forcing), since the full-pipeline fixture
    used elsewhere in this file happens to give every brief the same
    recurrence -- this proves the recurrence and grounding-strength
    ordering actually work, not just the dropped-last rule."""
    high_recurrence_weak = _brief(
        "High recurrence, weak",
        recurrence=5,
        grounding=GroundingStrength.WEAK,
        status=BriefStatus.CANDIDATE,
    )
    mid_recurrence_strong = _brief(
        "Mid recurrence, strong",
        recurrence=3,
        grounding=GroundingStrength.STRONG,
        status=BriefStatus.CANDIDATE,
    )
    tied_recurrence_strong = _brief(
        "Tied recurrence, strong",
        recurrence=2,
        grounding=GroundingStrength.STRONG,
        status=BriefStatus.CANDIDATE,
    )
    tied_recurrence_weak = _brief(
        "Tied recurrence, weak",
        recurrence=2,
        grounding=GroundingStrength.WEAK,
        status=BriefStatus.CANDIDATE,
    )
    dropped_highest_recurrence = _brief(
        "Dropped despite highest recurrence",
        recurrence=10,
        grounding=GroundingStrength.STRONG,
        status=BriefStatus.DROPPED,
    )

    text = inventory.format_inventory_md(
        [
            dropped_highest_recurrence,
            tied_recurrence_weak,
            tied_recurrence_strong,
            mid_recurrence_strong,
            high_recurrence_weak,
        ]
    )
    titles = [line[3:] for line in text.splitlines() if line.startswith("## ")]

    assert titles == [
        "High recurrence, weak",  # recurrence 5 beats everything below on recurrence alone
        "Mid recurrence, strong",  # recurrence 3
        "Tied recurrence, strong",  # recurrence 2, strong beats weak on the tie-break
        "Tied recurrence, weak",  # recurrence 2, weak
        "Dropped despite highest recurrence",  # dropped always sorts last, recurrence irrelevant
    ]
