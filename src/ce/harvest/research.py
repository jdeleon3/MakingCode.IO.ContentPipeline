"""External research (TDD 12 WP-07): search a topic, fetch pages, and have
an LLM extract a summary + stance for each — written to `harvest/research.json`.

Search and fetch are reached through `SearchClient`/`FetchClient` Protocols
(same DI shape as every external-API seam in this codebase: WP-02's
`LLMClient`, WP-04's `TranscriptionClient`, WP-06's `EmbeddingsClient`).
TDD 12 names no search provider for this module at all — unlike WP-02/
WP-04's "no *second* provider specified" gap (a first provider was named;
dispatch for a hypothetical second just isn't built), there isn't even a
first one specified here.

Three concrete `SearchClient`s are implemented, swappable via
`config.harvest.research.provider` and `build_search_client()`:

- `GeminiGroundedSearchClient` — the default. Official `google-genai` SDK
  (matches `gateway.py`'s `AnthropicClient` / `index.py`'s
  `OpenAIEmbeddingsClient`: prefer the official SDK when a provider has
  one). Gemini's "grounding with Google Search" tool: the model researches
  the query itself; `search()` adapts the response's
  `grounding_metadata.grounding_chunks` (web citations) into
  `SearchResult`s rather than treating the synthesized answer as one
  source. Needs `GEMINI_API_KEY` (required in `ce doctor` as of WP-07,
  since it's the default).
- `DuckDuckGoSearchClient` — no API key, a plain ranked link list scraped
  from the no-JS HTML results page (stdlib `html.parser`, no new
  dependency). A zero-config fallback (keeps TDD 2.4 S3's $20/month budget
  intact) for anyone who'd rather not set up a Gemini key. DuckDuckGo has
  no API/SDK at all here — this is screen-scraping its HTML results page,
  so there's no official client to switch to.
- `PerplexitySearchClient` — official `perplexityai` SDK. An online/Sonar
  model with built-in web search; `search()` adapts `search_results` (or,
  on older API responses, bare `citations` URLs) the same way. Needs
  `PERPLEXITY_API_KEY` — never required in `ce doctor`, since it's an
  alternative, not the default.

`research()` itself only ever depends on the `SearchClient` Protocol, never
on which provider is selected — callers (`ce harvest`, WP-08) build a
client via `build_search_client(config.harvest.research.provider)` and
inject it. Automated tests inject fakes for all three rather than hitting
the network, for the same determinism reason WP-02's Anthropic client is
never exercised by the automated suite either.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
import perplexity
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from ce.exit_codes import ResearchError
from ce.llm.gateway import Gateway

_CONTENT_CHARS_TO_LLM = 4000


# ---------------------------------------------------------------------------
# Search — three swappable providers (see module docstring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str = ""


class SearchClient(Protocol):
    def search(self, query: str, *, max_results: int) -> list[SearchResult]: ...


class _DuckDuckGoResultParser(HTMLParser):
    """Extracts `(url, title)` pairs from DuckDuckGo's no-JS HTML results
    page: `<a class="result__a" href="...">title</a>`."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._in_result_link = False
        self._href = ""
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and dict(attrs).get("class") == "result__a":
            self._in_result_link = True
            self._href = dict(attrs).get("href", "") or ""
            self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_result_link:
            self._in_result_link = False
            title = "".join(self._title_parts).strip()
            if self._href and title:
                self.results.append((self._href, title))


