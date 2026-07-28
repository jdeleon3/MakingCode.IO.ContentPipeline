# Implementation Status

**Project:** Content Engine (`ce`)
**Spec:** `docs/TDD-content-engine.md`
**Last session:** 2026-07-27 — completed WP-08

---

## Read this first

1. Read TDD §0–§3 for orientation (~5 min).
2. Find the next 🔵 row below.
3. Read that work package's spec in TDD §12, and only the sections it references.
4. Implement. Run its acceptance criteria. Update this file. Commit.

**Rules:** one WP per session · do not start the next until acceptance passes ·
`ce --help` must always run · record every deviation below.

---

## Work packages

| WP | Name | Status | Notes |
|----|------|--------|-------|
| WP-00 | Scaffold, CLI skeleton, doctor | ✅ done | 62 tests passing |
| WP-01 | Config, models, store | ✅ done | 100 tests passing (38 new) |
| WP-02 | LLM gateway | ✅ done | 131 tests passing (31 new); `ANTHROPIC_API_KEY` now required in `doctor.py` |
| WP-03 | Project lifecycle | ✅ done | 155 tests passing (24 new) |
| WP-04 | Capture & transcription | ✅ done | 188 tests passing (33 new); `ffmpeg`/`OPENAI_API_KEY` now required in `doctor.py` |
| WP-05 | Git harvest & safety gates ⚠️ | ✅ done | 225 tests passing (37 new); `gitleaks` now required in `doctor.py` |
| WP-06 | Index & dedupe | ✅ done | 240 tests passing (15 new); added `numpy` dependency |
| WP-07 | External research | ✅ done | 261 tests passing (21 new); swappable search: gemini (default) / duckduckgo / perplexity; `GEMINI_API_KEY` now required in `doctor.py` |
| WP-08 | Inventory generator (MATCH) ⭐ | ✅ done | 279 tests passing (18 new); **MVP milestone** — usable system after this |
| WP-09 | Writer & grader | 🔵 **next** | |
| WP-10 | Claim verification | ⬜ | |
| WP-11 | Asset pipeline | ⬜ | flip `mermaid-cli`, `playwright` to required |
| WP-12 | Renditions | ⬜ | |
| WP-13 | Packager & REVIEW.html | ⬜ | |
| WP-14 | Site publish | ⬜ | |
| WP-15 | Post-back & metrics | ⬜ | |
| WP-16 | Trend sweep | ⬜ | independent after WP-02 |

**Critical path:** 00 → 01 → 02 → 05 → 08 → 09 → 12 → 13

---

## Deviations from the TDD

