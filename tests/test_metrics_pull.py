"""WP-15 acceptance (TDD 12): `metrics/pull.py`.

Done-when: UTM-attributed clicks resolve per platform; LinkedIn is
correctly recorded as manual-entry-only; re-running `metrics pull` is
idempotent per snapshot date.

Uses fake `UmamiClient`/`YouTubeClient` (dependency injection, same shape
as `harvest/research.py`'s `SearchClient`/`FetchClient` fakes) rather than
hitting either real API -- zero network calls, fully deterministic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ce import store
from ce.exit_codes import MetricsError
from ce.metrics import pull as pull_module
from ce.metrics.youtube import VideoStats
from ce.models import MetricSnapshot, Piece, PostPlatform, PostRecord, Project
from ce.produce.renditions import canonical_url, utm_url

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class FakeUmamiClient:
    def __init__(self, clicks_by_url: dict[str, int]):
        self._clicks_by_url = clicks_by_url
        self.calls: list[tuple[str, date]] = []

    def clicks(self, *, url: str, since: date) -> int:
        self.calls.append((url, since))
        return self._clicks_by_url.get(url, 0)


class FakeYouTubeClient:
    def __init__(self, stats_by_video_id: dict[str, VideoStats]):
        self._stats = stats_by_video_id
        self.calls: list[str] = []

    def stats(self, video_id: str) -> VideoStats:
        self.calls.append(video_id)
        return self._stats[video_id]


def _write_piece(data_root: Path, *, slug="a-piece", piece_id="pc-0001") -> Piece:
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    piece = Piece(
        id=piece_id,
        brief_id="br-01",
        project="test-proj",
        slug=slug,
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        article_path=Path("article.md"),
    )
    store.write_piece(data_root, "test-proj", piece)
    return piece


def _tracked_url(config, slug: str, platform: str) -> str:
    base = canonical_url(config.identity.site_url, slug)
    return utm_url(base, config.utm.template, platform=platform, slug=slug)


def test_pull_resolves_utm_clicks_per_platform(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config()
    piece = _write_piece(data_root)
    store.write_posted(
        data_root,
        [
            PostRecord(
                piece_id=piece.id,
                platform=PostPlatform.LINKEDIN,
                url="https://linkedin.test/posts/1",
                posted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
            )
        ],
    )
    tracked_url = _tracked_url(config, piece.slug, "linkedin")
    umami = FakeUmamiClient({tracked_url: 133})

    updated = pull_module.pull(
        data_root,
        config,
        umami_client=umami,
        youtube_client=FakeYouTubeClient({}),
        now=NOW,
    )

    assert umami.calls[0][0] == tracked_url
    assert updated[0].metrics[-1].site_clicks == 133


def test_pull_youtube_uses_native_stats_not_umami_engagement(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config()
    piece = _write_piece(data_root)
    store.write_posted(
        data_root,
        [
            PostRecord(
                piece_id=piece.id,
                platform=PostPlatform.YOUTUBE,
                url="https://youtu.be/dQw4w9WgXcQ",
                posted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
            )
        ],
    )
    umami = FakeUmamiClient({_tracked_url(config, piece.slug, "youtube"): 42})
    youtube = FakeYouTubeClient({"dQw4w9WgXcQ": VideoStats(views=1000, likes=80, comments=12)})

    updated = pull_module.pull(
        data_root, config, umami_client=umami, youtube_client=youtube, now=NOW
    )

    snapshot = updated[0].metrics[-1]
    assert youtube.calls == ["dQw4w9WgXcQ"]
    assert snapshot.impressions == 1000
    assert snapshot.reactions == 80
    assert snapshot.comments == 12
    assert snapshot.site_clicks == 42


@pytest.mark.parametrize("platform", [PostPlatform.LINKEDIN, PostPlatform.FACEBOOK])
def test_pull_non_youtube_platforms_are_manual_entry_only_carry_forward_engagement(
    tmp_path, make_engine_config, platform
):
    """TDD 5.2's own posted.yml example has real LinkedIn impressions/
    reactions/comments -- only explainable as a hand-edit, since no CLI
    command accepts them. Neither LinkedIn nor Facebook has a public API
    for a personal/page post's engagement metrics, so `pull` must never
    invent or zero those three fields for either; it only ever refreshes
    `site_clicks`."""
    data_root = tmp_path / "data"
    config = make_engine_config()
    piece = _write_piece(data_root)
    store.write_posted(
        data_root,
        [
            PostRecord(
                piece_id=piece.id,
                platform=platform,
                url=f"https://{platform.value}.test/posts/1",
                posted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
                metrics=[
                    MetricSnapshot(
                        at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
                        impressions=4200,
                        reactions=87,
                        comments=14,
                        site_clicks=100,
                    )
                ],
            )
        ],
    )
    umami = FakeUmamiClient({_tracked_url(config, piece.slug, platform.value): 133})

    updated = pull_module.pull(
        data_root, config, umami_client=umami, youtube_client=FakeYouTubeClient({}), now=NOW
    )

    snapshot = updated[0].metrics[-1]
    assert snapshot.impressions == 4200
    assert snapshot.reactions == 87
    assert snapshot.comments == 14
    assert snapshot.site_clicks == 133


def test_pull_is_idempotent_per_snapshot_date(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config()
    piece = _write_piece(data_root)
    store.write_posted(
        data_root,
        [
            PostRecord(
                piece_id=piece.id,
                platform=PostPlatform.LINKEDIN,
                url="https://linkedin.test/posts/1",
                posted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
            )
        ],
    )
    tracked_url = _tracked_url(config, piece.slug, "linkedin")

    pull_module.pull(
        data_root,
        config,
        umami_client=FakeUmamiClient({tracked_url: 100}),
        youtube_client=FakeYouTubeClient({}),
        now=NOW,
    )
    updated = pull_module.pull(
        data_root,
        config,
        umami_client=FakeUmamiClient({tracked_url: 133}),
        youtube_client=FakeYouTubeClient({}),
        now=NOW,  # same day -> replaces, doesn't append
    )

    same_day = [m for m in updated[0].metrics if m.at.date() == NOW.date()]
    assert len(same_day) == 1
    assert same_day[0].site_clicks == 133


def test_pull_raises_if_piece_no_longer_exists(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config()
    store.write_posted(
        data_root,
        [
            PostRecord(
                piece_id="pc-9999",
                platform=PostPlatform.LINKEDIN,
                url="https://linkedin.test/posts/1",
                posted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
            )
        ],
    )

    with pytest.raises(MetricsError):
        pull_module.pull(
            data_root,
            config,
            umami_client=FakeUmamiClient({}),
            youtube_client=FakeYouTubeClient({}),
            now=NOW,
        )


def test_pull_writes_performance_md(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config()
    piece = _write_piece(data_root)
    store.write_posted(
        data_root,
        [
            PostRecord(
                piece_id=piece.id,
                platform=PostPlatform.LINKEDIN,
                url="https://linkedin.test/posts/1",
                posted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
            )
        ],
    )
    tracked_url = _tracked_url(config, piece.slug, "linkedin")

    pull_module.pull(
        data_root,
        config,
        umami_client=FakeUmamiClient({tracked_url: 133}),
        youtube_client=FakeYouTubeClient({}),
        now=NOW,
    )

    text = (data_root / "performance.md").read_text(encoding="utf-8")
    assert "pc-0001" in text
    assert "linkedin" in text
    assert "133 site clicks" in text


def test_pull_with_no_posted_records_writes_a_readable_performance_md(tmp_path, make_engine_config):
    data_root = tmp_path / "data"
    config = make_engine_config()

    updated = pull_module.pull(
        data_root,
        config,
        umami_client=FakeUmamiClient({}),
        youtube_client=FakeYouTubeClient({}),
        now=NOW,
    )

    assert updated == []
    text = (data_root / "performance.md").read_text(encoding="utf-8")
    assert "No posts recorded yet" in text
