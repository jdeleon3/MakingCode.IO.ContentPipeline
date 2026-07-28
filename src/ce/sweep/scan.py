"""`ce sweep` orchestration (TDD 12 WP-16): matches `config.sweep.topics`
against today's Hacker News + RSS haul, scores recurrence against the last
few sweeps, and writes both `sweeps/<date>.json` (the raw signals, so a
later run can score recurrence without re-parsing its own markdown) and
`sweeps/<date>.md` (the Recurring/Emerging/Fading digest — same
"structured data lives in git, the .md is what you read" split as
`harvest/inventory.md`).

No LLM call anywhere in this module. Unlike every other harvest-side work
package, WP-16's Build line names no new prompt — topic matching is a
plain case-insensitive substring match against a fixed, operator-edited
watch-list (`config.sweep.topics`), not an LLM classification call. That
also means there is nothing here to discover a topic the operator didn't
already think to list.

**Recurrence scoring.** Each topic gets a `(recurrence, today_strength)`
rank tuple. Python compares tuples element-by-element, so `recurrence`
always dominates the comparison regardless of how large `today_strength`
is — a topic seen in 3 of the last 4 sweeps outranks any brand-new
same-day spike, satisfying TDD 12 WP-16's Done-when line directly from the
sort, not from a hand-tuned weighting formula.

`recurrence` counts *prior* sweeps only -- up to the last `HISTORY_WINDOW`
snapshots already on disk, not counting today's own run -- matching the
Done-when line's literal "3 of 4 prior sweeps" and the same window
`BriefDemand.recurrence`'s TDD 5.2 comment describes ("sweeps out of the
last 4"). Today's own occurrence is a separate axis (`today_count`/
`today_strength`): a topic can spike hard today with zero history, or
recur for weeks with a quiet today -- the two are never added together.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ce import console
from ce.config import EngineConfig
from ce.exit_codes import SweepError
from ce.models import SweepSignal, SweepSnapshot
from ce.sweep.hn import HNClient
from ce.sweep.rss import RssClient

HISTORY_WINDOW = 4  # "the last 4 [prior] sweeps" (TDD 12 WP-16 Done-when, BriefDemand.recurrence)
RECURRING_THRESHOLD = 3  # of the last HISTORY_WINDOW prior sweeps (the Done-when's own "3 of 4")
FADING_THRESHOLD = 2  # of the prior sweeps, to flag a topic that just dropped off today
_HN_LOOKBACK_DAYS = 2  # how far back an HN/RSS hit still counts as "today's" signal

ALL_SOURCES: tuple[str, ...] = ("hn", "rss")


def sweeps_dir(data_root: Path) -> Path:
    return data_root / "sweeps"


def _snapshot_path(data_root: Path, on: date) -> Path:
    return sweeps_dir(data_root) / f"{on.isoformat()}.json"


def _digest_path(data_root: Path, on: date) -> Path:
    return sweeps_dir(data_root) / f"{on.isoformat()}.md"


def read_snapshot(data_root: Path, on: date) -> SweepSnapshot | None:
    path = _snapshot_path(data_root, on)
    if not path.exists():
        return None
    return SweepSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def _write_snapshot(data_root: Path, snapshot: SweepSnapshot) -> None:
    path = _snapshot_path(data_root, snapshot.date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")


def _load_prior_snapshots(data_root: Path, before: date, limit: int) -> list[SweepSnapshot]:
    """Sweep snapshots strictly before `before`, most recent first, capped
    at `limit`. Returns fewer than `limit` early in the project's life --
    there's no history to score against yet, not an error."""
    directory = sweeps_dir(data_root)
    if not directory.exists():
        return []
    prior_dates: list[date] = []
    for path in directory.glob("*.json"):
        try:
            found = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if found < before:
            prior_dates.append(found)
    prior_dates.sort(reverse=True)
    return [
        SweepSnapshot.model_validate_json(_snapshot_path(data_root, d).read_text(encoding="utf-8"))
        for d in prior_dates[:limit]
    ]


# ---------------------------------------------------------------------------
# Collection — a source failing never aborts the others (TDD 12 Done-when)
# ---------------------------------------------------------------------------


def collect_signals(
    topics: Sequence[str],
    *,
    hn_client: HNClient,
    rss_feeds: Sequence[str],
    rss_client: RssClient,
    since: date,
    now: datetime,
    sources: Sequence[str] = ALL_SOURCES,
) -> tuple[list[SweepSignal], list[str]]:
    """One HN Algolia search per topic, one RSS fetch per configured feed --
    both sides then re-filtered against every topic by a plain title
    substring match (Algolia's own relevance search returns stemmed/fuzzy
    matches, e.g. a query for "Astro" surfacing a story titled
    "Astronauts describe...", so its hits aren't trusted as already-precise).
    Each call is caught independently -- a dead feed or a failed HN request
    is recorded in the returned `failed` list and skipped, never raised out
    of this function.
    """
    signals: list[SweepSignal] = []
    failed: list[str] = []

    if "hn" in sources:
        for topic in topics:
            try:
                hits = hn_client.search(topic, since=since)
            except SweepError as exc:
                console.warn(f"ce sweep: {exc}")
                failed.append(f"hn:{topic}")
                continue
            for hit in hits:
                if topic.lower() not in hit.title.lower():
                    continue
                signals.append(
                    SweepSignal(
                        topic=topic,
                        source="hn",
                        title=hit.title,
                        url=hit.url,
                        strength=float(hit.points),
                        at=hit.created_at,
                    )
                )

    if "rss" in sources:
        for feed_url in rss_feeds:
            try:
                entries = rss_client.entries(feed_url)
            except SweepError as exc:
                console.warn(f"ce sweep: {exc}")
                failed.append(f"rss:{feed_url}")
                continue
            for entry in entries:
                if entry.published_at is not None and entry.published_at.date() < since:
                    continue
                for topic in topics:
                    if topic.lower() in entry.title.lower():
                        signals.append(
                            SweepSignal(
                                topic=topic,
                                source="rss",
                                title=entry.title,
                                url=entry.link,
                                strength=1.0,
                                at=entry.published_at or now,
                            )
                        )

    return signals, failed