- **2026-07-28 (post-WP-08, cross-cutting) · every provider client with an
  official SDK now uses it, not hand-rolled `httpx`, reversing WP-02's/
  WP-04's/WP-07's original "one POST doesn't justify an SDK dependency"
  deviations.** `AnthropicClient` (`llm/gateway.py`) and the OpenAI-based
  clients (`OpenAITranscriptionClient`, `OpenAIEmbeddingsClient`) moved
  first, forced by two things:
  1. **A real production bug.** `Gateway._call_with_retry` only caught
     `httpx.HTTPStatusError` (429/5xx) — a `ReadTimeout` is a different
     exception class and was never retried at all, so one slow response on
     a large reasoning-tier `brief_generate` call killed the whole
     `ce harvest` run outright. Bumping the timeout number alone (30s →
     120s → 600s) only delays the same failure; the SDK's streaming call
     (`messages.stream()` + `get_final_message()`) fixes it structurally —
     a read timeout is per-chunk, so periodic bytes keep the connection
     alive regardless of total generation time, unlike a synchronous POST
     that blocks with zero bytes until the entire response is ready.
  2. **An explicit decision to prefer official SDKs when a provider has
     one**, made that session.
  `Gateway._call_with_retry` now catches `anthropic.APIStatusError` /
  `anthropic.APIConnectionError` instead of the `httpx` equivalents — this
  couples retry logic to the Anthropic SDK's exception hierarchy, which
  isn't new coupling in practice (Gateway was already Anthropic-only; see
  the existing "Gateway never branches on `config.llm.provider`" note).
  Flagged as a follow-up rather than migrated blind in that same session:
  `harvest/research.py`'s `GeminiGroundedSearchClient`/
  `PerplexitySearchClient` were left on hand-rolled httpx (WP-07 code from a
  different session). **Follow-up completed this session:** both now use
  their official SDKs — `google-genai` (`google.genai.Client.models
  .generate_content()`, grounding via `Tool(google_search=GoogleSearch())`,
  citations read from `response.candidates[0].grounding_metadata
  .grounding_chunks`) and `perplexityai` (`perplexity.Perplexity.chat
  .completions.create()`, an OpenAI-shaped client — same Stainless codegen
  as the `openai` SDK, right down to `APIStatusError.status_code`/
  `.message`). Both new clients wrap SDK errors into `ResearchError` on the
  way out, matching `OpenAIEmbeddingsClient`/`OpenAITranscriptionClient`
  (not `AnthropicClient`, which leaves errors unwrapped for `Gateway`'s own
  retry loop to catch — there's no equivalent retry wrapper here, so
  wrapping happens in the client itself). `DuckDuckGoSearchClient`/
  `HttpFetchClient` stay on `httpx` — DuckDuckGo has no real API/SDK at all
  (it's HTML scraping), and there's nothing to switch a plain page-text GET
  to either. Added `google-genai>=1.0` and `perplexityai>=0.40` to
  `pyproject.toml`. `tests/test_harvest_research.py`'s Gemini/Perplexity
  fakes moved from monkeypatching `httpx.post` to installing a fake on the
  client's lazily-built `_get_client()`, matching
  `test_index.py::test_openai_embeddings_client_wraps_http_errors_readably`'s
  pattern. In passing, fixed a pre-existing test bug unrelated to this
  migration: `test_gemini_grounded_search_parses_grounding_chunks` asserted
  `"gemini-2.0-flash" in url` against a client whose actual default model
  was `"gemini-3.5-flash"` — model-name drift from before this session,
  caught because the new fakes assert the model argument directly instead
  of substring-matching a URL.

- **WP-08 · `briefs.schema.json` omits `id`/`project`/`status`/
  `dedupe_max_similarity` — assigned by `harvest/inventory.py` after
  generation, not trusted to the model.** TDD 10.4 doesn't specify the
  schema's exact shape, only that output validates against it. Sequential
  IDs (`br-01`, `br-02`, ...), which project a run is for, the initial
  `status` (always `candidate` pre-processing), and the dedupe score (not
  knowable until *after* generation, since it depends on the published
  back-catalog) are all deterministic bookkeeping — mirrors
  `store.generate_capture_id`'s collision-safe-in-code approach from WP-04
  rather than trusting an LLM to get IDs/status right.

- **WP-08 · `ce brief select`'s actual CLI command (creating a `Piece`) is
  still WP-09's job; only the "refuses a dropped brief" rule
  (`inventory.assert_selectable`) is built and tested here.** TDD 12's
  WP-08 Done-when line says "`ce brief select` refuses them", but
  `cli.py`'s own `EXPECTED_WP` mapping (predates this session) already put
  `("brief","select")` under WP-09, since promoting a brief to a `Piece`
  touches `produce/`, out of `harvest/inventory.py`'s scope. Same split
  WP-01 used for `ce project show`: build the logic where its data lives,
  wire the CLI command in the WP that owns the rest of that command's
  behavior.

- **WP-08 · `gates/dedupe.py`'s `max_similarity()` is called per-brief for
  *annotation*, not `check()` for a hard block.** TDD 6.3 describes G3 as
  blocking; here, one brief scoring above threshold marks *that brief*
  `dropped` with a `risk_flags` note naming the collision and the run
  continues to the next brief — raising `GateBlocked` and aborting the
  whole 6-8-brief batch over one collision would defeat the point of
  generating alternatives. `ce brief select` (WP-09) is a different call
  site — a single brief being promoted — where a hard `check()`-and-raise
  is the right shape; both call sites share the same `max_similarity()`
  scan.

- **WP-08 · `ce harvest --force` is accepted (TDD 9's CLI contract) but not
  yet meaningfully enforced.** Neither WP-05's `git.extract()` nor WP-07's
  `research()` implement stage-level resumability internally, so there's
  no "unchanged inputs, skip" state for `--force` to bypass yet. Revisit
  once a manifest scheme is designed for the whole harvest stage; noted in
  `cli.py`'s `harvest()` docstring.

- **WP-08 · "recent published" dedupe context uses each piece's first
  non-blank `article.md` line as its "one-line summary".** TDD 10.4 asks
  for "titles + one-line summaries" of the last 90 days of published
  pieces, but neither `Piece` nor `Brief` has a dedicated summary field
  (TDD 5.2) — title comes from the originating `Brief.title` (`Piece`
  itself has no title), and the summary is pragmatically the article's own
  opening line rather than a new LLM call just to produce one.

- **WP-07 · three swappable search providers implemented
  (`GeminiGroundedSearchClient`/`DuckDuckGoSearchClient`/
  `PerplexitySearchClient`), selected via a new
  `config.harvest.research.provider` field and `research.build_search_client()`
  — TDD 12's Build line names no search provider at all.** Unlike WP-02/04's
  "no *second* provider specified" gap (a first provider was named;
  dispatch for a hypothetical second just isn't built), there wasn't even
  a first one specified here, so this is a genuine addition, not a
  dispatch-completion. `gemini` (grounding-with-Google-Search) is the
  **default** (operator choice, made explicit during this session —
  `GEMINI_API_KEY` is accordingly now required in `doctor.py`, same as
  WP-04 flipping `OPENAI_API_KEY`). `duckduckgo` (scraped from the no-JS
  HTML results page via stdlib `html.parser`, no new dependency) remains
  available as a zero-config, no-API-key fallback — keeping TDD 2.4 S3's
  $20/month budget intact for anyone who picks it. `perplexity` (Sonar
  online models; needs `PERPLEXITY_API_KEY`) is a third option, never
  added to `doctor.py`'s required-flags table since it's an alternative,
  not the default. `gemini`/`perplexity` are both adapters over an
  answer-with-citations API, not a plain ranked link list — `search()`
  extracts `SearchResult`s from each response's citation metadata
  (`groundingChunks` / `search_results`/`citations`) rather than treating
  the synthesized answer as one source. `research()` itself only depends
  on the `SearchClient` Protocol; automated tests inject fakes for all
  three rather than hitting the network, for the same determinism reason
  WP-02's `AnthropicClient` isn't exercised by the test suite either — not
  because anything is missing from this machine, just to keep tests
  fast/free/deterministic.

- **WP-07 · `_dedupe_by_domain` dedupes on exact host
  (`urlparse(url).netloc`), not registrable domain (eTLD+1).** TDD 12
  says "dedupe by domain" without defining the term. Exact-host dedupe
  means `blog.example.com` and `docs.example.com` count as different
  domains and can both appear — a deliberate choice (avoids a public-
  suffix-list dependency for marginal benefit at this system's source
  count), not an oversight, but worth flagging as the narrower of two
  reasonable readings.

- **WP-06 · `gates/dedupe.py`'s `check()`/`max_similarity()` take a
  precomputed embedding (`np.ndarray`) plus an open `sqlite3.Connection`,
  not text + an `EmbeddingsClient` + an index path.** TDD 12's Build line
  only names the module, not a signature. Splitting the embed step out
  means a caller that already has the candidate's embedding (or needs the
  raw `dedupe_max_similarity` score for a brief that isn't blocked — TDD
  10.4) never re-embeds the same text twice for two different questions.
  WP-08/09 (the actual callers) own turning `--force` into "skip calling
  this at all"; the gate itself has no bypass logic, same shape as G1/G2.

- **WP-06 · `index.py`'s embeddings client is reached through an
  `EmbeddingsClient` Protocol (`OpenAIEmbeddingsClient` for real, a fake in
  tests), same DI shape as every other external-API seam in this
  codebase.** Not a hard requirement here the way ffmpeg/gitleaks were in
  WP-04/05 — nothing prevents live OpenAI calls in this environment
  (`OPENAI_API_KEY` is already required since WP-04) — but a live network
  call in every test run would be slow, costly, and nondeterministic.
  The fake (`tests/conftest.py`'s `FakeHashingEmbeddingsClient`) does real
  bag-of-words hashing against actual text content rather than returning a
  canned vector, so the Done-when thresholds (near-identical >0.9,
  unrelated <0.5) are genuinely exercised, not asserted against a rigged
  response.

- **WP-06 · added `numpy` as a runtime dependency (`pyproject.toml`).**
  ADR-003 explicitly calls for embeddings "stored as a numpy array" with
  brute-force cosine similarity; the TDD's dependency list in WP-00's Build
  line predates this ADR being acted on. No other WP's `--Done when--`
  criteria are affected.

- **WP-05 · `harvest/git.py`'s `git.json` is `{"repos": [...]}`, one entry
  per `project.repos`, not the single flat object TDD 10.3's example
  shows.** `Project.repos` (WP-01) is a list precisely because a project
  can harvest more than one repo (TDD 5.2's `client-thing` example) — the
  TDD's literal flat shape has nowhere to put a second one. Every field
  10.3 names (`repo`, `range`, `total_commits`, `kept`, `dropped`,
  `commits`, `redaction`) is present unchanged, one level down inside each
  `RepoHarvest`.

- **WP-05 · `gitleaks` is reached through a `SecretScanner` Protocol
  (`gates/secrets.py`), tested via a fake; the real `GitleaksScanner` is
  exercised only manually.** Same shape and same reason as WP-04's
  ffmpeg/transcription seams: this dev/build environment has no `gitleaks`
  binary at all (confirmed via `ce doctor`), so the automated suite can't
  invoke it regardless of preference. The mandatory planted-secret test
  (TDD 12/13) still proves real detection: the fake scanner does actual
  regex matching (`AKIA[0-9A-Z]{16}`) against real file content in a real,
  throwaway fixture repo, not a scripted "yes, blocked" response. `git`
  itself **is** installed here, so `git log` parsing, the deny-list filter,
  and significance scoring all run for real, unfaked.

- **WP-05 · the deny-list (TDD 6.2) is enforced as "does any path component
  match this glob", not literal whole-path glob matching.** Every pattern
  in the fixed list (`.env*`, `secrets/`, `**/fixtures/**`, etc.) reduces to
  exactly one meaningful path segment once directory markers and `**`
  traversal segments are stripped — there's nothing in the list that needs
  to match more than one component at a time, so `gates/secrets.py`'s
  `is_denied()` checks each path component against that reduced set via
  `fnmatch` rather than hand-rolling `**`-aware regex translation.

- **WP-05 · the 30-commit significance-scoring golden fixture (TDD 12/13)
  is a real git repo built at test time
  (`tests/test_harvest_git.py::_build_significance_fixture`), not a
  committed `.git` directory under `tests/fixtures/`.** A nested `.git`
  checked into this repo would be tracked as an embedded-repo gitlink
  rather than real content unless deliberately set up as a submodule —
  building it programmatically with controlled commit dates
  (`GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`) is both simpler and lets the test
  control exact gaps between commits (needed for the `war_story`/reversal
  rules) precisely. The golden *expected values* are still a static,
  hand-reviewable file (`tests/golden/significance-scoring.json`) per TDD
  §13, diffed against fresh output rather than regenerated inline.

- **WP-05 · `harvest/git.py::extract()` calls G1 before *any* git
  subprocess (including `git ls-files` inside the G2 secret scan), not
  only before `git log`.** TDD 10.3 lists G1 as step 1 and the secret scan
  as step 4, which already implies this ordering, but it's called out here
  because the mandatory allowlist test (TDD 13 #1) asserts zero
  `subprocess.run` calls of any kind, not just zero `git log` calls.

- **WP-04 · `ffmpeg`/OpenAI transcription reached through injectable
  `Preprocessor`/`Splitter`/`TranscriptionClient` Protocols, tested via
  fakes, real implementations exercised only manually.** Unlike WP-02's
  equivalent choice for `AnthropicClient` (mostly a style preference),
  this one isn't optional: this dev/build environment has no `ffmpeg`
  binary at all (confirmed via `shutil.which`), so the automated suite
  cannot invoke real ffmpeg regardless of preference. `ce doctor` now
  requires `ffmpeg` + `OPENAI_API_KEY`; a machine that actually has ffmpeg
  installed exercises `FfmpegPreprocessor`/`FfmpegSilenceSplitter`/
  `OpenAITranscriptionClient` for real, but no CI/automated run does.

- **WP-04 · the "90-second fixture m4a" is a synthesized WAV tone
  (`tests/fixtures/audio/self-correction-90s.wav`), not a real m4a
  recording.** Producing real M4A/AAC content needs either `ffmpeg` (not
  available here) or an actual hand-recorded file (not obtainable
  programmatically). The fixture is genuinely 90 seconds and a valid,
  playable audio file (built with stdlib `wave`), so `ingest()`'s file
  handling is exercised for real; the pipeline is format-agnostic (ffmpeg
  accepts any container) so `.wav` vs `.m4a` doesn't affect correctness.
  The "self-correction" itself is injected via a fake transcription
  client's canned text, not extracted from real speech — see the next
  entry for why that's still a meaningful test.

- **WP-04 · the golden "clean.md retains a self-correction" test verifies
  plumbing, not real ASR/LLM judgment.** No automated test can make a real
  model produce or preserve a self-correction without a network call.
  What's verified: the raw self-correction text a fake transcription
  client returns (a) is written verbatim to `raw.txt`, (b) is passed
  unmodified into the `transcript_clean` prompt as `raw_text`, and (c)
  whatever the (fake) LLM returns lands verbatim in `clean.md`. Whether a
  *real* transcription + a *real* model call actually preserves a
  self-correction is a property of `prompts/transcript_clean.md` and the
  real model, validated by using the real system, not by a unit test.

- **WP-04 · `transcribe()` idempotency is a direct existing-output check,
  not `store.py`'s `hash_inputs`/`_manifest.json` primitives.** Those are
  one manifest per *directory*, but `captures/audio/transcript/` holds
  outputs for every capture in a project — a shared manifest there would
  collide across captures. Checking `capture.derived.transcript_raw` /
  `transcript_clean` plus file existence is simpler and sufficient, since
  a given capture's source audio never changes after ingest.

- **WP-04 · `ce capture screen` classifies screenshot vs. screencast by
  file extension.** TDD 5.2/§9 both name a single `capture screen <file>`
  command covering both `screenshot` and `screencast` capture types but
  never say how to tell them apart. Images (`.png/.jpg/.jpeg/.gif/.webp/
  .bmp`) → screenshot, video (`.mp4/.mov/.webm/.mkv`) → screencast;
  anything else is a readable `CaptureError`, not a silent misclassification.

- **WP-04 · `ce capture friction` both appends to `friction.md` *and*
  records a `Capture` (type=friction).** The CLI contract's own help text
  only mentions the file append, but TDD 5.2's `capture.yml` schema lists
  `friction` as one of the four capture types, and WP-04's Done-when line
  requires `ce capture list` to show "all types" — which needs a `Capture`
  record to list. `source_path` points at the shared `friction.md` file
  (all friction notes for a project point at the same file); `context`
  holds the note text.

- **WP-04 · `--project` is a required option on `capture audio|screen|
  friction`, not `Optional[str]` as WP-00 stubbed it.** There's no
  "current project" concept anywhere in the TDD or this codebase to fall
  back to, so an omitted `--project` had no sensible default behavior to
  implement — required-with-a-clear-error beats a silent no-op or a guess.

- **WP-04 · capture ids gained collision-safety
  (`store.generate_capture_id`), not part of WP-01's original `Capture`
  work.** The obvious `cap-YYYYMMDD-HHMMSS` scheme (matching the TDD 5.2
  example) collides when two captures happen within the same second —
  genuinely possible for rapid manual captures, and something WP-04's own
  test suite hit immediately. Appends `-2`, `-3`, ... only when needed, so
  the common case stays exactly the TDD's example format.

- **WP-04 · only the OpenAI transcription provider is implemented;
  `config.transcription.provider` is accepted but not dispatched on.**
  Same shape as WP-02's Gateway never branching on `config.llm.provider` —
  TDD 10.2 only ever describes one provider ("Transcribe: provider from
  config" — but no second provider is specified anywhere), so there's
  nothing to dispatch to yet.

- **WP-03 · `ce project new --repo` validates against `config.repos.allowed`
  at creation time, ahead of G1.** TDD 6.1 scopes G1 (the repo allowlist
  gate) as running "before any git access" — i.e. at harvest time, and it's
  implemented in WP-05's `gates/allowlist.py`, not this WP. WP-03's Build
  line only says "Slug validation. Directory scaffolding." Added an early,
  fail-fast check in `project._resolve_repo()` anyway: creating a project
  that references a repo not in the allowlist is a config typo that should
  surface immediately, not weeks later at `ce harvest`. This is *not* G1 —
  no gate module, no bypass semantics, just a plain `CEError` — and doesn't
  replace the real G1 check WP-05 still needs to build.

- **WP-03 · media backup location wasn't decided as part of the code
  changes.** Environment notes below had carried "decide in WP-03" since
  WP-00, but WP-03's actual TDD Build/Done-when lines never mention it —
  only `captures/audio/{raw,transcript}/` directories need to exist, which
  `store.scaffold_project_tree` now does; there is no `engine.yml` field or
  CLI command for a backup path, so this was always a documentation
  decision, not a build one. Resolved conversationally later in the same
  session: Google Drive, `My Drive/makingCodeIO/content` — see Environment
  notes.

- **WP-02 · `gateway.complete()` is a method on a `Gateway` class, not the bare
  function TDD 10.1 pseudocode shows.** Every other module (`store.py`,
  `config.py`) is explicit-args with no hidden globals; a bare
  `complete(prompt_id, vars, ...)` would need config/paths and the per-run
  spend accumulator (TDD 6.5 "per-run cap likewise") to live somewhere, and
  a module-level global was the only alternative. `Gateway(config,
  data_root=..., client=...)` carries all three explicitly instead.

- **WP-02 · provider calls go through a hand-rolled `httpx` POST
  (`llm/gateway.AnthropicClient`), not the `anthropic` SDK.** `httpx` is
  already a dependency for everything else in this repo; the Messages API
  is one POST + one retry loop, not enough surface to justify adding the
  SDK as a dependency. `Gateway` takes any object satisfying the
  `LLMClient` protocol via dependency injection.

- **WP-02 · test determinism via a fake `LLMClient`, not a pre-primed
  `tests/fixtures/llm-cache/` + `pytest --refresh-llm-cache` flag (TDD
  §13).** The DI seam that already exists for the httpx-vs-SDK deviation
  above makes a fake client injectable at zero extra cost — tests build a
  `Gateway` with a canned-response fake and assert call counts directly,
  with zero network calls and zero cache-fixture maintenance. The real
  `AnthropicClient` is exercised only by manual/integration use, not by the
  test suite. Revisit if a later WP needs to exercise real committed
  cache-file fixtures (e.g. golden-file testing on actual model output).

- **WP-02 · cache check runs before the budget check, not after (TDD 10.1
  lists budget as step 4, cache as step 3, which already matches — but the
  budget check can degrade the tier/model, and the cache key must reflect
  whichever model actually gets billed).** `Gateway.complete()` checks the
  cache using the *nominal* (pre-degrade) model first — a cache hit is free
  and must not be blockable by a budget that only a real call would trip.
  On a miss, the budget check runs and may degrade the tier; if that
  changes the model, the cache key is recomputed before the provider call
  and again before the write. A cache entry written under a prior
  *degraded* run is not re-checked at that point — an accepted gap, since
  `on_exceed: degrade` is not the default and revisiting it costs a second
  cache read on every miss for no benefit in the common (`halt`) case.

- **WP-02 · fixed `ruff check` lint debt in `cli.py` (17 pre-existing
  `Optional[X]`/`List[X]` → `X | None`/`list[X]` findings from WP-00), not
  introduced by this WP but blocking a clean `ruff check` on the repo.**
  Mechanical, `ruff check --fix`-only change, verified against the full
  test suite (all CLI command `--help` invocations still resolve — Typer
  handles `X | None` fine at runtime; the module's existing note against
  `from __future__ import annotations` is about postponed evaluation, not
  this syntax).

- **WP-01 · `ce project show` built as read/format logic in `store.py`, not
  wired into the CLI.** TDD 12's WP-01 Done-when line names `ce project show`
  printing correctly, but the actual Typer command is WP-03's declared Build
  scope (`ce project new|list|show|close`). Implemented
  `store.format_project_summary()` / `store.read_project_summary()` and
  proved them with a direct test against a hand-built fixture instead of
  wiring the CLI stub — keeps the one-WP-per-session boundary intact. WP-03
  should call these directly rather than reimplementing the read/format path.

- **WP-01 · `Brief.evidence[].kind` is a plain `str`, not an enum.** TDD 5.3
  marks the archetype enum as fixed; evidence `kind` isn't marked fixed
  anywhere, and its real producers (WP-05 git harvest, WP-07 research) aren't
  built yet. Left open rather than guessing a closed set that might not match
  what those WPs actually emit.

- **WP-00 · doctor required-flags are WP-aware.** TDD §12 says doctor "exits 1
  if any required one is missing". Implemented so a dependency is only
  *required* once the WP that needs it is built; earlier ones report as pending
  (△) without failing. Rationale: nagging about `mermaid-cli` for eleven
  sessions trains you to ignore doctor output. **Consequence: when you complete
  a WP, flip its dependencies to `required=True` in `src/ce/doctor.py`.** The
  table at the top of that file lists which. `ce doctor --strict` treats
  everything as required.

- **WP-00 · source is 3.10-compatible syntax** even though `requires-python`
  is `>=3.11` as designed. Costs nothing and allows smoke-testing on older
  interpreters. The 3.11 floor is still enforced at runtime by `check_python`.

---

## Environment notes

- **Host:** Windows. `.gitattributes` normalises line endings to LF in the repo.
- **Media backup target:** Google Drive, `My Drive/makingCodeIO/content`
  (decided 2026-07-27) — off-machine redundancy for audio/video that would
  otherwise live only on this machine. `ce capture` writes to local disk as
  normal (`data/projects/<slug>/captures/...`, gitignored); this Drive
  folder is where those files get copied/synced afterward, not a live
  capture target. `data/` itself is committed to git except `.llm-cache/`,
  `index.db`, `runs/`, and media (see `.gitignore`).
- **API keys:** environment variables only, never `engine.yml` (TDD §14).

---

## Open questions

None currently open.
