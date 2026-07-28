"""Site-click metrics via a self-hosted Umami instance (TDD 12 WP-15).

Umami has no official Python SDK (unlike the Anthropic/OpenAI/Gemini/
Perplexity clients elsewhere in this codebase) -- it's a single self-hosted
REST endpoint, not a maintained third-party API surface, so a plain httpx
GET is the right call, same shape as `harvest/research.py`'s
`DuckDuckGoSearchClient` (scraping a page has no SDK either).

Every rendition's UTM'd URL is already deterministic
(`produce/renditions.py::canonical_url` + `utm_url`, TDD 8's
`utm.template`) -- this module reuses those exact helpers rather than
re-deriving the query string a third time, so a click only counts if its
URL matches byte-for-byte what was actually published for that platform.

Umami's `/api/websites/{id}/metrics?type=url` endpoint returns per-URL
pageview counts (`[{x: "<pathname><search>", y: <count>}]`) for a time
window -- Umami's default tracking script records the full path + query
string as `x`, so comparing path+query (ignoring scheme/host, in case a
row happens to include either) is enough; no custom event tracking needed.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from ce.exit_codes import MetricsError


def _path_and_query(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


class UmamiClient(Protocol):
    def clicks(self, *, url: str, since: date) -> int:
        """Total pageviews recorded for `url` (matched on path+query) since
        `since` (inclusive), through now."""
        ...


class HttpxUmamiClient:
    """Real implementation, driven by `config.analytics.umami` (non-secret:
    api_url, website_id) plus `UMAMI_API_KEY` (environment-only, TDD §14).

    The API-key check stays lazy (on `clicks()`, not `__init__`) to match
    every other client in this codebase -- callers can construct this
    unconditionally without an unset key aborting a run that never ends up
    calling Umami (e.g. a `posted.yml` with zero records yet).
    """

    def __init__(
        self,
        *,
        api_url: str,
        website_id: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._website_id = website_id
        self._api_key = api_key or os.environ.get("UMAMI_API_KEY", "")
        self._timeout = timeout

    def clicks(self, *, url: str, since: date) -> int:
        if not self._api_key:
            raise MetricsError("UMAMI_API_KEY is not set", hint="ce doctor")

        start_at = int(datetime.combine(since, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
        end_at = int(datetime.now(UTC).timestamp() * 1000)

        try:
            response = httpx.get(
                f"{self._api_url}/api/websites/{self._website_id}/metrics",
                params={"type": "url", "startAt": start_at, "endAt": end_at},
                headers={"x-umami-api-key": self._api_key},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MetricsError(f"Umami metrics request failed: {exc}") from exc

        rows: list[dict[str, Any]] = response.json()
        target = _path_and_query(url)
        return sum(
            int(row.get("y", 0)) for row in rows if _path_and_query(row.get("x", "")) == target
        )
