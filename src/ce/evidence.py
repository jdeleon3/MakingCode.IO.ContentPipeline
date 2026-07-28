"""Shared citation resolution: does an `evidence.ref` (a capture id or a
full/short commit SHA) name a real capture or commit, and if so, which one.

Used by two WP-09/WP-10 call sites that both need the *actual resolved
object*, not just a yes/no: `produce/writer.py` (to pull the real transcript/
commit summary into `article_draft`'s evidence context) and `gates/claims.py`
(to check a `grounded` claim's `ref` actually maps to something real, TDD
6.4). `harvest/inventory.py`'s citation-resolvability check (WP-08) is a
narrower, boolean-only version of the same idea built before this module
existed — left as its own thing rather than refactored onto this, since it
operates on raw not-yet-validated LLM JSON and touching already-closed WP-08
code isn't this WP's job.
"""

from __future__ import annotations

from ce.harvest.git import CommitRecord, GitHarvest
from ce.models import Capture


def resolve_capture_or_commit(
    ref: str, *, captures_by_id: dict[str, Capture], git_harvest: GitHarvest
) -> Capture | CommitRecord | None:
    """Matches `ref` (optionally `<id>@<timestamp>`) against known captures
    first, then commits by full or short (>=7 char) SHA prefix -- same
    short-SHA rule `harvest/inventory.py::_find_unresolvable_citations`
    uses to validate citations at MATCH time. `None` if neither resolves.
    """
    base_ref = ref.split("@", 1)[0]
    if base_ref in captures_by_id:
        return captures_by_id[base_ref]
    for repo in git_harvest.repos:
        for commit in repo.commits:
            if commit.sha == base_ref or (
                len(base_ref) >= 7 and commit.sha.lower().startswith(base_ref.lower())
            ):
                return commit
    return None
