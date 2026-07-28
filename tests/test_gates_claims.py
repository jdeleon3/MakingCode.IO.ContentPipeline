"""WP-10 acceptance (TDD 6.4, 12): G4 claim verification.

Done-when: a fixture article with one planted unverifiable claim exits 2
naming that claim; `grounded` claims not mapping to a real capture/commit
fail; `verification.json` written.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ce import store
from ce.exit_codes import GateBlocked
from ce.gates import claims as claims_module
from ce.harvest.git import GitHarvest
from ce.harvest.research import ResearchHarvest, SearchResult
from ce.llm.gateway import Gateway, ProviderResponse
from ce.models import (
    Brief,
    BriefArchetype,
    BriefDemand,
    BriefEvidence,
    Capture,
    CaptureMoment,
    CaptureType,
    GroundingStrength,
    Project,
    PublishableLevel,
    RepoRef,
)

NOW = datetime(2026, 7, 28, tzinfo=UTC)
CAP_ID = "cap-20260716-1423"

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


def _brief(project: str = "test-proj") -> Brief:
    return Brief(
        id="br-01",
        project=project,
        archetype=BriefArchetype.WHAT_WENT_WRONG,
        title="DuckDB's memory limit is not what the docs imply",
        angle="counter-position",
        demand=BriefDemand(recurrence=3, signals=["HN thread"]),
        evidence=[BriefEvidence(kind="audio", ref=CAP_ID, quote="it just died")],
        grounding_strength=GroundingStrength.STRONG,
        dedupe_max_similarity=0.31,
        weakest_point="n=1, single workload shape, 40GB",
    )


def _capture(project_slug: str) -> Capture:
    return Capture(
        id=CAP_ID,
        project=project_slug,
        type=CaptureType.AUDIO,
        moment=CaptureMoment.IN_SITU,
        captured_at=NOW,
        source_path=Path("captures/audio/raw") / f"{CAP_ID}.m4a",
    )


class FakeLLMClient:
    """Returns each response in `contents`, in call order, verbatim."""

    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.calls: list[dict] = []

    def complete(self, *, model, system, user, max_tokens):
        self.calls.append({"model": model, "system": system, "user": user})
        return ProviderResponse(content=self._contents.pop(0), in_tokens=50, out_tokens=100)


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


def _claims_json(claims: list[dict]) -> str:
    return json.dumps({"claims": claims})


def _stance_json(stance: str) -> str:
    return json.dumps({"stance": stance, "summary": "a summary"})


class FakeSearchClient:
    def __init__(self, results: list[SearchResult]):
        self._results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        return self._results[:max_results]


class FakeFetchClient:
    def __init__(self, content_by_url: dict[str, str | None]):
        self._content = content_by_url
        self.calls: list[str] = []

    def fetch(self, url: str) -> str | None:
        self.calls.append(url)
        return self._content.get(url)


# ---------------------------------------------------------------------------
# verify() — per-class behavior
# ---------------------------------------------------------------------------


def test_grounded_claim_resolves_to_a_real_capture(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project = _project()
    store.write_capture(data_root, _capture(project.slug))
    gateway, _ = _gateway(
        tmp_path,
        make_engine_config,
        contents=[_claims_json([{"text": "It just died.", "class": "grounded", "ref": CAP_ID}])],
    )

    result = claims_module.verify(
        "It just died.",
        _brief(),
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        search_client=FakeSearchClient([]),
        fetch_client=FakeFetchClient({}),
    )

    [claim] = result.claims
    assert claim.passed
    assert claim.claim_class == claims_module.ClaimClass.GROUNDED


def test_grounded_claim_with_unresolvable_ref_fails(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project = _project()
    gateway, _ = _gateway(
        tmp_path,
        make_engine_config,
        contents=[
            _claims_json(
                [{"text": "It ran in 3ms.", "class": "grounded", "ref": "cap-does-not-exist"}]
            )
        ],
    )

    result = claims_module.verify(
        "It ran in 3ms.",
        _brief(),
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        search_client=FakeSearchClient([]),
        fetch_client=FakeFetchClient({}),
    )

    [claim] = result.claims
    assert not claim.passed
    assert "does not resolve" in claim.reason


def test_external_claim_passes_when_a_fetched_source_supports(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project = _project()
    gateway, llm_client = _gateway(
        tmp_path,
        make_engine_config,
        contents=[
            _claims_json([{"text": "DuckDB is columnar.", "class": "external", "ref": None}]),
            _stance_json("supports"),
        ],
    )
    search_client = FakeSearchClient([SearchResult(url="https://x.test/1", title="DuckDB docs")])
    fetch_client = FakeFetchClient({"https://x.test/1": "DuckDB stores data in columns."})

    result = claims_module.verify(
        "DuckDB is columnar.",
        _brief(),
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    [claim] = result.claims
    assert claim.passed
    assert claim.source_url == "https://x.test/1"
    assert len(llm_client.calls) == 2  # claim_extract + research_stance


def test_external_claim_fails_when_no_source_supports(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project = _project()
    gateway, _ = _gateway(
        tmp_path,
        make_engine_config,
        contents=[
            _claims_json([{"text": "DuckDB invented SQL.", "class": "external", "ref": None}]),
            _stance_json("contradicts"),
        ],
    )
    search_client = FakeSearchClient([SearchResult(url="https://x.test/1", title="History of SQL")])
    fetch_client = FakeFetchClient({"https://x.test/1": "SQL predates DuckDB by decades."})

    result = claims_module.verify(
        "DuckDB invented SQL.",
        _brief(),
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    [claim] = result.claims
    assert not claim.passed
    assert claim.source_url is None


def test_opinion_claim_always_passes_unverified(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project = _project()
    gateway, _ = _gateway(
        tmp_path,
        make_engine_config,
        contents=[
            _claims_json([{"text": "I think DuckDB is great.", "class": "opinion", "ref": None}])
        ],
    )

    result = claims_module.verify(
        "I think DuckDB is great.",
        _brief(),
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        search_client=FakeSearchClient([]),
        fetch_client=FakeFetchClient({}),
    )

    [claim] = result.claims
    assert claim.passed
    assert claim.claim_class == claims_module.ClaimClass.OPINION


def test_unverifiable_claim_always_fails(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    project = _project()
    gateway, _ = _gateway(
        tmp_path,
        make_engine_config,
        contents=[
            _claims_json(
                [{"text": "This saved us $2M a year.", "class": "unverifiable", "ref": None}]
            )
        ],
    )

    result = claims_module.verify(
        "This saved us $2M a year.",
        _brief(),
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=_EMPTY_GIT_HARVEST,
        research_harvest=_EMPTY_RESEARCH_HARVEST,
        search_client=FakeSearchClient([]),
        fetch_client=FakeFetchClient({}),
    )

    [claim] = result.claims
    assert not claim.passed
    assert claim.claim_class == claims_module.ClaimClass.UNVERIFIABLE


# ---------------------------------------------------------------------------
# check() — blocking (TDD 6.4 / 12 Done-when: exits 2 naming the claim)
# ---------------------------------------------------------------------------


def test_check_raises_gate_blocked_naming_the_failed_claim():
    result = claims_module.VerificationResult(
        claims=[
            claims_module.ClaimVerification(
                text="This saved us $2M a year.",
                claim_class=claims_module.ClaimClass.UNVERIFIABLE,
                passed=False,
                reason="classified unverifiable by claim_extract",
            )
        ]
    )

    with pytest.raises(GateBlocked) as excinfo:
        claims_module.check(result)

    assert excinfo.value.exit_code == 2
    assert "This saved us $2M a year." in excinfo.value.message


def test_check_passes_when_every_claim_passes():
    result = claims_module.VerificationResult(
        claims=[
            claims_module.ClaimVerification(
                text="ok",
                claim_class=claims_module.ClaimClass.OPINION,
                passed=True,
                reason="opinion",
            )
        ]
    )
    claims_module.check(result)  # must not raise


def test_check_respects_block_on_unverifiable_false():
    result = claims_module.VerificationResult(
        claims=[
            claims_module.ClaimVerification(
                text="unverifiable claim",
                claim_class=claims_module.ClaimClass.UNVERIFIABLE,
                passed=False,
                reason="classified unverifiable by claim_extract",
            )
        ]
    )
    claims_module.check(result, block_on_unverifiable=False)  # must not raise


def test_check_still_blocks_on_a_failed_grounded_claim_even_with_block_on_unverifiable_false():
    result = claims_module.VerificationResult(
        claims=[
            claims_module.ClaimVerification(
                text="bad ref",
                claim_class=claims_module.ClaimClass.GROUNDED,
                passed=False,
                reason="ref does not resolve",
            )
        ]
    )
    with pytest.raises(GateBlocked):
        claims_module.check(result, block_on_unverifiable=False)


# ---------------------------------------------------------------------------
# verification.json
# ---------------------------------------------------------------------------


def test_write_verification_json_writes_full_detail(tmp_path):
    result = claims_module.VerificationResult(
        claims=[
            claims_module.ClaimVerification(
                text="It just died.",
                claim_class=claims_module.ClaimClass.GROUNDED,
                ref=CAP_ID,
                passed=True,
                reason=f"resolves to {CAP_ID!r}",
            )
        ]
    )
    path = tmp_path / "verification.json"

    claims_module.write_verification_json(path, result)

    data = json.loads(path.read_text(encoding="utf-8"))
    [claim] = data["claims"]
    assert claim["text"] == "It just died."
    assert claim["claim_class"] == "grounded"
    assert claim["passed"] is True
