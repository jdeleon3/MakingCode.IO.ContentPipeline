"""WP-20 acceptance: `/projects/<slug>/briefs` lists candidate briefs with
archetype/demand/evidence/dedupe/risk-flag detail; a dropped/weak brief's
Select control is disabled in the UI itself, not just rejected after a
click; selecting a real candidate shells to the real `ce brief select`,
creates a `Piece`, and hands back its id; a dedupe collision is surfaced via
the same risk-flag text `harvest/inventory.py` writes at generation time,
naming the colliding piece.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ce import store  # noqa: E402
from ce.gui import runner  # noqa: E402
from ce.gui.app import create_app  # noqa: E402
from ce.models import (  # noqa: E402
    Brief,
    BriefArchetype,
    BriefDemand,
    BriefEvidence,
    BriefStatus,
    GroundingStrength,
    Project,
)

_MINIMAL_ENGINE_YML = """
identity:
  name: John
  site_url: https://example.com
  site_repo: ~/code/site
  timezone: America/New_York
repos:
  allowed: []
llm:
  provider: anthropic
  models: {reasoning: claude-opus-5, default: claude-sonnet-5, cheap: claude-haiku-4-5}
  budget: {monthly_usd: 20, per_run_usd: 2.0, on_exceed: halt}
  retry: {max_attempts: 4, backoff_base_sec: 2}
transcription:
  provider: openai
  model: gpt-4o-mini-transcribe
  vocabulary: []
  preprocess: {silence_threshold_db: -40, silence_min_sec: 1.5, loudnorm: true}
embeddings: {provider: openai, model: text-embedding-3-small}
gates:
  allowlist: hard_fail
  secrets: hard_fail
  dedupe: {threshold: 0.88, scope_days: 365}
  claims: {enabled: true, block_on_unverifiable: true}
produce:
  min_grade: 8.0
  max_attempts: 3
  grade_weights: {hook: 0.3, evidence: 0.3, specificity: 0.2, voice: 0.1, cta: 0.1}
harvest:
  git: {lookback_days: 60, min_significance: 2}
  research: {max_sources: 8}
  inventory: {min_briefs: 6, max_briefs: 8}
utm:
  template: "?utm_source={platform}&utm_medium=social&utm_campaign={slug}"
analytics:
  umami: {api_url: "https://umami.example.com", website_id: "site-1"}
sweep:
  topics: [DuckDB]
  rss_feeds: []
"""


def _write_minimal_engine_config(root: Path) -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "engine.yml").write_text(_MINIMAL_ENGINE_YML, encoding="utf-8")


def _project(slug: str) -> Project:
    return Project(slug=slug, title=f"Title for {slug}", started_at=date(2026, 7, 1))


def _brief(
    brief_id: str,
    *,
    status: BriefStatus = BriefStatus.CANDIDATE,
    risk_flags: list[str] | None = None,
    dedupe_max_similarity: float = 0.1,
    recurrence: int = 2,
) -> Brief:
    return Brief(
        id=brief_id,
        project="proj",
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title=f"Brief {brief_id}",
        angle="counter-position",
        demand=BriefDemand(recurrence=recurrence, signals=["hn:duckdb"]),
        evidence=[BriefEvidence(kind="git", ref="abc1234")],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=dedupe_max_similarity,
        weakest_point="n=1",
        status=status,
        risk_flags=risk_flags or [],
    )


@pytest.fixture(autouse=True)
def _clean_run_registry():
    runner._runs.clear()
    yield
    runner._runs.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


def test_briefs_page_lists_archetype_demand_evidence_and_dedupe(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_briefs(data_root, "proj", [_brief("br-01", recurrence=3)])

    resp = client.get("/projects/proj/briefs")

    assert resp.status_code == 200
    assert "Brief br-01" in resp.text
    assert "what_went_wrong" in resp.text
    assert "recurrence 3" in resp.text
    assert "1 citation(s)" in resp.text
    assert "strong" in resp.text
    assert "0.10" in resp.text


def test_dropped_brief_select_control_is_disabled_in_the_ui(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_briefs(
        data_root,
        "proj",
        [
            _brief("br-01", status=BriefStatus.CANDIDATE),
            _brief(
                "br-02",
                status=BriefStatus.DROPPED,
                risk_flags=["duplicate of 'pc-0001' (similarity 0.95)"],
            ),
        ],
    )

    resp = client.get("/projects/proj/briefs")

    assert resp.status_code == 200
    # The colliding piece is named right in the rendered risk flag text --
    # matching what `assert_selectable`'s InventoryError points the operator
    # at ("see risk_flags") rather than a generic "duplicate" label. Jinja2
    # autoescapes the single quotes around the piece id (`'` -> `&#39;`).
    assert "pc-0001" in resp.text
    assert "similarity 0.95" in resp.text

    br01_pos = resp.text.index("br-01")
    br02_pos = resp.text.index('data-brief-id="br-02"')
    btn_br01 = resp.text[resp.text.index('data-brief-id="br-01"') : br02_pos]
    btn_br02 = resp.text[br02_pos : br02_pos + 200]
    assert "disabled" not in btn_br01
    assert "disabled" in btn_br02
    assert br01_pos >= 0


def test_selecting_a_candidate_creates_a_piece_and_returns_its_id(client, tmp_path):
    _write_minimal_engine_config(tmp_path)
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.scaffold_project_tree(data_root, "proj")
    store.write_briefs(data_root, "proj", [_brief("br-01")])

    resp = client.post("/projects/proj/briefs/br-01/select")

    assert resp.status_code == 200
    piece_id = resp.json()["piece_id"]
    assert piece_id.startswith("pc-")

    pieces = store.list_pieces(data_root, "proj")
    assert len(pieces) == 1
    assert pieces[0].id == piece_id
    assert pieces[0].brief_id == "br-01"

    briefs = store.read_briefs(data_root, "proj")
    assert briefs[0].status == BriefStatus.SELECTED


def test_selecting_a_dropped_brief_is_rejected_without_running_a_subprocess(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))
    store.write_briefs(
        data_root,
        "proj",
        [_brief("br-01", status=BriefStatus.DROPPED, risk_flags=["duplicate of 'pc-9999'"])],
    )

    resp = client.post("/projects/proj/briefs/br-01/select")

    assert resp.status_code == 400
    assert "dropped" in resp.json()["detail"].lower()
    assert not runner._runs
    assert store.list_pieces(data_root, "proj") == []


def test_selecting_an_unknown_brief_is_404(client):
    data_root = Path("data")
    store.write_project(data_root, _project("proj"))

    resp = client.post("/projects/proj/briefs/does-not-exist/select")

    assert resp.status_code == 404


def test_briefs_page_404s_for_a_project_not_on_disk(client):
    resp = client.get("/projects/does-not-exist/briefs")

    assert resp.status_code == 404
