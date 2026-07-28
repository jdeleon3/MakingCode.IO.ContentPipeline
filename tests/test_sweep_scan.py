"""WP-16 acceptance (TDD 12): `sweep/scan.py`.

Done-when: writes `sweeps/<date>.md` with Recurring/Emerging/Fading
sections; a topic present in 3 of 4 prior sweeps ranks above a same-day
spike; network failure on one source doesn't abort the others.

Uses fake `HNClient`/`RssClient` (same DI shape as `harvest/research.py`'s
`SearchClient`/`FetchClient` fakes) -- zero network calls, fully deterministic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ce.models import SweepSignal, SweepSnapshot
from ce.sweep import scan as scan_module
from ce.sweep.hn import HNHit
from ce.sweep.rss import RssEntry


class FakeHNClient:
    def __init__(self, hits_by_topic=None, *, error_topics=()):
        self._hits_by_topic = hits_by_topic or {}
        self._error_topics = set(error_topics)
        self.calls: list[tuple[str, date]] = []

    def search(self, query, *, since):
        self.calls.append((query, since))
        if query in self._error_topics:
            from ce.exit_codes import SweepError

            raise SweepError(f"HN search for {query!r} failed: boom")
        return self._hits_by_topic.get(query, [])


class FakeRssClient:
    def __init__(self, entries_by_feed=None, *, error_feeds=()):
        self._entries_by_feed = entries_by_feed or {}
        self._error_feeds = set(error_feeds)
        self.calls: list[str] = []

    def entries(self, feed_url):
        self.calls.append(feed_url)
        if feed_url in self._error_feeds:
            from ce.exit_codes import SweepError

            raise SweepError(f"RSS fetch failed for {feed_url}: boom")
        return self._entries_by_feed.get(feed_url, [])


def _write_prior_snapshot(data_root, on: date, topics_present: list[str]) -> None:
    at = datetime(on.year, on.month, on.day, 9, tzinfo=UTC)
    snapshot = SweepSnapshot(
        date=on,
        signals=[
            SweepSignal(
                topic=t, source="hn", title=t, url="https://example.com", strength=1.0, at=at
            )
            for t in topics_present
        ],
    )
    path = data_root / "sweeps" / f"{on.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")


def test_scan_writes_a_digest_with_all_three_sections(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config(sweep={"topics": ["DuckDB"], "rss_feeds": []})
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)
    hn = FakeHNClient(
        {
            "DuckDB": [
                HNHit(
                    title="DuckDB news", url="https://x", points=50, num_comments=1, created_at=now
                )
            ]
        }
    )

    result = scan_module.scan(data_root, config, hn_client=hn, rss_client=FakeRssClient(), now=now)

    text = (data_root / "sweeps" / "2026-01-10.md").read_text(encoding="utf-8")
    assert "## Recurring" in text
    assert "## Emerging" in text
    assert "## Fading" in text
    assert result.ranks and result.ranks[0].topic == "DuckDB"


def test_topic_recurring_in_3_of_4_prior_sweeps_outranks_a_same_day_spike(
    tmp_path, make_engine_config
):
    data_root = tmp_path / "data"
    config = make_engine_config(sweep={"topics": ["DuckDB", "viral-thing"], "rss_feeds": []})

    # 4 prior sweeps: DuckDB present in 3 of them, viral-thing in none.
    _write_prior_snapshot(data_root, date(2026, 1, 6), ["DuckDB"])
    _write_prior_snapshot(data_root, date(2026, 1, 7), [])
    _write_prior_snapshot(data_root, date(2026, 1, 8), ["DuckDB"])
    _write_prior_snapshot(data_root, date(2026, 1, 9), ["DuckDB"])

    now = datetime(2026, 1, 10, 12, tzinfo=UTC)
    hn = FakeHNClient(
        {
            "DuckDB": [
                HNHit(
                    title="DuckDB minor update",
                    url="https://x",
                    points=5,
                    num_comments=0,
                    created_at=now,
                )
            ],
            "viral-thing": [
                HNHit(
                    title="This viral-thing is everywhere today",
                    url="https://y",
                    points=5000,
                    num_comments=900,
                    created_at=now,
                )
            ],
        }
    )

    result = scan_module.scan(data_root, config, hn_client=hn, rss_client=FakeRssClient(), now=now)

    ranked_topics = [r.topic for r in result.ranks]
    assert ranked_topics.index("DuckDB") < ranked_topics.index("viral-thing")

    duckdb_rank = next(r for r in result.ranks if r.topic == "DuckDB")
    viral_rank = next(r for r in result.ranks if r.topic == "viral-thing")
    assert duckdb_rank.recurrence == 3
    assert viral_rank.recurrence == 0
    assert viral_rank.today_strength > duckdb_rank.today_strength  # the spike really is bigger...
    assert duckdb_rank.sort_key > viral_rank.sort_key  # ...yet it still ranks lower.


def test_a_failing_source_does_not_abort_the_others(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config(
        sweep={
            "topics": ["DuckDB", "AI agents"],
            "rss_feeds": ["https://good.example.com/feed", "https://bad.example.com/feed"],
        }
    )
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)

    hn = FakeHNClient(
        {
            "AI agents": [
                HNHit(
                    title="AI agents ship",
                    url="https://x",
                    points=10,
                    num_comments=1,
                    created_at=now,
                )
            ]
        },
        error_topics=["DuckDB"],
    )
    rss = FakeRssClient(
        {
            "https://good.example.com/feed": [
                RssEntry(title="DuckDB tips", link="https://z", published_at=now)
            ]
        },
        error_feeds=["https://bad.example.com/feed"],
    )

    result = scan_module.scan(data_root, config, hn_client=hn, rss_client=rss, now=now)

    assert "hn:DuckDB" in result.failed_sources
    assert "rss:https://bad.example.com/feed" in result.failed_sources

    ai_rank = next(r for r in result.ranks if r.topic == "AI agents")
    duckdb_rank = next(r for r in result.ranks if r.topic == "DuckDB")
    assert ai_rank.today_count == 1  # HN succeeded for this topic
    assert duckdb_rank.today_count == 1  # came through the good RSS feed despite HN failing

    snapshot = scan_module.read_snapshot(data_root, date(2026, 1, 10))
    assert set(snapshot.sources_failed) == {"hn:DuckDB", "rss:https://bad.example.com/feed"}


def test_sources_filter_skips_the_excluded_source(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config(
        sweep={"topics": ["DuckDB"], "rss_feeds": ["https://good.example.com/feed"]}
    )
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)
    hn = FakeHNClient(
        {
            "DuckDB": [
                HNHit(
                    title="DuckDB news", url="https://x", points=1, num_comments=0, created_at=now
                )
            ]
        }
    )
    rss = FakeRssClient()

    scan_module.scan(data_root, config, hn_client=hn, rss_client=rss, sources=("rss",), now=now)

    assert hn.calls == []
    assert rss.calls == ["https://good.example.com/feed"]


def test_snapshot_json_is_written_and_readable_back(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config(sweep={"topics": ["DuckDB"], "rss_feeds": []})
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)
    hn = FakeHNClient(
        {
            "DuckDB": [
                HNHit(
                    title="DuckDB news", url="https://x", points=1, num_comments=0, created_at=now
                )
            ]
        }
    )

    scan_module.scan(data_root, config, hn_client=hn, rss_client=FakeRssClient(), now=now)

    snapshot = scan_module.read_snapshot(data_root, date(2026, 1, 10))
    assert snapshot is not None
    assert snapshot.signals[0].topic == "DuckDB"


def test_a_topic_absent_today_but_recurring_historically_is_fading(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config(sweep={"topics": ["Kafka"], "rss_feeds": []})
    _write_prior_snapshot(data_root, date(2026, 1, 8), ["Kafka"])
    _write_prior_snapshot(data_root, date(2026, 1, 9), ["Kafka"])
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)

    result = scan_module.scan(
        data_root, config, hn_client=FakeHNClient(), rss_client=FakeRssClient(), now=now
    )

    text = (data_root / "sweeps" / "2026-01-10.md").read_text(encoding="utf-8")
    fading_section = text.split("## Fading")[1]
    assert "Kafka" in fading_section
    kafka_rank = next(r for r in result.ranks if r.topic == "Kafka")
    assert kafka_rank.today_count == 0
    assert kafka_rank.recurrence == 2
