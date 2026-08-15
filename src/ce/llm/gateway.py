"""LLM gateway (TDD 10.1): cached, budgeted, schema-validated calls to the
configured provider.

Deviation from the TDD's pseudocode signature: `complete(prompt_id, vars,
...)` is shown there as a bare function with no config/paths, but every
other module in this codebase (`store.py`, `config.py`) is explicit-args,
no hidden globals. Wrapped in a `Gateway` class instead — it carries
config/paths once at construction and holds the per-run spend accumulator
the budget governor needs (TDD 6.5 "per-run cap likewise"), which a bare
function would otherwise need a module-level global for.

Provider calls go through `AnthropicClient`, built on the official
`anthropic` SDK — a reversal of WP-02's original "hand-rolled httpx POST,
not worth the SDK dependency" call. Two things changed that judgment: a
production `ReadTimeout` on a large reasoning-tier `brief_generate` call
(raw httpx has no defense against this beyond "raise the number and hope"),
and an explicit decision to prefer official SDKs when a provider has one.
The SDK call streams (`messages.stream()` + `get_final_message()`) rather
than a plain synchronous POST — Anthropic's own guidance is that streaming
sidesteps the timeout risk structurally: a read timeout is per-chunk, so
periodic bytes keep the connection alive regardless of total generation
time, where a non-streaming call blocks with zero bytes until the entire
response is ready server-side. `Gateway` still takes any `LLMClient` via
dependency injection, which is what lets tests run against a fake client
with zero network calls instead of a pre-primed cache-file fixture.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import anthropic
import jsonschema
from pydantic import BaseModel

from ce.config import EngineConfig
from ce.exit_codes import BudgetExceeded, PromptError, SchemaValidationError
from ce.llm import cache as cache_store
from ce.llm import ledger
from ce.llm.prompts import load_prompt, render_prompt

# USD per 1M tokens (input, output). Source: Anthropic pricing, 2026-07.
# claude-sonnet-5 uses its standard post-intro rate ($3/$15), not the
# $2/$10 promo running through 2026-08-31 — so the budget governor doesn't
# undercount spend once that promo ends.
PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

DEFAULT_MAX_TOKENS = 8192
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _strip_code_fence(content: str) -> str:
    """Every schema-validated prompt in this codebase funnels through this
    one `json.loads` call (`Gateway._try_validate`) -- models occasionally
    wrap an otherwise-correct JSON response in a ```/```json markdown fence
    despite being told "JSON only, no other text", which previously failed
    parsing at char 0 (the backtick) with no retry. Stripped here rather
    than fixed per-prompt so every schema call gets the tolerance at once.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


def estimate_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    try:
        in_rate, out_rate = PRICING_PER_MILLION[model]
    except KeyError as exc:
        raise PromptError(f"no pricing configured for model {model!r}") from exc
    return (in_tokens / 1_000_000) * in_rate + (out_tokens / 1_000_000) * out_rate


class LLMResult(BaseModel):
    content: str
    parsed: Any | None = None
    model: str
    prompt_version: int
    in_tokens: int
    out_tokens: int
    usd: float
    cache_hit: bool


@dataclass
class ProviderResponse:
    content: str
    in_tokens: int
    out_tokens: int


class LLMClient(Protocol):
    def complete(
        self, *, model: str, system: str, user: str, max_tokens: int
    ) -> ProviderResponse: ...


