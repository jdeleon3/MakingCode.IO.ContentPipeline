"""`ce metrics pull [--since DATE]` (TDD 12 WP-15): refresh `data/posted.yml`
with UTM-attributed site clicks (every platform, via Umami) and native
YouTube stats, then regenerate `data/performance.md` -- same "the data
lives in git, the .md is the thing you actually read" split as
`harvest/inventory.md` (WP-08).

**LinkedIn (and Facebook) engagement metrics are manual-entry-only.**
Neither has a public API for a personal/page post's impressions,
reactions, or comments without a partnered app review this project has no
path to (TDD §15: "API publishing to social platforms -- never, under
current product decisions" covers reads the same way it covers writes).
`pull()` never invents or zeroes those three fields for a non-YouTube
platform -- it carries forward whatever the most recent snapshot already
recorded (0 the first time, until the operator hand-edits `posted.yml`
directly -- the TDD 5.2 example's own LinkedIn snapshot, with real
impressions/reactions/comments, is only explainable as a hand-edit, since
no CLI command anywhere accepts those numbers). `site_clicks` is the one
field Umami can see regardless of platform, so it's the only field every
platform's snapshot gets refreshed for real.

**Idempotent per snapshot date** (today, UTC): re-running `pull` the same
day replaces that day's `MetricSnapshot` in place rather than appending a
second one for the same date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from ce import store
from ce.config import EngineConfig
from ce.exit_codes import MetricsError
from ce.metrics.umami import UmamiClient
from ce.metrics.youtube import YouTubeClient, extract_video_id
from ce.models import MetricSnapshot, PostPlatform, PostRecord
from ce.produce.renditions import canonical_url, utm_url


def _latest_snapshot(record: PostRecord) -> MetricSnapshot | None:
    return max(record.metrics, key=lambda m: m.at) if record.metrics else None


def pull(
    data_root: Path,
    config: EngineConfig,
    *,
    umami_client: UmamiClient,
    youtube_client: YouTubeClient,
    since: date | None = None,
    now: datetime | None = None,
) -> list[PostRecord]:
    """Returns the refreshed records (already written to `posted.yml`)."""
    records = store.read_posted(data_root)
    snapshot_at = now or datetime.now(UTC)
    snapshot_date = snapshot_at.date()

    updated: list[PostRecord] = []
    for record in records:
        found = store.find_piece(data_root, record.piece_id)
        if found is None:
            raise MetricsError(
                f"piece {record.piece_id!r} (posted to {record.platform.value}) no longer exists"
            )
        _project, piece = found

        base_url = canonical_url(config.identity.site_url, piece.slug)
        tracked_url = utm_url(
            base_url, config.utm.template, platform=record.platform.value, slug=piece.slug
        )
        clicks_since = since or record.posted_at.date()
        site_clicks = umami_client.clicks(url=tracked_url, since=clicks_since)

        prior = _latest_snapshot(record)
        if record.platform == PostPlatform.YOUTUBE:
            stats = youtube_client.stats(extract_video_id(record.url))
            impressions, reactions, comments = stats.views, stats.likes, stats.comments
        else:
            impressions = prior.impressions if prior else 0
            reactions = prior.reactions if prior else 0
            comments = prior.comments if prior else 0

        new_snapshot = MetricSnapshot(
            at=snapshot_at,
            impressions=impressions,
            reactions=reactions,
            comments=comments,
            site_clicks=site_clicks,
        )
        # Idempotent per snapshot date: drop today's prior snapshot (if
        # `pull` already ran once today) rather than appending a duplicate.
        metrics = sorted(
            (m for m in record.metrics if m.at.date() != snapshot_date),
            key=lambda m: m.at,
        )
        metrics.append(new_snapshot)
        updated.append(record.model_copy(update={"metrics": metrics}))

    store.write_posted(data_root, updated)
    _write_performance_md(data_root, updated)
    return updated


def _write_performance_md(data_root: Path, records: list[PostRecord]) -> None:
    """A human-readable digest of every post-back, same "content lives in
    git, the .md is what you read" split as `harvest/inventory.md`."""
    lines = ["# Performance", ""]
    if not records:
        lines.append("No posts recorded yet -- run `ce posted` after publishing to a platform.")

    for record in sorted(records, key=lambda r: (r.piece_id, r.platform.value)):
        latest = _latest_snapshot(record)
        lines.append(f"## {record.piece_id} -- {record.platform.value}")
        lines.append(f"- posted {record.posted_at.date().isoformat()}: {record.url}")
        if latest is None:
            lines.append("- no metrics pulled yet")
        else:
            lines.append(
                f"- as of {latest.at.date().isoformat()}: "
                f"{latest.impressions} impressions, {latest.reactions} reactions, "
                f"{latest.comments} comments, {latest.site_clicks} site clicks"
            )
        lines.append("")

    (data_root / "performance.md").write_text("\n".join(lines), encoding="utf-8")
