"""WP-15 acceptance (TDD 12): `metrics/umami.py`.

The real client's own transport is exercised only manually (this dev
environment has no live Umami instance to hit) -- same shape as WP-04's
ffmpeg/WP-05's gitleaks. `httpx.get` is monkeypatched to prove request
shape, response parsing, and error wrapping without a network call.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from ce.exit_codes import MetricsError
from ce.metrics.umami import HttpxUmamiClient, _path_and_query


def test_path_and_query_ignores_scheme_and_host():
    assert _path_and_query("https://a.test/blog/x?utm_source=linkedin") == _path_and_query(
        "https://b.test/blog/x?utm_source=linkedin"
    )


def test_path_and_query_distinguishes_different_queries():
    assert _path_and_query("https://a.test/blog/x?utm_source=linkedin") != _path_and_query(
        "https://a.test/blog/x?utm_source=facebook"
    )


def test_clicks_raises_without_api_key():
    client = HttpxUmamiClient(api_url="https://umami.test", website_id="site-1", api_key="")

    with pytest.raises(MetricsError, match="UMAMI_API_KEY"):
        client.clicks(url="https://example.com/blog/x?utm_source=linkedin", since=date(2026, 7, 1))


def test_clicks_sums_only_matching_url_rows(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"x": "/blog/x?utm_source=linkedin&utm_medium=social&utm_campaign=x", "y": 100},
                {"x": "/blog/x?utm_source=linkedin&utm_medium=social&utm_campaign=x", "y": 33},
                {"x": "/blog/x?utm_source=facebook&utm_medium=social&utm_campaign=x", "y": 999},
            ]

    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    client = HttpxUmamiClient(api_url="https://umami.test/", website_id="site-1", api_key="k")
    total = client.clicks(
        url="https://example.com/blog/x?utm_source=linkedin&utm_medium=social&utm_campaign=x",
        since=date(2026, 7, 1),
    )

    assert total == 133
    assert captured["url"] == "https://umami.test/api/websites/site-1/metrics"
    assert captured["headers"]["x-umami-api-key"] == "k"
    assert captured["params"]["type"] == "url"


def test_clicks_wraps_http_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    client = HttpxUmamiClient(api_url="https://umami.test", website_id="site-1", api_key="k")

    with pytest.raises(MetricsError, match="Umami metrics request failed"):
        client.clicks(url="https://example.com/blog/x", since=date(2026, 7, 1))
