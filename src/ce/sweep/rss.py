"""RSS 2.0 / Atom feed polling (TDD 12 WP-16). Stdlib `xml.etree.ElementTree`
only, no new dependency — same "a plain fetch doesn't need an SDK" precedent
as `harvest/research.py`'s `DuckDuckGoSearchClient` (HTML) and
`metrics/umami.py` (a bare REST endpoint).

Parses by local element name (`item`/`entry`, ignoring whichever XML
namespace prefix a given feed declares) rather than hardcoding one dialect,
so both RSS 2.0 (`<item><link>url</link></item>`) and Atom
(`<entry><link href="url"/></entry>`, e.g. Reddit's own `.rss` feeds, which
are actually Atom) parse through the same path. Not a faithful RSS/Atom
implementation — good enough to pull a title/link/timestamp per entry for
`sweep/scan.py`'s keyword matching, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from xml.etree import ElementTree

import httpx

from ce.exit_codes import SweepError


@dataclass(frozen=True)
class RssEntry:
    title: str
    link: str
    published_at: datetime | None


class RssClient(Protocol):
    def entries(self, feed_url: str) -> list[RssEntry]:
        """Every entry currently in `feed_url`'s feed."""
        ...


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _link(element: ElementTree.Element) -> str | None:
    """RSS: `<link>url</link>` (text content). Atom: one or more
    `<link href="url" rel="...">` elements — prefer `rel="alternate"`
    (or no `rel` at all), falling back to the first `href` present."""
    links = [child for child in element if _local_name(child.tag) == "link"]
    for link in links:
        if link.get("rel") in (None, "alternate") and link.get("href"):
            return link.get("href")
    for link in links:
        if link.get("href"):
            return link.get("href")
    for link in links:
        if link.text and link.text.strip():
            return link.text.strip()
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)  # RSS pubDate, RFC-822
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )  # Atom updated/published, ISO 8601
    except ValueError:
        return None


class HttpxRssClient:
    def __init__(self, *, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def entries(self, feed_url: str) -> list[RssEntry]:
        try:
            response = httpx.get(
                feed_url,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (content-engine sweep)"},
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            raise SweepError(f"RSS fetch failed for {feed_url}: {exc}") from exc

        results: list[RssEntry] = []
        for element in root.iter():
            if _local_name(element.tag) not in ("item", "entry"):
                continue
            title = _child_text(element, "title")
            link = _link(element)
            published_at = _parse_date(
                _child_text(element, "pubDate")
                or _child_text(element, "updated")
                or _child_text(element, "published")
            )
            if title and link:
                results.append(RssEntry(title=title, link=link, published_at=published_at))
        return results