# ---------------------------------------------------------------------------
# Recurrence scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopicRank:
    topic: str
    today_count: int
    today_strength: float
    recurrence: int  # of the last HISTORY_WINDOW *prior* sweeps -- today is not part of this count
    signals: tuple[SweepSignal, ...] = ()

    @property
    def sort_key(self) -> tuple[int, float]:
        """Recurrence first, today's strength only as a tie-breaker --
        this ordering is what actually satisfies "a topic present in 3 of
        4 prior sweeps ranks above a same-day spike" (TDD 12 Done-when):
        a topic's historical pattern always outweighs how big today's
        number happens to be."""
        return (self.recurrence, self.today_strength)


def rank_topics(
    topics: Sequence[str],
    today_signals: Sequence[SweepSignal],
    prior_snapshots: Sequence[SweepSnapshot],
) -> list[TopicRank]:
    ranks: list[TopicRank] = []
    for topic in topics:
        matched_today = tuple(s for s in today_signals if s.topic == topic)
        recurrence = sum(
            1 for snapshot in prior_snapshots if any(s.topic == topic for s in snapshot.signals)
        )
        ranks.append(
            TopicRank(
                topic=topic,
                today_count=len(matched_today),
                today_strength=sum(s.strength for s in matched_today),
                recurrence=recurrence,
                signals=matched_today,
            )
        )
    ranks.sort(key=lambda r: r.sort_key, reverse=True)
    return ranks


def _bucket(rank: TopicRank) -> str | None:
    """`None` means "not interesting enough to print" -- a configured topic
    with zero signal today and no meaningful history either."""
    if rank.today_count > 0:
        return "recurring" if rank.recurrence >= RECURRING_THRESHOLD else "emerging"
    if rank.recurrence >= FADING_THRESHOLD:
        return "fading"
    return None


# ---------------------------------------------------------------------------
# sweeps/<date>.md
# ---------------------------------------------------------------------------


def _write_digest(
    data_root: Path, on: date, ranks: list[TopicRank], snapshot: SweepSnapshot
) -> None:
    recurring = [r for r in ranks if _bucket(r) == "recurring"]
    emerging = [r for r in ranks if _bucket(r) == "emerging"]
    fading = [r for r in ranks if _bucket(r) == "fading"]

    lines = [f"# Sweep -- {on.isoformat()}", ""]

    def _section(title: str, items: list[TopicRank]) -> None:
        lines.append(f"## {title}")
        if not items:
            lines.append("_none_")
            lines.append("")
            return
        for rank in items:
            lines.append(
                f"- **{rank.topic}** -- {rank.recurrence}/{HISTORY_WINDOW} prior sweeps, "
                f"{rank.today_count} mention(s) today (strength {rank.today_strength:.0f})"
            )
            top_signals = sorted(rank.signals, key=lambda s: s.strength, reverse=True)[:3]
            for signal in top_signals:
                lines.append(f"  - [{signal.title}]({signal.url})")
        lines.append("")

    _section("Recurring", recurring)
    _section("Emerging", emerging)
    _section("Fading", fading)

    if snapshot.sources_failed:
        lines.append(
            f"_{len(snapshot.sources_failed)} source(s) failed this run: "
            f"{', '.join(snapshot.sources_failed)}_"
        )
        lines.append("")

    path = _digest_path(data_root, on)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepResult:
    date: date
    ranks: list[TopicRank]
    failed_sources: list[str]


def scan(
    data_root: Path,
    config: EngineConfig,
    *,
    hn_client: HNClient,
    rss_client: RssClient,
    sources: Sequence[str] = ALL_SOURCES,
    now: datetime | None = None,
) -> SweepResult:
    now = now or datetime.now(UTC)
    today = now.date()
    topics = config.sweep.topics
    since = today - timedelta(days=_HN_LOOKBACK_DAYS)

    signals, failed = collect_signals(
        topics,
        hn_client=hn_client,
        rss_feeds=config.sweep.rss_feeds,
        rss_client=rss_client,
        since=since,
        now=now,
        sources=sources,
    )

    prior = _load_prior_snapshots(data_root, today, HISTORY_WINDOW)
    ranks = rank_topics(topics, signals, prior)

    snapshot = SweepSnapshot(date=today, signals=signals, sources_failed=failed)
    _write_snapshot(data_root, snapshot)
    _write_digest(data_root, today, ranks, snapshot)

    return SweepResult(date=today, ranks=ranks, failed_sources=failed)