class DuckDuckGoSearchClient:
    _URL = "https://html.duckduckgo.com/html/"

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        response = httpx.get(
            self._URL,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (content-engine research)"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        parser = _DuckDuckGoResultParser()
        parser.feed(response.text)
        return [SearchResult(url=url, title=title) for url, title in parser.results[:max_results]]


class GeminiGroundedSearchClient:
    """Official `google-genai` SDK, driving Gemini's "grounding with Google
    Search" tool: the model researches the query and returns web citations
    in `grounding_metadata`, which this adapts into a plain `SearchResult`
    list. There's no independent snippet (Gemini doesn't expose one
    per-citation), so `snippet` stays empty.

    The API-key check stays lazy (on `search()`, not `__init__`) to match
    every other client in this codebase — `build_search_client()` can
    construct this unconditionally without an unset key aborting a run
    that never ends up calling Gemini.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-3.5-flash",
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model = model
        self._timeout = timeout
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if not self._api_key:
            raise ResearchError("GEMINI_API_KEY is not set", hint="ce doctor")
        if self._client is None:
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=genai_types.HttpOptions(timeout=int(self._timeout * 1000)),
            )
        return self._client

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        client = self._get_client()
        try:
            response = client.models.generate_content(
                model=self._model,
                contents=query,
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
                ),
            )
        except genai_errors.APIError as exc:
            raise ResearchError(f"Gemini search request failed ({exc.code}): {exc.message}") from exc

        results: list[SearchResult] = []
        candidates = response.candidates or []
        grounding = candidates[0].grounding_metadata if candidates else None
        chunks = grounding.grounding_chunks if grounding and grounding.grounding_chunks else []
        for chunk in chunks:
            web = chunk.web
            if web and web.uri and web.title:
                results.append(SearchResult(url=web.uri, title=web.title))
        return results[:max_results]


class PerplexitySearchClient:
    """Official `perplexityai` SDK. An online/Sonar Perplexity model
    searches the web as part of answering; `search()` adapts the
    response's `search_results` (title + url, current API) or bare
    `citations` (url only, older API) into `SearchResult`s, rather than
    treating the synthesized answer as a single source.

    The API-key check stays lazy (on `search()`, not `__init__`) — see
    `GeminiGroundedSearchClient` above for why.
    """

    def __init__(
        self, *, api_key: str | None = None, model: str = "sonar", timeout: float = 90.0
    ) -> None:
        self._api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self._model = model
        self._timeout = timeout
        self._client: perplexity.Perplexity | None = None

    def _get_client(self) -> perplexity.Perplexity:
        if not self._api_key:
            raise ResearchError("PERPLEXITY_API_KEY is not set", hint="ce doctor")
        if self._client is None:
            self._client = perplexity.Perplexity(api_key=self._api_key, timeout=self._timeout)
        return self._client

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=self._model, messages=[{"role": "user", "content": query}]
            )
        except perplexity.APIStatusError as exc:
            raise ResearchError(
                f"Perplexity search request failed ({exc.status_code}): {exc.message}"
            ) from exc

        search_results = response.search_results or []
        if search_results:
            results = [
                SearchResult(url=r.url, title=r.title or r.url) for r in search_results if r.url
            ]
        else:
            results = [SearchResult(url=url, title=url) for url in (response.citations or [])]
        return results[:max_results]


def build_search_client(provider: str, **kwargs: Any) -> SearchClient:
    """Picks a concrete `SearchClient` by name
    (`config.harvest.research.provider`) — the one place that knows all
    three exist. `research()` never imports a provider class directly.
    """
    if provider == "duckduckgo":
        return DuckDuckGoSearchClient(**kwargs)
    if provider == "gemini":
        return GeminiGroundedSearchClient(**kwargs)
    if provider == "perplexity":
        return PerplexitySearchClient(**kwargs)
    raise ResearchError(f"unknown research provider: {provider!r}")


# ---------------------------------------------------------------------------
# Fetch — degrades gracefully on failure (TDD 12 WP-07 Done-when)
# ---------------------------------------------------------------------------


class FetchClient(Protocol):
    def fetch(self, url: str) -> str | None:
        """Returns page text, or `None` on any failure."""
        ...


class _TextExtractor(HTMLParser):
    """Strips tags to plain text — good enough to feed a page's visible
    content to `research_stance`; not a faithful readability extraction."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def text(self) -> str:
        return " ".join(self._parts)


class HttpFetchClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def fetch(self, url: str) -> str | None:
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (content-engine research)"},
                timeout=self._timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        extractor = _TextExtractor()
        extractor.feed(response.text)
        return extractor.text()


# ---------------------------------------------------------------------------
# research.json output
# ---------------------------------------------------------------------------


class Stance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class ResearchSource(BaseModel):
    url: str
    title: str
    fetched_at: datetime
    summary: str
    stance: Stance


class ResearchHarvest(BaseModel):
    sources: list[ResearchSource]


def _load_schema(prompts_dir: Path) -> dict[str, Any]:
    schema_path = prompts_dir / "_schemas" / "research_stance.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _dedupe_by_domain(results: list[SearchResult]) -> list[SearchResult]:
    """TDD 12 WP-07: "dedupe by domain" — keeps each result's search-rank
    order, dropping any result whose domain already appeared."""
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        domain = urlparse(result.url).netloc.lower()
        if domain in seen:
            continue
        seen.add(domain)
        deduped.append(result)
    return deduped


def _write_research_json(path: Path, harvest: ResearchHarvest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(harvest.model_dump_json(indent=2), encoding="utf-8")


def research(
    query: str,
    *,
    gateway: Gateway,
    harvest_dir: Path,
    max_sources: int,
    search_client: SearchClient | None = None,
    fetch_client: FetchClient | None = None,
    now: datetime | None = None,
) -> ResearchHarvest:
    """Searches `query`, fetches deduped-by-domain results in rank order,
    and stops once `max_sources` pages have been successfully fetched and
    summarized. A fetch failure (network error, empty page) is skipped —
    not aborted — so one dead link doesn't sink the whole run (TDD 12
    WP-07 Done-when).
    """
    search_client = search_client or DuckDuckGoSearchClient()
    fetch_client = fetch_client or HttpFetchClient()
    schema = _load_schema(gateway.prompts_dir)
    now = now or datetime.now(UTC)

    # Overfetch: not every search hit survives dedupe or a successful fetch,
    # so asking for exactly `max_sources` results would starve the run on
    # the first dead link.
    candidates = _dedupe_by_domain(search_client.search(query, max_results=max_sources * 3))

    sources: list[ResearchSource] = []
    for candidate in candidates:
        if len(sources) >= max_sources:
            break
        content = fetch_client.fetch(candidate.url)
        if not content or not content.strip():
            continue

        result = gateway.complete(
            "research_stance",
            {
                "hypothesis": query,
                "title": candidate.title,
                "url": candidate.url,
                "content": content[:_CONTENT_CHARS_TO_LLM],
            },
            schema=schema,
            tier="cheap",
        )
        sources.append(
            ResearchSource(
                url=candidate.url,
                title=candidate.title,
                fetched_at=now,
                summary=result.parsed["summary"],
                stance=Stance(result.parsed["stance"]),
            )
        )

    harvest = ResearchHarvest(sources=sources)
    _write_research_json(harvest_dir / "research.json", harvest)
    return harvest
