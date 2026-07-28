"""Hacker News signal source (TDD 12 WP-16), via the Algolia HN Search API
(`https://hn.algolia.com/api/v1/search` — public, no auth, no API key). A
plain `httpx` GET is the right call here, same "no SDK exists for this, it's
one endpoint" precedent as `metrics/umami.py` and `harvest/research.py`'s
`DuckDuckGoSearchClient`.

Reached through the `HNClient` Protocol (same DI shape as every other
external-API seam in this codebase) so `sweep/scan.py` never imports
`AlgoliaHNClient` directly and tests can inject a fake instead of hitting
the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

import httpx

from ce.exit_codes import SweepError

_ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


@dataclass(frozen=True)
class HNHit:
    title: str
    url: str
    points: int
    num_comments: int
    created_at: datetime


class HNClient(Protocol):
    def search(self, query: str, *, since: date) -> list[HNHit]:
        """Story hits matching `query`, created on or after `since`."""
        ...


class AlgoliaHNClient:
    def __init__(self, *, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def search(self, query: str, *, since: date) -> list[HNHit]:
        since_ts = int(datetime.combine(since, datetime.min.time(), tzinfo=UTC).timestamp())
        try:
            response = httpx.get(
                _ALGOLIA_SEARCH_URL,
                params={
                    "query": query,
                    "tags": "story",
                    "numericFilters": f"created_at_i>={since_ts}",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SweepError(f"HN search for {query!r} failed: {exc}") from exc

        hits = response.json().get("hits", [])
        results: list[HNHit] = []
        for hit in hits:
            object_id = hit.get("objectID")
            results.append(
                HNHit(
                    title=hit.get("title") or "",
                    url=hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
                    points=int(hit.get("points") or 0),
                    num_comments=int(hit.get("num_comments") or 0),
                    created_at=datetime.fromtimestamp(hit["created_at_i"], tz=UTC),
                )
            )
        return results
