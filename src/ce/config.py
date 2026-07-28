"""Loads and validates `config/engine.yml` and `config/platforms/*.yml` (TDD 8).

Secrets are never read here: API keys are environment-only (TDD 8, 14) and
`ce doctor` already checks for their presence. This module only ever sees
the non-secret operational config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ce.exit_codes import ConfigError
from ce.models import GradeScores, RepoRef, expand_and_resolve

DEFAULT_ENGINE_CONFIG_PATH = Path("config/engine.yml")


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path}: expected a YAML mapping at the top level, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# engine.yml
# ---------------------------------------------------------------------------


class Identity(BaseModel):
    name: str
    site_url: str
    site_repo: Path
    timezone: str

    _resolve_repo = field_validator("site_repo", mode="before")(expand_and_resolve)


class ReposConfig(BaseModel):
    allowed: list[RepoRef] = Field(default_factory=list)


class LLMModels(BaseModel):
    reasoning: str
    default: str
    cheap: str


class BudgetConfig(BaseModel):
    monthly_usd: float = Field(gt=0)
    per_run_usd: float = Field(gt=0)
    on_exceed: Literal["halt", "degrade"] = "halt"


class RetryConfig(BaseModel):
    max_attempts: int = Field(ge=1)
    backoff_base_sec: float = Field(gt=0)


class LLMConfig(BaseModel):
    provider: str
    models: LLMModels
    budget: BudgetConfig
    retry: RetryConfig


class PreprocessConfig(BaseModel):
    silence_threshold_db: float
    silence_min_sec: float = Field(ge=0)
    loudnorm: bool = True


class TranscriptionConfig(BaseModel):
    provider: str
    model: str
    vocabulary: list[str] = Field(default_factory=list)
    preprocess: PreprocessConfig


class EmbeddingsConfig(BaseModel):
    provider: str
    model: str


class DedupeConfig(BaseModel):
    threshold: float = Field(ge=0.0, le=1.0)
    scope_days: int = Field(ge=1)


class ClaimsConfig(BaseModel):
    enabled: bool = True
    block_on_unverifiable: bool = True


class GatesConfig(BaseModel):
    allowlist: Literal["hard_fail"] = "hard_fail"
    secrets: Literal["hard_fail"] = "hard_fail"
    dedupe: DedupeConfig
    claims: ClaimsConfig


class ProduceConfig(BaseModel):
    min_grade: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    grade_weights: GradeScores


class GitHarvestConfig(BaseModel):
    lookback_days: int = Field(ge=1)
    min_significance: int = Field(ge=0)


class ResearchConfig(BaseModel):
    max_sources: int = Field(ge=1)
    # Swappable search backend (WP-07's `SearchClient` Protocol) — TDD names
    # no provider at all here. "gemini" (grounding-with-Google-Search) is
    # the default; "duckduckgo" needs no API key as a zero-config fallback;
    # "perplexity" is a third option. Needs GEMINI_API_KEY / PERPLEXITY_API_KEY
    # respectively when selected.
    provider: Literal["duckduckgo", "gemini", "perplexity"] = "gemini"


class InventoryConfig(BaseModel):
    min_briefs: int = Field(ge=1)
    max_briefs: int = Field(ge=1)

    @field_validator("max_briefs")
    @classmethod
    def _max_at_least_min(cls, v: int, info: Any) -> int:
        min_briefs = info.data.get("min_briefs")
        if min_briefs is not None and v < min_briefs:
            raise ValueError(f"max_briefs ({v}) must be >= min_briefs ({min_briefs})")
        return v


class HarvestConfig(BaseModel):
    git: GitHarvestConfig
    research: ResearchConfig
    inventory: InventoryConfig


class UtmConfig(BaseModel):
    template: str


class UmamiConfig(BaseModel):
    # No TDD schema exists for this at all (WP-15's Build line names
    # `metrics/umami.py` but §8 never lists an `analytics` section) --
    # `UMAMI_API_KEY` is the actual secret (environment-only, TDD §14);
    # these two are non-secret operational config, same split every other
    # provider section in this file already makes.
    api_url: str
    website_id: str


class AnalyticsConfig(BaseModel):
    umami: UmamiConfig


class SweepConfig(BaseModel):
    # No TDD schema exists for this either (WP-16's Build line names
    # `sweep/hn.py`/`sweep/rss.py` but §8 never lists a `sweep` section) --
    # `topics` is this operator's own watch-list (matched case-insensitively
    # as a substring against HN/RSS titles, no LLM classification involved),
    # same "EDIT THIS, it's project-specific" shape as
    # `transcription.vocabulary`. `rss_feeds` needs no API key at all (plain
    # GET), unlike every provider section above.
    topics: list[str] = Field(default_factory=list)
    rss_feeds: list[str] = Field(default_factory=list)


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: Identity
    repos: ReposConfig
    llm: LLMConfig
    transcription: TranscriptionConfig
    embeddings: EmbeddingsConfig
    gates: GatesConfig
    produce: ProduceConfig
    harvest: HarvestConfig
    utm: UtmConfig
    analytics: AnalyticsConfig
    sweep: SweepConfig


def load_engine_config(path: Path | None = None) -> EngineConfig:
    """Load and validate `engine.yml`. Defaults to `config/engine.yml` (cwd-relative)."""
    resolved = path or DEFAULT_ENGINE_CONFIG_PATH
    data = _read_yaml_mapping(resolved)
    try:
        return EngineConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{resolved}: {exc}") from exc


# ---------------------------------------------------------------------------
# config/platforms/*.yml
# ---------------------------------------------------------------------------


class ImageSpec(BaseModel):
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    formats: list[str] = Field(default_factory=list)


class PlatformAssets(BaseModel):
    image: ImageSpec


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    max_chars: int = Field(gt=0)
    hook_chars: int = Field(gt=0)
    links_in_body: bool
    supports_markdown: bool
    allow_unicode_styling: bool
    line_break_style: Literal["single", "double"]
    assets: PlatformAssets
    extras: list[str] = Field(default_factory=list)


def load_platform_config(path: Path) -> PlatformConfig:
    """Load and validate one `config/platforms/<name>.yml` file."""
    data = _read_yaml_mapping(path)
    try:
        return PlatformConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
