"""WP-07 acceptance (TDD 12): external research returns >=3 usable sources
for a fixture topic; fetch failures degrade gracefully rather than
aborting the run.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import perplexity
import pytest

from ce.exit_codes import ResearchError
from ce.harvest import research as research_module
from ce.harvest.research import (
    SearchResult,
    Stance,
    _dedupe_by_domain,
    research,
)
from ce.llm.gateway import Gateway, ProviderResponse


class FakeSearchClient:
    def __init__(self, results: list[SearchResult]):
        self._results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        return self._results[:max_results]


class FakeFetchClient:
    def __init__(self, content_by_url: dict[str, str | None]):
        self._content = content_by_url
        self.calls: list[str] = []

    def fetch(self, url: str) -> str | None:
        self.calls.append(url)
        return self._content.get(url)


class FakeLLMClient:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, model, system, user, max_tokens):
        self.calls.append({"model": model, "system": system, "user": user})
        payload = self._responses.pop(0)
        return ProviderResponse(content=json.dumps(payload), in_tokens=10, out_tokens=10)


def _gateway(
    tmp_path: Path, make_engine_config, responses: list[dict]
) -> tuple[Gateway, FakeLLMClient]:
    client = FakeLLMClient(responses)
    gateway = Gateway(
        make_engine_config(),
        data_root=tmp_path / "data",
        prompts_dir=Path("prompts"),
        client=client,
    )
    return gateway, client


# ---------------------------------------------------------------------------
# dedupe by domain
# ---------------------------------------------------------------------------


def test_dedupe_by_domain_keeps_first_occurrence_per_domain():
    results = [
        SearchResult(url="https://blog.duckdb.org/a", title="A"),
        SearchResult(url="https://blog.duckdb.org/b", title="B"),  # same domain -- dropped
        SearchResult(url="https://news.ycombinator.com/x", title="X"),
        SearchResult(url="https://other.example.com/y", title="Y"),
    ]
    deduped = _dedupe_by_domain(results)
    assert [r.url for r in deduped] == [
        "https://blog.duckdb.org/a",
        "https://news.ycombinator.com/x",
        "https://other.example.com/y",
    ]


# ---------------------------------------------------------------------------
# research() — Done-when: >=3 usable sources; fetch failures degrade gracefully
# ---------------------------------------------------------------------------


def test_returns_at_least_three_usable_sources_despite_a_fetch_failure(
    tmp_path, make_engine_config
):
    results = [
        SearchResult(url="https://a.example.com/1", title="A"),
        SearchResult(url="https://b.example.com/1", title="B"),  # this one fails to fetch
        SearchResult(url="https://c.example.com/1", title="C"),
        SearchResult(url="https://d.example.com/1", title="D"),
    ]
    search_client = FakeSearchClient(results)
    fetch_client = FakeFetchClient(
        {
            "https://a.example.com/1": "DuckDB handles the join fine up to 40GB.",
            # "https://b.example.com/1" deliberately absent -- simulates a fetch failure
            "https://c.example.com/1": "Spark still wins for very large joins.",
            "https://d.example.com/1": "Anecdotal report of a similar migration.",
        }
    )
    gateway, llm_client = _gateway(
        tmp_path,
        make_engine_config,
        responses=[
            {"stance": "supports", "summary": "Confirms DuckDB handles the join."},
            {"stance": "contradicts", "summary": "Says Spark wins for large joins."},
            {"stance": "neutral", "summary": "An anecdotal, inconclusive report."},
        ],
    )

    harvest = research(
        "DuckDB replaces Spark for <100GB workloads",
        gateway=gateway,
        output_path=tmp_path / "harvest" / "research.json",
        max_sources=8,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    assert len(harvest.sources) == 3
    assert {s.url for s in harvest.sources} == {
        "https://a.example.com/1",
        "https://c.example.com/1",
        "https://d.example.com/1",
    }
    assert "https://b.example.com/1" in fetch_client.calls  # attempted, then skipped
    assert len(llm_client.calls) == 3  # never called for the failed fetch


def test_fetch_failure_does_not_abort_the_run(tmp_path, make_engine_config):
    """A URL that fails to fetch is skipped, not fatal (TDD 12 Done-when)."""
    results = [
        SearchResult(url="https://dead.example.com/1", title="Dead link"),
        SearchResult(url="https://alive.example.com/1", title="Alive"),
    ]
    search_client = FakeSearchClient(results)
    fetch_client = FakeFetchClient({"https://alive.example.com/1": "Some real content here."})
    gateway, _ = _gateway(
        tmp_path,
        make_engine_config,
        responses=[{"stance": "neutral", "summary": "Some real content."}],
    )

    harvest = research(
        "some topic",
        gateway=gateway,
        output_path=tmp_path / "harvest" / "research.json",
        max_sources=8,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    assert len(harvest.sources) == 1
    assert harvest.sources[0].url == "https://alive.example.com/1"


def test_stops_once_max_sources_reached(tmp_path, make_engine_config):
    results = [SearchResult(url=f"https://s{i}.example.com/1", title=f"S{i}") for i in range(6)]
    search_client = FakeSearchClient(results)
    fetch_client = FakeFetchClient({r.url: f"content for {r.title}" for r in results})
    gateway, llm_client = _gateway(
        tmp_path,
        make_engine_config,
        responses=[{"stance": "neutral", "summary": "x"} for _ in range(2)],
    )

    harvest = research(
        "some topic",
        gateway=gateway,
        output_path=tmp_path / "harvest" / "research.json",
        max_sources=2,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    assert len(harvest.sources) == 2
    assert len(llm_client.calls) == 2
    # only the first two candidates were ever fetched -- the rest weren't needed
    assert fetch_client.calls == ["https://s0.example.com/1", "https://s1.example.com/1"]


def test_all_fetches_failing_yields_an_empty_but_valid_harvest(tmp_path, make_engine_config):
    results = [SearchResult(url="https://dead.example.com/1", title="Dead")]
    search_client = FakeSearchClient(results)
    fetch_client = FakeFetchClient({})  # every fetch fails
    gateway, llm_client = _gateway(tmp_path, make_engine_config, responses=[])

    harvest = research(
        "some topic",
        gateway=gateway,
        output_path=tmp_path / "harvest" / "research.json",
        max_sources=8,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    assert harvest.sources == []
    assert len(llm_client.calls) == 0
    assert (tmp_path / "harvest" / "research.json").exists()


def test_writes_research_json_with_expected_shape(tmp_path, make_engine_config):
    results = [SearchResult(url="https://a.example.com/1", title="A")]
    search_client = FakeSearchClient(results)
    fetch_client = FakeFetchClient({"https://a.example.com/1": "Some content."})
    gateway, _ = _gateway(
        tmp_path,
        make_engine_config,
        responses=[{"stance": "supports", "summary": "It supports the hypothesis."}],
    )
    harvest_dir = tmp_path / "harvest"

    research(
        "some topic",
        gateway=gateway,
        output_path=harvest_dir / "research.json",
        max_sources=8,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    data = json.loads((harvest_dir / "research.json").read_text(encoding="utf-8"))
    [source] = data["sources"]
    assert set(source.keys()) == {"url", "title", "fetched_at", "summary", "stance"}
    assert source["stance"] == "supports"
    assert source["url"] == "https://a.example.com/1"


def test_search_is_overfetched_beyond_max_sources_to_survive_dedupe_and_failures(
    tmp_path, make_engine_config
):
    results = [SearchResult(url=f"https://s{i}.example.com/1", title=f"S{i}") for i in range(6)]
    search_client = FakeSearchClient(results)
    fetch_client = FakeFetchClient({})
    gateway, _ = _gateway(tmp_path, make_engine_config, responses=[])

    research(
        "some topic",
        gateway=gateway,
        output_path=tmp_path / "harvest" / "research.json",
        max_sources=2,
        search_client=search_client,
        fetch_client=fetch_client,
    )

    # asked for more than max_sources so a run of fetch failures doesn't
    # starve the result set
    assert search_client.calls == [("some topic", 6)]


def test_stance_enum_accepts_all_schema_values():
    assert {s.value for s in Stance} == {"supports", "contradicts", "neutral"}


# ---------------------------------------------------------------------------
# Swappable search providers (Gemini grounded search, Perplexity) — both
# official SDKs, so fakes are installed on the lazily-built `_get_client()`
# rather than at the HTTP layer (same shape as
# test_index.py::test_openai_embeddings_client_wraps_http_errors_readably).
# ---------------------------------------------------------------------------


class _FakeGenaiModels:
    def __init__(self, *, response=None, exc=None, captured=None):
        self._response = response
        self._exc = exc
        self.captured = captured if captured is not None else {}

    def generate_content(self, *, model, contents, config):
        self.captured["model"] = model
        self.captured["contents"] = contents
        self.captured["config"] = config
        if self._exc is not None:
            raise self._exc
        return self._response


def _gemini_response(chunks: list) -> SimpleNamespace:
    return SimpleNamespace(
        candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=chunks))]
    )


def test_gemini_grounded_search_parses_grounding_chunks():
    chunks = [
        SimpleNamespace(web=SimpleNamespace(uri="https://a.example.com/1", title="A")),
        SimpleNamespace(web=SimpleNamespace(uri="https://b.example.com/1", title="B")),
        SimpleNamespace(web=None),  # no web key -- must be skipped, not crash
    ]
    models = _FakeGenaiModels(response=_gemini_response(chunks))
    client = research_module.GeminiGroundedSearchClient(api_key="test-key")
    client._get_client = lambda: SimpleNamespace(models=models)

    results = client.search("DuckDB vs Spark", max_results=10)

    assert [r.url for r in results] == ["https://a.example.com/1", "https://b.example.com/1"]
    assert [r.title for r in results] == ["A", "B"]
    assert models.captured["contents"] == "DuckDB vs Spark"
    assert models.captured["model"] == "gemini-3.5-flash"
    tool = models.captured["config"].tools[0]
    assert isinstance(tool.google_search, research_module.genai_types.GoogleSearch)


def test_gemini_respects_max_results():
    chunks = [
        SimpleNamespace(web=SimpleNamespace(uri=f"https://s{i}.example.com/1", title=f"S{i}"))
        for i in range(5)
    ]
    models = _FakeGenaiModels(response=_gemini_response(chunks))
    client = research_module.GeminiGroundedSearchClient(api_key="test-key")
    client._get_client = lambda: SimpleNamespace(models=models)

    results = client.search("q", max_results=2)
    assert len(results) == 2


def test_gemini_missing_api_key_raises():
    client = research_module.GeminiGroundedSearchClient(api_key="")
    with pytest.raises(ResearchError, match="GEMINI_API_KEY"):
        client.search("q", max_results=5)


def test_gemini_search_wraps_api_errors_readably():
    """Without wrapping, an SDK error surfaces as a raw traceback with no
    visible status code or API error message (same class of regression as
    `OpenAITranscriptionClient` -- see test_capture_audio.py)."""
    api_error = research_module.genai_errors.APIError(
        429, {"message": "Rate limited", "status": "RESOURCE_EXHAUSTED"}
    )
    models = _FakeGenaiModels(exc=api_error)
    client = research_module.GeminiGroundedSearchClient(api_key="test-key")
    client._get_client = lambda: SimpleNamespace(models=models)

    with pytest.raises(ResearchError, match="429") as excinfo:
        client.search("q", max_results=5)
    assert "Rate limited" in excinfo.value.message


class _FakePerplexityCompletions:
    def __init__(self, *, response=None, exc=None, captured=None):
        self._response = response
        self._exc = exc
        self.captured = captured if captured is not None else {}

    def create(self, *, model, messages):
        self.captured["model"] = model
        self.captured["messages"] = messages
        if self._exc is not None:
            raise self._exc
        return self._response


def _fake_perplexity_client(completions: _FakePerplexityCompletions) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_perplexity_search_uses_search_results_field():
    response = SimpleNamespace(
        search_results=[
            SimpleNamespace(url="https://a.example.com/1", title="A"),
            SimpleNamespace(url="https://b.example.com/1", title="B"),
        ],
        citations=["https://a.example.com/1", "https://b.example.com/1"],
    )
    completions = _FakePerplexityCompletions(response=response)
    client = research_module.PerplexitySearchClient(api_key="test-key")
    client._get_client = lambda: _fake_perplexity_client(completions)

    results = client.search("DuckDB vs Spark", max_results=10)

    assert [r.title for r in results] == ["A", "B"]
    assert [r.url for r in results] == ["https://a.example.com/1", "https://b.example.com/1"]
    assert completions.captured["model"] == "sonar"
    assert completions.captured["messages"] == [{"role": "user", "content": "DuckDB vs Spark"}]


def test_perplexity_falls_back_to_bare_citations_when_no_search_results():
    response = SimpleNamespace(search_results=None, citations=["https://a.example.com/1"])
    completions = _FakePerplexityCompletions(response=response)
    client = research_module.PerplexitySearchClient(api_key="test-key")
    client._get_client = lambda: _fake_perplexity_client(completions)

    results = client.search("q", max_results=10)

    assert results == [SearchResult(url="https://a.example.com/1", title="https://a.example.com/1")]


def test_perplexity_missing_api_key_raises():
    client = research_module.PerplexitySearchClient(api_key="")
    with pytest.raises(ResearchError, match="PERPLEXITY_API_KEY"):
        client.search("q", max_results=5)


def test_perplexity_search_wraps_api_errors_readably():
    request = httpx.Request("POST", "https://api.perplexity.ai/chat/completions")
    response = httpx.Response(429, request=request)
    api_error = perplexity.APIStatusError("Rate limited", response=response, body=None)
    completions = _FakePerplexityCompletions(exc=api_error)
    client = research_module.PerplexitySearchClient(api_key="test-key")
    client._get_client = lambda: _fake_perplexity_client(completions)

    with pytest.raises(ResearchError, match="429") as excinfo:
        client.search("q", max_results=5)
    assert "Rate limited" in excinfo.value.message


def test_build_search_client_dispatches_by_provider():
    assert isinstance(
        research_module.build_search_client("duckduckgo"), research_module.DuckDuckGoSearchClient
    )
    assert isinstance(
        research_module.build_search_client("gemini", api_key="x"),
        research_module.GeminiGroundedSearchClient,
    )
    assert isinstance(
        research_module.build_search_client("perplexity", api_key="x"),
        research_module.PerplexitySearchClient,
    )


def test_build_search_client_rejects_unknown_provider():
    with pytest.raises(ResearchError, match="unknown research provider"):
        research_module.build_search_client("bing")
