"""YouTube view/like/comment counts via the YouTube Data API v3 (TDD 12
WP-15). A single read-only GET against `videos.list?part=statistics`
doesn't justify `google-api-python-client` (a heavyweight, discovery-
document-based SDK meant for multi-endpoint, write-capable use) -- same
"one GET doesn't need an SDK" call `harvest/research.py`'s
`DuckDuckGoSearchClient` already makes, still valid here since there's no
retry/streaming/multi-endpoint surface an SDK would actually earn its
keep on.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx

from ce.exit_codes import MetricsError

_VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")


@dataclass(frozen=True)
class VideoStats:
    views: int
    likes: int
    comments: int


class YouTubeClient(Protocol):
    def stats(self, video_id: str) -> VideoStats: ...


class YouTubeDataApiClient:
    """The API-key check stays lazy (on `stats()`, not `__init__`) -- see
    `metrics.umami.HttpxUmamiClient` for why."""

    _URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key or os.environ.get("YOUTUBE_API_KEY", "")
        self._timeout = timeout

    def stats(self, video_id: str) -> VideoStats:
        if not self._api_key:
            raise MetricsError("YOUTUBE_API_KEY is not set", hint="ce doctor")

        try:
            response = httpx.get(
                self._URL,
                params={"part": "statistics", "id": video_id, "key": self._api_key},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MetricsError(f"YouTube stats request failed: {exc}") from exc

        items = response.json().get("items", [])
        if not items:
            raise MetricsError(f"YouTube video {video_id!r} not found or not public")

        stats = items[0]["statistics"]
        return VideoStats(
            views=int(stats.get("viewCount", 0)),
            likes=int(stats.get("likeCount", 0)),
            comments=int(stats.get("commentCount", 0)),
        )


def extract_video_id(url: str) -> str:
    """Parses the 11-char video id out of a watch/shorts/live/youtu.be URL.

    Covers the shapes `ce posted --url` will actually see pasted from a
    browser: `youtu.be/<id>`, `youtube.com/watch?v=<id>`,
    `youtube.com/shorts|live|embed/<id>`.
    """
    parsed = urlparse(url)

    if parsed.hostname and "youtu.be" in parsed.hostname:
        candidate = parsed.path.lstrip("/")
    else:
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            candidate = query_id
        else:
            parts = [p for p in parsed.path.split("/") if p]
            candidate = parts[-1] if parts else ""

    if not _VIDEO_ID_RE.match(candidate):
        raise MetricsError(f"could not extract a YouTube video id from {url!r}")
    return candidate
