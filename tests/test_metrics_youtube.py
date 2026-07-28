"""WP-15 acceptance (TDD 12): `metrics/youtube.py`.

Real transport exercised only manually, same shape as `test_metrics_umami.py`.
"""

from __future__ import annotations

import httpx
import pytest

from ce.exit_codes import MetricsError
from ce.metrics.youtube import YouTubeDataApiClient, extract_video_id

_VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://youtu.be/{_VIDEO_ID}",
        f"https://www.youtube.com/watch?v={_VIDEO_ID}",
        f"https://www.youtube.com/watch?v={_VIDEO_ID}&t=42s",
        f"https://www.youtube.com/shorts/{_VIDEO_ID}",
        f"https://www.youtube.com/live/{_VIDEO_ID}",
    ],
)
def test_extract_video_id_from_common_url_shapes(url):
    assert extract_video_id(url) == _VIDEO_ID


def test_extract_video_id_rejects_an_unparsable_url():
    with pytest.raises(MetricsError, match="could not extract"):
        extract_video_id("https://example.com")


def test_stats_raises_without_api_key():
    client = YouTubeDataApiClient(api_key="")

    with pytest.raises(MetricsError, match="YOUTUBE_API_KEY"):
        client.stats(_VIDEO_ID)


def test_stats_parses_statistics(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "items": [
                    {"statistics": {"viewCount": "1000", "likeCount": "80", "commentCount": "12"}}
                ]
            }

    def fake_get(url, *, params, timeout):
        assert params["id"] == _VIDEO_ID
        assert params["key"] == "k"
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    client = YouTubeDataApiClient(api_key="k")
    stats = client.stats(_VIDEO_ID)

    assert stats.views == 1000
    assert stats.likes == 80
    assert stats.comments == 12


def test_stats_raises_a_readable_error_when_video_not_found(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"items": []}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse())

    client = YouTubeDataApiClient(api_key="k")

    with pytest.raises(MetricsError, match="not found"):
        client.stats(_VIDEO_ID)


def test_stats_wraps_http_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    client = YouTubeDataApiClient(api_key="k")

    with pytest.raises(MetricsError, match="YouTube stats request failed"):
        client.stats(_VIDEO_ID)