class AnthropicClient:
    """Official `anthropic` SDK, called via `messages.stream()` rather than
    a plain `.create()` — see the module docstring for why streaming is the
    real fix for the timeout failure mode, not just a bigger number.

    The API-key check stays lazy (on `complete()`, not `__init__`) to match
    every other client in this codebase (`OpenAITranscriptionClient`,
    `OpenAIEmbeddingsClient`) — `Gateway.__init__` constructs this
    unconditionally, so checking eagerly would make constructing a `Gateway`
    fail before any command that doesn't end up calling the LLM gets a
    chance to run.
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client: anthropic.Anthropic | None = None

    def _get_client(self) -> anthropic.Anthropic:
        if not self._api_key:
            raise PromptError("ANTHROPIC_API_KEY is not set", hint="ce doctor")
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(self, *, model: str, system: str, user: str, max_tokens: int) -> ProviderResponse:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            kwargs["system"] = system

        with client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()

        text = "".join(block.text for block in message.content if block.type == "text")
        return ProviderResponse(
            content=text,
            in_tokens=message.usage.input_tokens,
            out_tokens=message.usage.output_tokens,
        )


class Gateway:
    """One instance per `ce` invocation. `_run_usd` is the per-run budget
    accumulator (TDD 6.5) — it only lives as long as the process does.
    """

    def __init__(
        self,
        config: EngineConfig,
        *,
        data_root: Path,
        prompts_dir: Path = Path("prompts"),
        client: LLMClient | None = None,
    ) -> None:
        self.config = config
        self.data_root = data_root
        self.prompts_dir = prompts_dir
        self.cache_dir = data_root / ".llm-cache"
        self.ledger_path = data_root / "ledger.jsonl"
        self._client = client or AnthropicClient()
        self._run_usd = 0.0

    def _model_for_tier(self, tier: str) -> str:
        return getattr(self.config.llm.models, tier)

    def _check_budget(self, tier: str) -> str:
        """Month-to-date and per-run caps (TDD 6.5). Returns the tier to
        actually bill against — `on_exceed: degrade` drops to `cheap`."""
        budget = self.config.llm.budget
        month_usd = ledger.month_to_date_usd(ledger.read_all(self.ledger_path))
        over_month = month_usd >= budget.monthly_usd
        over_run = self._run_usd >= budget.per_run_usd
        if not (over_month or over_run):
            return tier

        if budget.on_exceed == "degrade" and tier != "cheap":
            return "cheap"

        spent = month_usd if over_month else self._run_usd
        cap = budget.monthly_usd if over_month else budget.per_run_usd
        scope = "monthly" if over_month else "per-run"
        raise BudgetExceeded(f"{scope} LLM budget exceeded: ${spent:.2f} >= ${cap:.2f}")

    def _call_with_retry(
        self, *, model: str, system: str, user: str, max_tokens: int
    ) -> ProviderResponse:
        retry = self.config.llm.retry
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._client.complete(
                    model=model, system=system, user=user, max_tokens=max_tokens
                )
            except anthropic.APIStatusError as exc:
                if exc.status_code not in _RETRYABLE_STATUS or attempt >= retry.max_attempts:
                    raise
            except anthropic.APIConnectionError:
                # Network-level failures (read timeouts, connection resets,
                # DNS blips — APITimeoutError is a subclass of this) — not
                # an APIStatusError, so this needs its own except clause or
                # it isn't retried at all. A slow reasoning-tier response is
                # exactly the case this must cover.
                if attempt >= retry.max_attempts:
                    raise

            delay = retry.backoff_base_sec * (2 ** (attempt - 1)) + random.uniform(
                0, retry.backoff_base_sec
            )
            time.sleep(delay)

    @staticmethod
    def _try_validate(schema: dict[str, Any], content: str) -> tuple[Any | None, str | None]:
        try:
            parsed = json.loads(_strip_code_fence(content))
            jsonschema.validate(parsed, schema)
        except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
            # Include a snippet of what the model actually returned -- the
            # bare jsonschema/JSONDecodeError text alone (e.g. "Expecting
            # value: line 1 column 1 (char 0)") is identical whether the
            # model returned nothing at all or something non-empty that
            # merely failed to parse, which made a real failure
            # (research_stance against a live harvest) undiagnosable after
            # the fact since `content` itself was never surfaced anywhere.
            snippet = content[:300] + ("..." if len(content) > 300 else "")
            return None, f"{exc} | raw response: {snippet!r}"
        return parsed, None

    def complete(
        self,
        prompt_id: str,
        vars: dict[str, Any],
        *,
        schema: dict[str, Any] | None = None,
        tier: str = "default",
        cache: bool = True,
        piece: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> LLMResult:
        template = load_prompt(prompt_id, self.prompts_dir)
        system, user = render_prompt(template, vars)
        rendered = f"{system}\x1f{user}"

        # Cache check runs on the nominal (pre-budget) model, before the
        # budget check — a cache hit costs nothing, so it must not be
        # blockable by a budget that a real call would have exceeded
        # (ADR-007: cache hits keep tests deterministic and free).
        nominal_model = self._model_for_tier(tier)
        key = cache_store.compute_key(prompt_id, template.version, rendered, nominal_model, schema)
        if cache:
            cached = cache_store.read(self.cache_dir, key)
            if cached is not None:
                return LLMResult(**{**cached, "cache_hit": True})

        effective_tier = self._check_budget(tier)
        model = self._model_for_tier(effective_tier)
        if model != nominal_model:
            key = cache_store.compute_key(prompt_id, template.version, rendered, model, schema)

        response = self._call_with_retry(
            model=model, system=system, user=user, max_tokens=max_tokens
        )
        content = response.content
        in_tokens, out_tokens = response.in_tokens, response.out_tokens
        parsed: Any | None = None
        validation_error: str | None = None

        if schema is not None:
            parsed, validation_error = self._try_validate(schema, content)
            if validation_error is not None:
                repair_user = (
                    f"{user}\n\n"
                    f"Your previous response failed schema validation:\n{validation_error}\n\n"
                    "Return only corrected JSON matching the schema, with no other text."
                )
                repair = self._call_with_retry(
                    model=model, system=system, user=repair_user, max_tokens=max_tokens
                )
                in_tokens += repair.in_tokens
                out_tokens += repair.out_tokens
                content = repair.content
                parsed, validation_error = self._try_validate(schema, content)

        # Record spend/ledger against the tokens actually billed — including
        # a still-failing repair attempt — *before* raising. Both calls cost
        # real money; raising first would silently drop that spend from
        # ce cost and the budget governor (a bug caught in WP-02 review).
        usd = estimate_usd(model, in_tokens, out_tokens)
        self._run_usd += usd

        ledger.append(
            self.ledger_path,
            ledger.LedgerRecord(
                ts=datetime.now(UTC),
                prompt=prompt_id,
                version=template.version,
                model=model,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                usd=usd,
                piece=piece,
                cache_hit=False,
            ),
        )

        if validation_error is not None:
            raise SchemaValidationError(
                f"prompt {prompt_id!r}: schema validation failed after one repair attempt: {validation_error}"
            )

        result = LLMResult(
            content=content,
            parsed=parsed,
            model=model,
            prompt_version=template.version,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            usd=usd,
            cache_hit=False,
        )
        if cache:
            cache_store.write(self.cache_dir, key, result.model_dump(mode="json"))
        return result
