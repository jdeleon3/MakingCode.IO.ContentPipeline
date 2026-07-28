"""WP-16 acceptance (TDD 12): `sweep/hn.py` -- Algolia HN Search, no auth."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from ce.exit_codes import SweepError
from ce.sweep.hn import AlgoliaHNClient


def test_search_parses_hits(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "hits": [
                    {
                        "title": "DuckDB 1.1 released",
                        "url": "https://duckdb.org/2026/01/01/release",
                        "points": 340,
                        "num_comments": 88,
                        "created_at_i": 1750000000,
                        "objectID": "123",
                    },
                    {
                        "title": "Ask HN: memory limits",
                        "points": 12,
                        "num_comments": 4,
                        "created_at_i": 1750000100,
                        "objectID": "456",
                    },
                ]
            }

    def fake_get(url, *, params, timeout):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    client = AlgoliaHNClient()
    hits = client.search("DuckDB", since=date(2026, 1, 1))

    assert captured["url"] == "https://hn.algolia.com/api/v1/search"
    assert captured["params"]["query"] == "DuckDB"
    assert captured["params"]["tags"] == "story"
    assert "created_at_i>=" in captured["params"]["numericFilters"]

    assert len(hits) == 2
    assert hits[0].title == "DuckDB 1.1 released"
    assert hits[0].url == "https://duckdb.org/2026/01/01/release"
    assert hits[0].points == 340
    assert hits[0].num_comments == 88
    assert hits[0].created_at == datetime.fromtimestamp(1750000000, tz=UTC)

    # No `url` field on the raw hit -> falls back to the HN discussion link.
    assert hits[1].url == "https://news.ycombinator.com/item?id=456"


def test_search_wraps_http_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    client = AlgoliaHNClient()

    with pytest.raises(SweepError, match="HN search"):
        client.search("DuckDB", since=date(2026, 1, 1))
