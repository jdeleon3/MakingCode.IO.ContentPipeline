"""Pydantic entities for every schema in TDD 5.2.

These are the on-disk shape of `data/` (TDD 5.4: directory-as-database).
Everything here is stored as YAML and validated on load — `store.py` is the
only module that should read or write these files directly.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


def expand_and_resolve(value: str | Path) -> Path:
    """`~` expansion + absolute resolution.

    G1 (TDD 6.1) compares repo paths as resolved absolutes to block symlink
    and `..` escapes from the allowlist, so paths are normalised at the model
    boundary rather than left as whatever string was in the YAML.
    """
    return Path(value).expanduser().resolve()


# ---------------------------------------------------------------------------
# Shared enums (closed sets named explicitly in TDD 5.2 / 5.3)
# ---------------------------------------------------------------------------


class PublishableLevel(StrEnum):
    FULL = "full"
    LESSONS_ONLY = "lessons-only"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    HARVESTED = "harvested"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class CaptureType(StrEnum):
    AUDIO = "audio"
    SCREENSHOT = "screenshot"
    SCREENCAST = "screencast"
    FRICTION = "friction"
    # A pre-written text reflection (e.g. a journal/retrospective note kept
    # outside this tool) ingested whole, expanded into captures_context in
    # full the same way an audio transcript is -- not a fit for FRICTION's
    # one-line in-the-moment jots or its "Friction log" framing, since this
    # kind of note isn't necessarily about what went wrong.
    NOTE = "note"


class CaptureMoment(StrEnum):
    IN_SITU = "in_situ"
    RETRO = "retro"


class BriefArchetype(StrEnum):
    """TDD 5.3 — fixed enum. The inventory generator attempts one per project."""

    WHY_THIS_PROJECT = "why_this_project"
    BUILD_WALKTHROUGH = "build_walkthrough"
    WHAT_WENT_WRONG = "what_went_wrong"
    I_WAS_WRONG = "i_was_wrong"
    TOOL_REVIEW = "tool_review"
    SPECIFIC_GOTCHA = "specific_gotcha"
    RETROSPECTIVE = "retrospective"
    VIDEO_WALKTHROUGH = "video_walkthrough"


class GroundingStrength(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"  # gate-blocked downstream (TDD 12, WP-08), not enforced here


class BriefStatus(StrEnum):
    CANDIDATE = "candidate"
    SELECTED = "selected"
    PRODUCED = "produced"
    PUBLISHED = "published"
    DROPPED = "dropped"


class PieceStatus(StrEnum):
    DRAFTED = "drafted"
    EDITED = "edited"
    VERIFIED = "verified"
    PUBLISHED = "published"


class Platform(StrEnum):
    """All four rendition targets. Used for `Brief.target_platforms`."""

    SITE = "site"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    YOUTUBE = "youtube"


class PostPlatform(StrEnum):
    """The subset of `Platform` you actually post to by hand (`ce posted`).

    `site` is excluded: it's published automatically by `ce publish site`,
    never recorded via manual post-back.
    """

    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    YOUTUBE = "youtube"


# ---------------------------------------------------------------------------
# Shared value objects
# ---------------------------------------------------------------------------


class RepoRef(BaseModel):
    """A repo entry — identical shape in `engine.yml`'s allowlist and
    `Project.repos`. Defined once so both consume the same validation."""

    name: str
    path: Path
    publishable: PublishableLevel

    _resolve_path = field_validator("path", mode="before")(expand_and_resolve)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class Selection(BaseModel):
    """Why this project was picked (TDD 5.2 `project.yml#selection`)."""

    demand_signals: list[str] = Field(default_factory=list)
    hypothesis: str = ""
    expected_failure_surface: str = ""


class Project(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$", description="Immutable, primary key.")
    title: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    started_at: date
    ended_at: date | None = None
    repos: list[RepoRef] = Field(default_factory=list)
    selection: Selection = Field(default_factory=Selection)
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


class CaptureDerived(BaseModel):
    """Audio captures populate both transcript fields; NOTE captures populate
    only `transcript_clean` (the note's own text, verbatim -- there's no
    separate "raw" pass for a note the way there is for ASR output). Every
    other type leaves both unset."""

    transcript_raw: Path | None = None
    transcript_clean: Path | None = None
    duration_sec: float | None = None


class Capture(BaseModel):
    id: str
    project: str
    type: CaptureType
    moment: CaptureMoment
    captured_at: datetime
    source_path: Path
    derived: CaptureDerived | None = None
    context: str | None = None


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


class BriefDemand(BaseModel):
    recurrence: int = Field(ge=0, description="Sweeps out of the last 4 (TDD 5.2).")
    signals: list[str] = Field(default_factory=list)


class BriefEvidence(BaseModel):
    """`kind` is intentionally a free string, not an enum.

    TDD 5.3 marks the archetype enum as fixed; evidence `kind` is not — WP-05
    (git) and WP-07 (research) are the actual producers and may introduce
    kinds beyond the `git`/`audio` shown in the TDD 5.2 example.
    """

    kind: str
    ref: str
    note: str | None = None
    quote: str | None = None


class Brief(BaseModel):
    id: str
    project: str
    archetype: BriefArchetype
    title: str
    angle: str
    target_platforms: list[Platform] = Field(default_factory=list)
    demand: BriefDemand
    evidence: list[BriefEvidence] = Field(default_factory=list)
    grounding_strength: GroundingStrength
    dedupe_max_similarity: float = Field(ge=0.0, le=1.0)
    weakest_point: str
    risk_flags: list[str] = Field(default_factory=list)
    status: BriefStatus = BriefStatus.CANDIDATE

    @field_validator("weakest_point")
    @classmethod
    def _weakest_point_not_blank(cls, v: str) -> str:
        """TDD 12 WP-08 Done-when: "weakest_point is required and non-empty
        for every brief." Enforced at the model layer, not just at
        `brief_generate`'s JSON schema, so any future producer of a `Brief`
        gets the same guarantee for free."""
        if not v.strip():
            raise ValueError("weakest_point must not be blank")
        return v


# ---------------------------------------------------------------------------
# Piece
# ---------------------------------------------------------------------------


class GradeScores(BaseModel):
    """The five scored dimensions (TDD 8 `produce.grade_weights`).

    Shared shape between a grading attempt's raw scores here and the
    configured weights in `config.py` — same five keys, different meaning.
    """

    hook: float
    evidence: float
    specificity: float
    voice: float
    cta: float


class GradeAttempt(BaseModel):
    attempt: int = Field(ge=1)
    total: float
    scores: GradeScores


class VerificationSummary(BaseModel):
    claims_checked: int = Field(ge=0)
    claims_failed: int = Field(ge=0)
    ran_at: datetime


class PublishedInfo(BaseModel):
    url: str
    at: datetime


class Piece(BaseModel):
    id: str
    brief_id: str
    project: str
    slug: str
    status: PieceStatus = PieceStatus.DRAFTED
    created_at: datetime
    article_path: Path
    generated_at: datetime | None = None
    grades: list[GradeAttempt] = Field(default_factory=list)
    verification: VerificationSummary | None = None
    published: PublishedInfo | None = None


# ---------------------------------------------------------------------------
# PostRecord (data/posted.yml — a flat array, not per-project)
# ---------------------------------------------------------------------------


class MetricSnapshot(BaseModel):
    at: datetime
    impressions: int = Field(ge=0)
    reactions: int = Field(ge=0)
    comments: int = Field(ge=0)
    site_clicks: int = Field(ge=0)


class PostRecord(BaseModel):
    piece_id: str
    platform: PostPlatform
    url: str
    posted_at: datetime
    metrics: list[MetricSnapshot] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rendition (data/projects/<slug>/pieces/<id>/renditions/<platform>.yml)
#
# No schema is given anywhere in TDD 5.2 for this entity -- piece.yml's own
# example has no `renditions` key, and TDD 5.4/§7 only names the file paths
# (`renditions/{linkedin,facebook,youtube}.yml`), not their shape. Invented
# this session, same as WP-09's `grades.json`. `title`/`chapters` are
# YouTube-only (its rendition is structurally different: a title + a
# chapter list, not just a body); left unset for LinkedIn/Facebook rather
# than splitting into three separate per-platform models, since one shared
# shape is simpler for `ce package` (WP-13) to iterate over uniformly.
# ---------------------------------------------------------------------------


class Rendition(BaseModel):
    platform: PostPlatform
    body: str
    first_comment: str | None = None  # LinkedIn only: separate UTM'd-URL comment
    title: str | None = None  # YouTube only
    chapters: list[str] = Field(default_factory=list)  # YouTube only, "MM:SS Label" lines
    prompt_version: int
    generated_at: datetime


# ---------------------------------------------------------------------------
# Sweep (data/sweeps/<date>.json — the machine-readable half of `ce sweep`,
# TDD 12 WP-16)
#
# No schema exists anywhere in the TDD for this either (same gap as
# Rendition/GradeAttempt above) -- WP-16's Build line only names
# `sweep/hn.py`/`sweep/rss.py`/"recurrence scoring", never a data shape.
# `SweepSnapshot` is one day's raw signal haul, kept alongside the
# human-readable `sweeps/<date>.md` digest so recurrence scoring on a later
# run can compare against the last few days' *data* without re-parsing its
# own rendered markdown.
# ---------------------------------------------------------------------------


class SweepSignal(BaseModel):
    topic: str
    source: str  # "hn" | "rss" — a free string, not an enum: same reasoning
    # as BriefEvidence.kind above, a third source is plausible before this
    # enum would ever get revisited.
    title: str
    url: str
    strength: float = Field(ge=0.0)  # HN points, or a flat 1.0 for an RSS mention
    at: datetime


class SweepSnapshot(BaseModel):
    date: date
    signals: list[SweepSignal] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
