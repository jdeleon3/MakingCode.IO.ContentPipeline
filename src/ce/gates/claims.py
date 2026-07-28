"""G4 — claim verification (TDD 6.4; blocking, bypassable with `--force`,
unlike G1/G2).

After a piece is drafted, extract every discrete factual assertion from
`article.md` and verify each one per its class:

- `grounded` — its `ref` (a capture id or commit SHA) must resolve to a
  real capture/commit in this project's harvest (`ce.evidence`, same
  resolver `produce/writer.py` uses to build the evidence context
  `claim_extract` reads from in the first place).
- `external` — verified by search + fetch, reusing WP-07's
  `SearchClient`/`FetchClient` Protocols and the already-built
  `research_stance` prompt (no new "verify against a fetched source"
  prompt needed — stance classification *is* claim-vs-source verification).
  Passes only if some fetched source's stance is `supports`.
- `opinion` — never verified (TDD 6.4: "no verification"). Trusted to
  `claim_extract`'s own classification, which is instructed to only use
  this class when a claim is linguistically marked as opinion — there's no
  independent mechanical check for "is this phrased as an opinion" beyond
  the extraction prompt's own judgment.
- `unverifiable` — always fails. Whether that failure actually *blocks*
  the gate is `config.gates.claims.block_on_unverifiable` (`check()`);
  `grounded`/`external` failures block unconditionally — TDD 6.4 offers no
  toggle for those.

`verify()` never raises — it always returns full per-claim detail (written
to `verification.json` regardless of outcome, so the operator can see what
failed). `check()` is the separate enforcement step that raises
`GateBlocked`, mirroring `gates/dedupe.py`'s `max_similarity()`/`check()`
split.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ce import store
from ce.evidence import resolve_capture_or_commit
from ce.exit_codes import GateBlocked
from ce.harvest.git import GitHarvest
from ce.harvest.research import FetchClient, ResearchHarvest, SearchClient
from ce.llm.gateway import Gateway
from ce.models import Brief, Project
from ce.produce.writer import format_evidence_context

_FETCHED_CONTENT_CHARS = 4000
_EXTERNAL_SEARCH_RESULTS = 3


class ClaimClass(StrEnum):
    GROUNDED = "grounded"
    EXTERNAL = "external"
    OPINION = "opinion"
    UNVERIFIABLE = "unverifiable"


class ClaimVerification(BaseModel):
    text: str
    claim_class: ClaimClass
    ref: str | None = None
    source_url: str | None = None
    passed: bool
    reason: str


class VerificationResult(BaseModel):
    claims: list[ClaimVerification] = Field(default_factory=list)

    def failed(self, *, block_on_unverifiable: bool) -> list[ClaimVerification]:
        return [
            c
            for c in self.claims
            if not c.passed and (block_on_unverifiable or c.claim_class != ClaimClass.UNVERIFIABLE)
        ]


# ---------------------------------------------------------------------------
# Per-class verification
# ---------------------------------------------------------------------------


def _verify_grounded(
    ref: str | None, *, captures_by_id: dict[str, Any], git_harvest: GitHarvest
) -> tuple[bool, str]:
    if not ref:
        return False, "classified grounded but no ref was given"
    resolved = resolve_capture_or_commit(
        ref, captures_by_id=captures_by_id, git_harvest=git_harvest
    )
    if resolved is None:
        return False, f"ref {ref!r} does not resolve to any known capture or commit"
    return True, f"resolves to {ref!r}"


def _load_research_stance_schema(prompts_dir: Path) -> dict[str, Any]:
    schema_path = prompts_dir / "_schemas" / "research_stance.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _verify_external(
    text: str,
    *,
    gateway: Gateway,
    search_client: SearchClient,
    fetch_client: FetchClient,
) -> tuple[bool, str | None, str]:
    """Searches for `text`, fetches each hit in rank order, and classifies
    the fetched page's stance toward the claim via the existing
    `research_stance` prompt (WP-07) — a source whose stance is `supports`
    counts as verification; the first one found wins.
    """
    schema = _load_research_stance_schema(gateway.prompts_dir)
    for hit in search_client.search(text, max_results=_EXTERNAL_SEARCH_RESULTS):
        content = fetch_client.fetch(hit.url)
        if not content or not content.strip():
            continue
        stance_result = gateway.complete(
            "research_stance",
            {
                "hypothesis": text,
                "title": hit.title,
                "url": hit.url,
                "content": content[:_FETCHED_CONTENT_CHARS],
            },
            schema=schema,
            tier="cheap",
        )
        if stance_result.parsed["stance"] == "supports":
            return True, hit.url, f"supported by {hit.url}"
    return False, None, "no fetched source supports this claim"


# ---------------------------------------------------------------------------
# verify() — extract + classify + verify every claim (never raises)
# ---------------------------------------------------------------------------


def _load_claims_schema(prompts_dir: Path) -> dict[str, Any]:
    schema_path = prompts_dir / "_schemas" / "claims.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def verify(
    article: str,
    brief: Brief,
    project: Project,
    *,
    data_root: Path,
    gateway: Gateway,
    git_harvest: GitHarvest,
    research_harvest: ResearchHarvest,
    search_client: SearchClient,
    fetch_client: FetchClient,
) -> VerificationResult:
    """Extracts and verifies every factual claim in `article` (TDD 6.4).
    `evidence_context` is rebuilt the same way `produce()` built it for
    drafting — `claim_extract` needs to see the same cited material to
    correctly attribute a `grounded` claim's `ref`.
    """
    evidence_context = format_evidence_context(
        brief,
        data_root=data_root,
        project=project,
        git_harvest=git_harvest,
        research_harvest=research_harvest,
    )
    schema = _load_claims_schema(gateway.prompts_dir)
    result = gateway.complete(
        "claim_extract",
        {"article": article, "evidence_context": evidence_context},
        schema=schema,
        tier="default",
    )

    captures_by_id = {c.id: c for c in store.list_captures(data_root, project.slug)}

    claims: list[ClaimVerification] = []
    for claim_data in result.parsed["claims"]:
        cls = ClaimClass(claim_data["class"])
        text = claim_data["text"]
        ref = claim_data.get("ref")

        if cls == ClaimClass.GROUNDED:
            passed, reason = _verify_grounded(
                ref, captures_by_id=captures_by_id, git_harvest=git_harvest
            )
            claims.append(
                ClaimVerification(text=text, claim_class=cls, ref=ref, passed=passed, reason=reason)
            )
        elif cls == ClaimClass.EXTERNAL:
            passed, source_url, reason = _verify_external(
                text, gateway=gateway, search_client=search_client, fetch_client=fetch_client
            )
            claims.append(
                ClaimVerification(
                    text=text,
                    claim_class=cls,
                    source_url=source_url,
                    passed=passed,
                    reason=reason,
                )
            )
        elif cls == ClaimClass.OPINION:
            claims.append(
                ClaimVerification(
                    text=text, claim_class=cls, passed=True, reason="opinion -- not verified"
                )
            )
        else:
            claims.append(
                ClaimVerification(
                    text=text,
                    claim_class=cls,
                    passed=False,
                    reason="classified unverifiable by claim_extract",
                )
            )

    return VerificationResult(claims=claims)


def check(result: VerificationResult, *, block_on_unverifiable: bool = True) -> None:
    """Raises `GateBlocked` (exit 2) naming every failing claim, unless
    `--force` is handled by the caller (same shape as G3's `dedupe.check()`
    -- this function always enforces; callers decide whether to call it).
    """
    failed = result.failed(block_on_unverifiable=block_on_unverifiable)
    if not failed:
        return
    names = "; ".join(f"[{c.claim_class.value}] {c.text!r} ({c.reason})" for c in failed)
    raise GateBlocked("G4", f"{len(failed)} claim(s) failed verification: {names}")


# ---------------------------------------------------------------------------
# verification.json — full per-claim detail (written regardless of outcome)
# ---------------------------------------------------------------------------


def write_verification_json(path: Path, result: VerificationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
