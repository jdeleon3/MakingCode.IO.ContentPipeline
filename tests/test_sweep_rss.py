"""WP-16 acceptance (TDD 12): `sweep/rss.py` -- parses both RSS 2.0 and
Atom (e.g. Reddit's own `.rss` feeds, which are actually Atom) through the
same local-element-name path.
"""

from __future__ import annotations

import httpx
import pytest

from ce.exit_codes import SweepError
from ce.sweep.rss import HttpxRssClient

_RSS_2_0 = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>DuckDB memory limits explained</title>
      <link>https://example.com/duckdb-memory</link>
      <pubDate>Mon, 01 Jan 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Unrelated post</title>
      <link>https://example.com/unrelated</link>
      <pubDate>Tue, 02 Jan 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>r/dataengineering</title>
  <entry>
    <title>AI agents in production: what actually broke</title>
    <link href="https://reddit.com/r/dataengineering/1" rel="alternate"/>
    <updated>2026-01-03T12:00:00Z</updated>
  </entry>
</feed>
"""


def _fake_get(content: bytes):
    def fake(url, *, timeout, follow_redirects, headers):
        class FakeResponse:
            def raise_for_status(self):
                pass

        response = FakeResponse()
        response.content = content
        return response

    return fake


def test_entries_parses_rss_2_0(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get(_RSS_2_0))

    client = HttpxRssClient()
    entries = client.entries("https://example.com/feed.rss")

    assert len(entries) == 2
    assert entries[0].title == "DuckDB memory limits explained"
    assert entries[0].link == "https://example.com/duckdb-memory"
    assert entries[0].published_at is not None
    assert entries[0].published_at.year == 2026


def test_entries_parses_atom(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get(_ATOM))

    client = HttpxRssClient()
    entries = client.entries("https://reddit.com/r/dataengineering/.rss")

    assert len(entries) == 1
    assert entries[0].title == "AI agents in production: what actually broke"
    assert entries[0].link == "https://reddit.com/r/dataengineering/1"
    assert entries[0].published_at.isoformat().startswith("2026-01-03")


def test_entries_wraps_http_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    client = HttpxRssClient()

    with pytest.raises(SweepError, match="RSS fetch failed"):
        client.entries("https://example.com/feed.rss")


def test_entries_wraps_malformed_xml(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get(b"<not><valid"))

    client = HttpxRssClient()

    with pytest.raises(SweepError, match="RSS fetch failed"):
        client.entries("https://example.com/feed.rss")
