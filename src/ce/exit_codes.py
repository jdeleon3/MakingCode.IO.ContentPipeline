"""Process exit codes and the exception hierarchy that maps onto them.

Contract (TDD 9):
    0  OK
    1  Unexpected error
    2  Gate blocked (message names the gate)
    3  Budget exceeded
    4  Precondition unmet (e.g. article not edited)

Every command must exit with one of these. `cli.main` translates a raised
`CEError` into its `exit_code`; anything else surfaces as 1.
"""

from __future__ import annotations

from enum import IntEnum


class Exit(IntEnum):
    OK = 0
    ERROR = 1
    GATE_BLOCKED = 2
    BUDGET_EXCEEDED = 3
    PRECONDITION = 4


class CEError(Exception):
    """Base for all deliberate Content Engine failures."""

    exit_code: Exit = Exit.ERROR

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class GateBlocked(CEError):
    """A safety gate refused to let the run continue.

    ADR-005: gates fail closed. G1 (allowlist) and G2 (secrets) are not
    bypassable by --force; that restriction is enforced at the gate, not here.
    """

    exit_code = Exit.GATE_BLOCKED

    def __init__(self, gate: str, message: str, *, hint: str | None = None) -> None:
        super().__init__(f"[{gate}] {message}", hint=hint)
        self.gate = gate


class BudgetExceeded(CEError):
    """Month-to-date or per-run LLM spend would exceed the configured cap."""

    exit_code = Exit.BUDGET_EXCEEDED


class PreconditionUnmet(CEError):
    """A required prior step has not happened.

    Example (ADR-008): `ce publish site` when article.md has not been edited
    since it was generated.
    """

    exit_code = Exit.PRECONDITION


class ConfigError(CEError):
    """`engine.yml`, a platform config, or a stored entity failed validation.

    Wraps the underlying `pydantic.ValidationError` message, which already
    names the offending field — this class exists so callers can catch one
    `CEError` type instead of also importing pydantic's exception.
    """

    exit_code = Exit.ERROR


class PromptError(CEError):
    """A `prompts/<id>.md` file failed to load or render (TDD 10.1, ADR-004).

    Covers missing files, malformed frontmatter, and Jinja2 `StrictUndefined`
    errors — a template referencing a var the caller didn't supply is a bug
    in the caller, not a silently blank section sent to a paid API call.
    """

    exit_code = Exit.ERROR


class SchemaValidationError(CEError):
    """An LLM response failed `output_schema` validation after one repair
    attempt (TDD 10.1 step 6).

    The gateway always retries once with the validation error appended
    before raising this — by the time it's raised, a retry already happened.
    """

    exit_code = Exit.ERROR


class CaptureError(CEError):
    """A capture/transcription step failed (TDD 10.2): a missing binary, a
    failed subprocess, an unreachable transcription API, or an unsupported
    input file.
    """

    exit_code = Exit.ERROR


class HarvestError(CEError):
    """A git harvest step failed (TDD 10.3) for a reason other than a gate
    blocking the run: `git log` itself failed, the path isn't a git repo, etc.
    """

    exit_code = Exit.ERROR


class IndexingError(CEError):
    """`ce index rebuild` (TDD 10, ADR-002/003) failed for a reason other
    than a gate blocking a run: a missing embeddings API key, an
    unreachable embeddings endpoint, or a corrupt `index.db`.
    """

    exit_code = Exit.ERROR


class ResearchError(CEError):
    """`harvest/research.py` (TDD 12 WP-07) failed for a reason other than
    a gate blocking the run: a missing search-provider API key, or an
    unknown `config.harvest.research.provider` value.
    """

    exit_code = Exit.ERROR


class InventoryError(CEError):
    """`harvest/inventory.py` (TDD 10.4/12 WP-08, the MATCH step) failed
    for a reason other than a gate blocking the run: `brief_generate`
    still cited an unresolvable capture/commit after one retry, or
    something in a candidate `Brief`'s selection was refused.
    """

    exit_code = Exit.ERROR


class AssetError(CEError):
    """`assets/*` (TDD 10.7, 12 WP-11) failed: a missing `mermaid-cli`/
    Playwright binary, a failed render subprocess, or an unknown `--only`
    kind. Mirrors `CaptureError`'s "missing binary produces a clear error,
    not a stack trace" shape (WP-04's `ffmpeg` check) — WP-11's own
    Done-when line asks for the identical behavior for `mermaid-cli`.
    """

    exit_code = Exit.ERROR


class RenditionError(CEError):
    """`produce/renditions.py` (TDD 10.6, 12 WP-12) failed: a platform's
    generated copy still violates one of §10.6's mechanical validations
    after the one allowed regeneration attempt. Mirrors `AssetError`'s
    "missing binary produces a clear error" shape, but for a mechanical
    validation failure instead of a missing dependency.
    """

    exit_code = Exit.ERROR


class PublishError(CEError):
    """`publish/site.py` (TDD 10.9, 12 WP-14) failed for a reason other than
    a precondition gate: `git add`/`commit`/`push` to `identity.site_repo`
    failed, the canonical URL never returned 200 within the poll window, or
    the built page is missing/empty `og:title`/`og:description`/`og:image`
    once it did.
    """

    exit_code = Exit.ERROR


class NotImplementedYet(CEError, NotImplementedError):
    """Command exists in the CLI contract but its work package is not built.

    Carries the WP id so the message tells you exactly where to look in the
    TDD rather than dumping a traceback. Also a real `NotImplementedError`,
    so `except NotImplementedError` and `pytest.raises(NotImplementedError)`
    both behave as you would expect.
    """

    exit_code = Exit.ERROR

    def __init__(self, command: str, wp: str) -> None:
        super().__init__(
            f"`ce {command}` is not implemented yet.",
            hint=f"Implemented by {wp}. See TDD-content-engine.md 12 and STATUS.md.",
        )
        self.command = command
        self.wp = wp
