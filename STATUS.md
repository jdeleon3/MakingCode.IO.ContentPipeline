# Implementation Status

**Project:** Content Engine (`ce`)
**Spec:** `docs/TDD-content-engine.md`
**Last session:** 2026-07-28 — completed WP-19 (Pipeline run/log console):
`gui/routes/runs.py` (`/runs` picker + recent-runs list, `/runs/<run-id>`
console, `/runs/stream/<run-id>` SSE), `runs.html`, `run_detail.html`. Same
day as WP-17/WP-18.

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
| WP-09 | Writer & grader | ✅ done | 323 tests passing (44 new) |
| WP-10 | Claim verification | ✅ done | 337 tests passing (14 new) |
| WP-11 | Asset pipeline | ✅ done | 355 tests passing (18 new); `mermaid-cli`/`playwright` now required in `doctor.py` — `ce doctor` will fail on a machine without both installed |
| WP-12 | Renditions | ✅ done | 379 tests passing (26 new) |
| WP-13 | Packager & REVIEW.html | ✅ done | 394 tests passing (15 new); real Playwright/chromium acceptance test (browsers now installed on this machine) |
| WP-14 | Site publish | ✅ done | 421 tests passing (27 new) |
| WP-15 | Post-back & metrics | ✅ done | 449 tests passing (28 new); `UMAMI_API_KEY`/`YOUTUBE_API_KEY` now required in `doctor.py` |
| WP-16 | Trend sweep | ✅ done | 460 tests passing (12 new), 1 skipped (`EXPECTED_WP` in `test_cli.py` is now empty -- every stub is built); no new doctor entry, neither source needs auth |
| WP-17 | GUI scaffold, process runner, doctor screen | ✅ done | 473 tests passing (13 new), 1 skipped (pre-existing); new `gui` optional-dependency group (`fastapi`, `uvicorn`); no new `doctor.py` entry |
| WP-18 | Project dashboard | ✅ done | 477 tests passing (4 new), 1 skipped (pre-existing); no new `doctor.py` entry (read-only screen, no new dependency) |
| WP-19 | Pipeline run/log console | ✅ done | 487 tests passing (9 new), 1 skipped (pre-existing); no new `doctor.py` entry (subprocess console, no new dependency) |
| WP-20 | Brief review & selection | 🔵 next | |
| WP-21 | Article & grade review | ⬜ | |
| WP-22 | Rendition editing & package preview | ⬜ | |

**Critical path:** 00 → 01 → 02 → 05 → 08 → 09 → 12 → 13
**GUI critical path:** 17 → 19 → 21 → 22 (18, 20 can slip)

---

## Deviations from the TDD

- **WP-19 · `/runs` is a fixed picker over a hardcoded `_COMMANDS` list
  (`gui/routes/runs.py`), not a fully dynamic reflection of every §9
  command's real Typer signature.** The Build line says "pick any §9 stage
  command for a project/piece id" — every stage command from `doctor`
  through `cost` is represented, but each entry is (command key, argv
  prefix, one free-text "argument" slot, confirm flag); optional flags
  (`--force`, `--dry-run`, `--platform`, ...) go through a single free-text
  "extra flags" field parsed with `shlex.split` rather than per-flag form
  controls. `ce project new`/`ce capture *` are deliberately left off the
  list — they're one-time authoring actions with their own future screens
  (WP-20+), not pipeline stages you'd re-run from a log console. Consistent
  with the "the GUI never reimplements CLI logic" rule (§10.10): argument
  validation is left entirely to the real CLI subprocess, surfaced through
  its own streamed output, not re-validated here.
- **WP-19 · the confirm gate (`_Command.confirm`) is scoped to exactly one
  command, `publish-site`.** TDD's Build line says "`ce publish site`,
  anything that ends in `git push`" — grepped the whole `src/ce` tree for
  `git push`/`"push"` this session and the only hit is
  `publish/site.py`'s own call; no other §9 command reaches outside this
  machine, so there was nothing else to gate.
- **WP-19 · `/runs/<run-id>` falls back to reading the log file statically
  (no live exit code) when `runner._runs` no longer has the run's handle in
  memory** (e.g. the GUI process was restarted since that run finished).
  ADR-009 says `ce gui` is deliberately not a daemon, so there is no
  `Popen` left anywhere to poll an exit code from once the process that
  launched it is gone — this reads the same log file every other run's
  live view tails, just without a stream to reconnect to. Not itself named
  in the Done-when line (which is about a closed *browser tab*, not a
  restarted *GUI process*), but the natural edge case once `/runs/<run-id>`
  is a bookmarkable/reloadable URL rather than only a live SSE view.
- **WP-19 · `/runs/start` accepts a JSON body (`_RunRequest` Pydantic
  model), not `multipart/form-data`.** FastAPI's `Form(...)` parameter
  style needs `python-multipart` installed, which isn't currently a
  dependency of the `gui` extra (`pyproject.toml`) or anywhere else in this
  repo; a JSON body needs no new package. `runs.html`'s form submit handler
  posts `JSON.stringify(...)` with an explicit `Content-Type` header
  instead of handing the browser's native form-encoded body straight to
  `fetch`.
- **WP-18 · "not harvested" is `git.json` absent AND `research.json` absent AND
  `inventory.md` absent, not a single canonical flag.** TDD 10.10's Screens
  table just says `/projects/<slug>` reads "project + capture/harvest/piece
  counts" without defining what "harvested" means precisely. Cross-checked
  against the actual write paths (`harvest/git.py`'s `git.json`,
  `harvest/research.py`'s `research.json`, `harvest/inventory.py`'s
  `inventory.md`, all under `store.harvest_dir`) rather than inventing a
  fourth marker file — a project with *any* one of the three counts as
  "harvested" (possibly mid-harvest), all three absent is the explicit
  "not harvested yet" empty state the Done-when line calls out.
- **WP-18 · brief/piece counts are broken down by status (`Counter` over
  `BriefStatus`/`PieceStatus`), not shown as a single number.** Not required
  by the literal Done-when wording ("rolls up ... counts"), but a bare total
  hides exactly the distinction the dashboard exists to surface (e.g. how
  many briefs are `dropped` vs `candidate`) — same "build what the spirit of
  the Build line asks for" precedent as WP-11's hero-image handling and
  WP-15's `performance.md`.
- **WP-17 · TDD §14's "every run writes `data/runs/<ts>-<command>.log`" had
  never actually been built by any prior WP, despite being described as an
  existing, system-wide behavior** — no logging module, no `data/runs/`
  writer anywhere in the codebase before this session (confirmed by
  grepping the whole `src/` tree). WP-17 is the first WP whose own
  Done-when line genuinely depends on that log existing (`gui/runner.py`
  tails it), so it's built now: a new `ce/run_log.py` teeing `sys.stdout`/
  `sys.stderr` to `data/runs/<run-id>-<command>.log` for the duration of
  `cli.main()`'s call into the Typer app — wired in for **every**
  invocation, not just GUI-triggered ones, matching §14's literal
  "every run" wording rather than scoping it to the GUI alone. ANSI colour
  codes (`console.py`'s `paint()` output) are stripped from the log copy
  but left intact on the real terminal stream, since the log is meant to be
  plain text a browser can render directly, not a terminal transcript.
  `CE_RUN_ID` is an environment variable `gui/runner.py` sets before
  launching a subprocess so the parent can predict the exact log path the
  child will write to without racing it or duplicating `run_log.py`'s own
  filename logic; a bare terminal invocation has no such variable set and
  `run_log.tee` generates a fresh id itself, so direct CLI use gets a log
  with zero GUI involvement. Confirmed working end-to-end by running
  `ce doctor` directly in a scratch directory this session and inspecting
  the resulting log file, not just via the automated test suite.

- **WP-17 · `gui/runner.py::run_command` launches
  `[sys.executable, "-m", "ce.cli", *args]`, not the literal `["ce", *args]`
  shown in TDD 10.10's pseudocode.** A bare `"ce"` depends on the installed
  console-script's directory being on PATH inside whatever process
  environment `ce gui` itself happens to be running in, which isn't
  guaranteed (e.g. a venv invoked via its full interpreter path without
  ever being "activated"). `sys.executable -m ce.cli` resolves
  deterministically regardless of PATH state while still being a genuine
  subprocess invocation of the same unmodified `cli.main()` — not an
  in-process import, so §10.10's hard rule ("the GUI never imports pipeline
  modules... only ever a subprocess invocation of the real `ce` entry
  point") still holds.

- **WP-17 · the `/doctor` screen's live log tailing uses the browser's
  native `EventSource` API, not htmx.** htmx has no built-in SSE support
  without vendoring a second file (the `htmx-ext-sse` extension), and one
  screen's "tail a log live" behavior is exactly what `EventSource` is for
  natively — `static/htmx.min.js` is still vendored per the Build line (for
  the base layout's future page/partial navigation across WP-18–22), just
  not used for this specific screen's streaming.

- **WP-17 · `run_log.command_name()` derives a run's log filename with a
  two-token, non-flag-prefix heuristic, not a real argv/Typer parser.** It
  takes the leading run of tokens that don't start with `-`, capped at two
  (`["doctor"]` → `doctor`, `["brief","select","br-01"]` → `brief-select`,
  `["gui","--port","8420"]` → `gui`). Good enough for a readable, bounded
  filename without needing this module to track every command's actual
  positional/option schema — a filename is cosmetic, not something any
  Done-when line depends on being parsed back out.

- **WP-17 · `gui` is an optional dependency group (`fastapi`, `uvicorn`) in
  `pyproject.toml`, not a hard dependency, and no new `doctor.py` entry was
  added.** Same shape as WP-11's `playwright` extra: `pip install -e .`
  alone doesn't need to pull in a web server just to run the pipeline CLI;
  `ce gui` raises a readable `CEError` (`cli.py`'s `gui_cmd`) naming the
  install command if the extra isn't present, rather than a bare
  `ModuleNotFoundError` traceback. Neither WP-17's Build nor Done-when line
  mentions `doctor.py`, unlike every dependency-adding WP before it that
  did (WP-02/04/05/07/11/15) — confirmed by this session's
  `wp-spec-conformance` review, which independently checked the TDD text
  for any such requirement.

- **GUI (pre-WP-17) · §15's "Web UI" out-of-scope trigger ("after 10
  published pieces") was overridden before it fired.** `data/posted.yml`
  doesn't exist and no project has any `pieces/` yet — checked directly
  this session, not assumed. Raised explicitly to the operator before any
  design work started; the operator chose to proceed anyway (full
  operator dashboard, not just a REVIEW.html replacement) and asked for it
  recorded as a deviation rather than silently building around the
  original trigger. New ADR-009 (`docs/TDD-content-engine.md`) documents
  the resulting architecture decision (on-demand local FastAPI/HTMX
  server, `127.0.0.1`-only, no daemon, shells out to the real `ce` CLI for
  every action) and its own rationale; §10.10 is the full component spec;
  WP-17–WP-22 (table above) are the new work packages, same one-WP-per-
  session discipline as WP-00–16. This session did design only — no code
  written yet, WP-17 is next.
- **GUI scope, chosen via interview this session** (recorded here since
  none of it is derivable from code that doesn't exist yet): full operator
  dashboard covering the whole pipeline, not just a review/approval layer;
  local web app (`ce gui`) over a desktop app or TUI; drives the pipeline
  by shelling out to the existing tested CLI, never by importing pipeline
  modules in-process; live log streaming for long-running stages, tailing
  the run log every command already writes per §14 rather than piping
  subprocess stdout directly (survives a closed browser tab); article text
  and per-platform rendition copy are editable in-GUI with save-back to
  the same files the CLI reads/writes (ADR-008's mtime-based edit check
  keeps working unmodified, no special-casing); localhost-only, no
  authentication; explicit confirm dialogs on any action that reaches
  outside this machine (`ce publish site`'s git push). Metrics/trend-sweep
  dashboards and a project-creation/capture wizard were considered and
  deliberately left out of this v1 scope — revisit after WP-22 if the CLI
  for those still feels like the more natural surface.

- **WP-16 · no component-spec section exists anywhere in the TDD for this
  WP at all** — not just a missing §10.10 (WP-15's gap): §10 stops at 10.9
  `publish/site.py`, and there is no `10.10`/`10.11` for sweep either. The
  *entire* module design below (data shapes, config, recurrence math,
  bucket thresholds) is this session's invention, working only from the
  one-line Build/Done-when pair in TDD 12. Confirmed by this session's
  `wp-spec-conformance` review, which independently searched the TDD for
  any WP-16-specific spec text rather than trusting this note.

- **WP-16 · no LLM call anywhere in this module.** Unlike every other
  harvest-side WP, the Build line names no new prompt — topic matching is
  a plain case-insensitive substring match against a fixed,
  operator-edited watch-list (`config.sweep.topics`), not an LLM
  classification call. Consequence: there's nothing here to discover a
  topic the operator didn't already think to list; a real "AI agents"
  boom the operator never added to `config.sweep.topics` would sweep
  right past unnoticed.

- **WP-16 · a new `config.sweep` section (`topics`, `rss_feeds`) was added
  to `engine.yml`/`config.py`** — TDD §8 has no `sweep` key at all, same
  gap WP-15 hit for `analytics`. `topics` is the operator's own
  demand-signal watch-list (matched case-insensitively as a substring
  against HN/RSS titles); neither field is a secret, so both stay in
  `engine.yml` rather than the environment.

- **WP-16 · recurrence is computed purely from *prior* sweeps, never
  blended with today's own occurrence.** `TopicRank.recurrence` counts how
  many of the last `HISTORY_WINDOW=4` prior `sweeps/<date>.json` snapshots
  already on disk contained the topic; today's occurrence lives on a
  separate axis (`today_count`/`today_strength`). This is the literal
  reading of the Done-when line's own wording ("3 of 4 **prior** sweeps")
  and matches `BriefDemand.recurrence`'s existing TDD 5.2 comment ("sweeps
  out of the last 4") without divergence. Ranking sorts by the tuple
  `(recurrence, today_strength)` — Python's tuple comparison means
  recurrence always dominates regardless of how large a same-day spike's
  strength is, which is what actually satisfies the Done-when line, not a
  hand-tuned weighting formula.

- **WP-16 · `sweeps/<date>.json` (one per day, alongside `sweeps/<date>.md`)
  is invented — TDD 5.4/§7's directory tree names only the `.md` file.**
  Same "structured data lives in git, the .md is what you read" split as
  `harvest/inventory.md` (WP-08) and `performance.md` (WP-15): recurrence
  scoring on a later run needs to compare against the last few days'
  *signals*, not re-parse its own rendered markdown.

- **WP-16 · HN hits are re-filtered by a plain title-substring match
  against the query topic, not trusted as already-precise from Algolia's
  own relevance ranking.** Discovered by running a real sweep against this
  session's own `config/engine.yml` topics: a live Algolia search for
  "Astro" surfaced a story titled "Astronauts describe..." (Algolia does
  stemmed/fuzzy relevance search, not literal substring matching) —
  `collect_signals()` drops any HN hit whose title doesn't literally
  contain the topic string, same filter RSS entries already needed.

- **WP-16 · `sweep/rss.py` parses by local element name (`item` or
  `entry`), not by RSS-vs-Atom dialect detection.** TDD names no format at
  all for this file. Needed for real, not just in theory: this session's
  default `config.sweep.rss_feeds` (Reddit subreddit feeds) are actually
  Atom under a `.rss` URL path, not RSS 2.0 — verified against the real
  feeds, not assumed.

- **WP-16 · `_HN_LOOKBACK_DAYS = 2` (how far back an HN/RSS hit still
  counts as "today's" signal) is a hardcoded constant, not a config
  field.** TDD gives no number for this at all; a config knob for a single
  hardcoded input felt like more machinery than the actual need, same
  "revisit if per-project tuning turns out to matter" call WP-09 made for
  `writer._LENGTH_TARGET`.

- **WP-16 · no new `doctor.py` entry.** Every other harvest-adjacent WP
  added a required dependency (an API key or a binary); this one doesn't
  — the Algolia HN Search API needs no auth at all, and RSS is a plain
  GET. Confirmed by running a real sweep against live HN + Reddit feeds
  this session (one Reddit feed 429'd mid-run and was correctly recorded
  as a failed source without aborting the others, proving the Done-when
  line against real network conditions, not just a fake).

- **WP-15 · no `§10.10` component spec exists anywhere in the TDD for this
  WP** (§10 stops at 10.9 `publish/site.py`) — every design choice below is
  this session's invention, not derived from a TDD section the way most
  other WPs' Build lines could be. Confirmed by this session's
  `wp-spec-conformance` review, which independently checked the TDD for a
  missing §10.10 rather than trusting this note.

- **WP-15 · a new `config.analytics.umami` section (`api_url`,
  `website_id`) was added to `engine.yml`/`config.py`** — TDD §8's
  reference config has no `analytics` key at all. `UMAMI_API_KEY` (the
  actual secret) stays environment-only per TDD §14/ADR pattern; these two
  fields are non-secret operational config, same split every other
  provider section in `config.py` already makes.

- **WP-15 · `metrics/umami.py` and `metrics/youtube.py` both use a plain
  `httpx.get`, not an official SDK** — reversing the general "prefer the
  official SDK" direction the 2026-07-28 cross-cutting deviation set for
  Anthropic/OpenAI/Gemini/Perplexity. Umami has no official Python SDK at
  all (self-hosted, single REST endpoint) — same shape as
  `harvest/research.py`'s `DuckDuckGoSearchClient`, which scrapes a page
  for the same reason. YouTube's Data API v3 does have an official SDK
  (`google-api-python-client`), deliberately not added: it's a heavyweight,
  discovery-document-based client meant for multi-endpoint/write use, and
  this WP only ever makes one read-only `videos.list?part=statistics` call
  — no retry/streaming/multi-endpoint surface for an SDK to actually earn
  its keep on, the same "one GET doesn't need an SDK" reasoning WP-02
  originally used for Anthropic before that call was reversed for a
  different reason (a real retry bug an SDK's streaming call fixed
  structurally — no equivalent bug exists here).

- **WP-15 · Umami click attribution matches on path+query against the
  piece's UTM'd URL, reusing `produce/renditions.py`'s existing
  `canonical_url`/`utm_url` helpers rather than re-deriving the query
  string a third time.** Assumes Umami's tracking script records the full
  path+query (including `utm_*` params) as its per-URL `x` value, which is
  its default behavior; not verified against a real Umami instance (this
  dev environment has none) — see the next entry.

- **WP-15 · `HttpxUmamiClient`/`YouTubeDataApiClient`'s real transport is
  exercised only by monkeypatching `httpx.get` in tests, never a live
  network call** — same shape as WP-04's ffmpeg/WP-05's gitleaks/WP-07's
  original httpx-based research clients: this dev environment has neither
  a live Umami instance nor a populated `YOUTUBE_API_KEY` to test against
  for real. `ce doctor` reports both as pending until installed/set.

- **WP-15 · LinkedIn *and* Facebook engagement metrics (`impressions`,
  `reactions`, `comments`) are manual-entry-only — `metrics/pull.py` never
  fetches or zeroes them for either platform, only ever refreshing
  `site_clicks`.** TDD's Done-when line only names LinkedIn explicitly,
  but the Build line lists no `metrics/facebook.py` module either, and
  neither platform has a public API for a personal/page post's engagement
  numbers without a partnered app review — out of reach per TDD §15's "API
  publishing to social platforms: never" stance, which this session reads
  as covering reads of that kind of data the same way it covers writes.
  TDD 5.2's own `posted.yml` example (real LinkedIn impressions/reactions/
  comments) is only explainable as a hand-edit, since no CLI command
  anywhere accepts those numbers — `data/posted.yml` is committed to git
  like everything else in `data/`, so hand-editing it is consistent with
  how the rest of this system already treats its own data files.

- **WP-15 · idempotent-per-snapshot-date is implemented as "drop any
  existing `MetricSnapshot` with today's calendar date (UTC), then append
  a fresh one"** rather than merging fields into the existing snapshot in
  place. Simpler, and behaviorally identical for every field `pull` itself
  computes (site_clicks always recomputed; YouTube's three fields always
  recomputed from the live API; LinkedIn/Facebook's three fields always
  carried forward from the prior snapshot) — there's no field a same-day
  rerun would need to preserve that isn't already being explicitly
  recomputed or carried forward by that same call.

- **WP-15 · `performance.md` (`data/performance.md`, global, next to
  `posted.yml`) is regenerated in full on every `ce metrics pull` run**,
  same "content lives in git, the `.md` is what you actually read" split
  as `harvest/inventory.md` (WP-08). Not itself named in the Done-when
  line, only the Build line — same "build what the Build line asks for
  even when Done-when doesn't re-test it" precedent as WP-11's hero-image
  handling.

- **WP-14 · `publish/site.py`'s frontmatter omits TDD 10.9's literal
  `canonical` key.** Inspected the real site repo this session
  (`identity.site_repo`, an Astro project) rather than guessing:
  `src/content.config.ts`'s blog collection schema has no `canonical` field
  (Zod's default `z.object()` behavior silently strips unknown keys, so
  writing one would be inert at best), and `src/components/BaseHead.astro`
  already computes `<link rel="canonical">` and every `og:*`/`twitter:*` tag
  from `Astro.url`/`Astro.site` automatically. The canonical URL this WP
  actually needs (to poll, and to write `piece.published.url`) reuses
  WP-12's `produce/renditions.py::canonical_url`
  (`site_url + "/blog/" + slug`) rather than a second copy. Confirmed
  independently by this session's `wp-spec-conformance` review, which read
  the site repo's schema/layout itself rather than trusting this note.

- **WP-14 · `--no-edit-check` (ADR-008's own language) is a keyword
  parameter on `publish/site.py::publish()`, not a CLI flag.** TDD 9's
  literal CLI contract line for this exact command --
  `ce publish site <piece-id> [--dry-run]` -- lists no such flag, and
  ADR-008 never says which command should surface it. Read literally: the
  bypass exists for this module's own test suite to call directly ("for
  testing only"), not as an operator-facing escape hatch on
  `ce publish site`.

- **WP-14 · no `description` field exists anywhere in the data model**
  (`Piece`, `Brief`, `Project`) to carry an OG description. Same gap WP-08
  hit for its dedupe "one-line summary":
  `publish/site.py::_description_from_body` uses the article body's first
  non-blank, non-heading line, truncated to 155 chars (a common OG/meta-
  description soft limit, not a TDD number).

- **WP-14 · the hero image copied into the site repo is namespaced by the
  piece's slug** (`src/assets/blog/<slug>.<ext>`), not a fixed `hero.<ext>`
  name. Unlike a piece's own `assets/` directory (one piece per folder),
  the site repo's asset directory is shared across every published piece --
  a fixed name would collide on the second post.

- **WP-14 · git commit/push uses direct `subprocess` calls
  (`publish/site.py::commit_and_push`), not an injectable Protocol**,
  matching `harvest/git.py`'s existing precedent (git itself is a required
  system dependency since WP-00, not a swappable provider). The HTTP
  polling/OG-tag-fetch client (`HttpClient` Protocol, `HttpxClient` the real
  implementation) *is* injectable, same DI shape as `harvest/research.py`'s
  `SearchClient`/`FetchClient` -- tests fake it rather than hitting the
  network or sleeping the real 120s default.

- **WP-13 · the Done-when line's "matches the v3 §4 layout" points at a
  section that doesn't exist.** `docs/DIY-Content-Engine-v3-Spec.md`'s
  actual §4 is "Reversal #1 — build YouTube now, not later" (narrative
  prose about screen-recording vs. AI avatars, not a directory tree) — the
  only outbox-shaped thing anywhere in that document is one line in its
  pipeline diagram, `OUTPUT: outbox/<slug>/REVIEW.html`. Resolved using TDD
  §9's own CLI contract line instead (`ce package <piece-id> ->
  outbox/<piece-id>/ + REVIEW.html` — keyed by piece-id, not slug) and §7's
  directory layout. Built the smallest thing that satisfies both that and
  ADR-006 (`REVIEW.html` + relatively-pathed images): `outbox/<piece-id>/`
  holds `REVIEW.html` plus a flat `assets/` of every staged *output* image
  copied as-is. Article text and rendition YAML are deliberately **not**
  copied into the outbox — ADR-006's point is that `REVIEW.html` is the
  single self-contained deliverable, and the site article isn't posted from
  here at all (`ce publish site`, WP-14, ships it separately). Confirmed by
  this session's `wp-spec-conformance` review: no better-matching "v3 §4"
  content exists elsewhere in that document.

- **WP-13 · which staged asset image a platform's REVIEW.html section shows
  is an invented heuristic (`package/builder.py::_PLATFORM_IMAGE_PRIORITY`),
  not a TDD rule.** No per-platform asset tagging exists anywhere in the
  data model (WP-11's own deviations log already flagged this gap).
  YouTube's section shows `thumbnail.png` (a literal 1280×720 dims match
  for `config/platforms/youtube.yml`); LinkedIn/Facebook prefer the hero
  image (the "real artifact" screenshot — the strongest asset per the v3
  spec's own §5 table) and fall back to the thumbnail only if no hero was
  staged, rather than showing nothing. Revisit if assets ever gain explicit
  per-platform tags.

- **WP-13 · `REVIEW.html`'s copy boxes are editable `<textarea>`s, not
  read-only.** TDD 10.8 doesn't say either way ("copy box" + "live
  character counter"), but a genuinely *live* counter implies the operator
  can tweak the generated copy in-browser before copying it — the same
  "you edit before it ships" spirit as ADR-008's `article.md` edit check,
  just informal here since REVIEW.html has no write-back path (ADR-006:
  no server, no localStorage). The counter recomputes on every `input`
  event, not just once at page load.

- **WP-13 · `ce package` requires at least one rendition file to already
  exist (`renditions/*.yml`), else it raises rather than producing an empty
  REVIEW.html.** Not a literal Done-when line, but a packaged piece with
  zero rendered platforms has nothing for the reviewer to act on, which
  defeats §10.8's entire purpose — same "refuse a precondition gap with a
  clear pointer to the missing prior step" shape as `ce verify`/`ce render`
  checking for `article.md`.

- **WP-13 · `produce/renditions.py`'s `_YOUTUBE_TITLE_MAX_CHARS` (WP-12)
  was renamed to the public `YOUTUBE_TITLE_MAX_CHARS`.** `package/builder.py`
  needs the same number to label the YouTube title copy box's character
  counter — one source of truth for the literal `60` (TDD §11) rather than
  a second hardcoded copy in a different module. No behavior change, purely
  a visibility rename; all three existing call sites in `renditions.py`
  updated along with it.

- **WP-13, cross-cutting · `playwright`/chromium got installed on this dev
  machine this session** (WP-13's own REVIEW.html acceptance test drives a
  real browser to prove "opens from `file://` with no network and no
  console errors" — no string-matching assertion against raw HTML can
  actually prove that). This flipped `ce doctor`'s playwright check from
  missing to present, which broke one *already-closed* WP-11 test
  (`test_assets.py::test_playwright_renderer_missing_package_is_a_clear_error`)
  whose premise was "this dev environment genuinely has no playwright
  installed" — no longer true. Fixed by monkeypatching
  `sys.modules['playwright.sync_api'] = None` to force Python's real
  `ImportError` path deterministically (the standard technique for this),
  rather than relying on environment absence. Same shape as WP-02's
  session-incidental ruff-lint-debt fix: a pre-existing test broken by
  something this session did on purpose, fixed and verified, not left
  behind.

- **WP-12 · no `Rendition` schema exists anywhere in TDD 5.2 — `piece.yml`'s
  own example has no `renditions` key, and TDD 5.4/§7 only names the file
  paths (`renditions/{linkedin,facebook,youtube}.yml`), not their shape.**
  Invented this session, same as WP-09's `grades.json`: `platform`, `body`,
  `first_comment` (LinkedIn only), `title`/`chapters` (YouTube only,
  structurally different from a single body), `prompt_version`,
  `generated_at`. One shared model rather than three per-platform ones, so
  `ce package` (WP-13) can iterate over a piece's renditions uniformly.

- **WP-12 · the canonical URL used in LinkedIn's first comment, Facebook's
  inline link, and YouTube's description is computed deterministically as
  `config.identity.site_url + "/blog/" + piece.slug`, never read from
  `piece.published.url`.** WP-12 runs *before* WP-13/WP-14 in the pipeline
  (TDD 12.1's dependency graph: WP-09 → WP-12 → WP-13, separately from
  WP-09 → WP-10 → WP-14), so nothing has published the piece yet at render
  time — `published.url` is unset. The computed shape matches TDD 5.2's own
  `piece.yml` example (`https://example.com/blog/duckdb-memory-limit-reality`
  is exactly `site_url + "/blog/" + slug`), i.e. the URL WP-14 will actually
  publish to, so the link is correct in advance rather than a placeholder.
  UTM parameters (`config.utm.template`) are appended per platform on top of
  this base URL, for every platform, including YouTube — TDD gives no
  per-platform opt-out for UTM tracking.

- **WP-12 · `config/platforms/facebook.yml` and `youtube.yml` have no TDD
  example to copy — only `linkedin.yml` is spelled out verbatim (TDD 8).**
  TDD §11's registry gives one-line notes only ("Facebook: links OK; native
  image", "YouTube: title ≤60, desc hook 150, chapters from 00:00"). Every
  numeric value in both files (max_chars, hook_chars, image dims,
  links_in_body, allow_unicode_styling, ...) is this session's own choice,
  not derived from the TDD. YouTube's `hook_chars: 150` is the one number
  that *is* TDD-literal ("desc hook 150").

- **WP-12 · YouTube's title (≤60 chars) and chapter (start at `00:00`,
  strictly ascending) rules are hardcoded in `produce/renditions.py`
  (`_YOUTUBE_TITLE_MAX_CHARS`, `_validate_chapters`), not driven by
  `PlatformConfig` fields.** TDD 10.6/11 state both as fixed numbers/rules,
  not per-platform config (unlike `max_chars`/`hook_chars`, which genuinely
  vary by platform). `youtube.yml`'s `hook_chars` field is reused for a
  different assertion than LinkedIn's: LinkedIn's hook must contain *no*
  URL, YouTube's description hook must *contain* the URL — same field,
  opposite check, because both are "does the visible-before-fold span
  satisfy platform-specific rule X" and TDD's own bullet list already
  branches validation logic per platform name, so reusing the field instead
  of adding a second one felt more honest than inventing an unused knob.
  `youtube.yml`'s `links_in_body: true` is schema-required
  (`PlatformConfig.links_in_body` has no default) but is not actually read
  by `_validate_youtube` — the description's URL-presence check is
  unconditional there, driven only by the hardcoded hook-chars logic. The
  field is set to a defensible value (`true`, since a link is required, not
  forbidden) but is decorative for YouTube rather than load-bearing;
  flagged by this session's `wp-spec-conformance` review, not a correctness
  bug (every Done-when criterion still passes) but worth knowing if
  `youtube.yml` is hand-edited later expecting that field to do something.

- **WP-12 · LinkedIn's "first `hook_chars` ... end at a sentence boundary"
  check (TDD 10.6) is implemented as "some sentence-ending punctuation
  (`.`/`!`/`?`) exists anywhere within the first `hook_chars` characters",
  not "the character at exactly `hook_chars` is itself a sentence
  boundary".** TDD's own wording is inherently fuzzy for a "mechanical"
  check — this is the looser of two reasonable readings, chosen because
  requiring an exact-position match would reject a hook that reads
  perfectly well but happens to end its sentence a few characters before or
  after the fold.

- **WP-11 · no `Asset` schema exists anywhere in TDD 5.2, and
  `pieces/<id>/assets/`'s *inputs* (as opposed to its rendered outputs)
  aren't named by TDD 5.4/§7's directory tree at all — every input
  location below is this session's invention, not a TDD-specified path.**
  Recorded here in full since none of it could be inferred from an
  existing convention the way, say, WP-09's `grades.json` shape could:
  - **Diagram source**: hand-authored Mermaid at
    `pieces/<id>/assets/diagrams/*.mmd`, one PNG per file. TDD 10.7 says
    diagram input is "Mermaid source (LLM-generated or hand)" but WP-11's
    Build line names no new prompt, so "or hand" is the only path this WP
    actually builds — nests inside the already-TDD-named `assets/` leaf.
  - **Code snippets**: `pieces/<id>/evidence/*`, one code card per file,
    language inferred from extension. Reuses TDD 6.2's exact words — "the
    operator hand-selects the snippet into `evidence/` explicitly" — for
    *where*, but that line never gives a path, and **`evidence/` does not
    appear in TDD 5.4/§7's own `pieces/<id>/` directory tree** (which lists
    only `piece.yml`, `article.md`, `grades.json`, `verification.json`,
    `renditions/`, `assets/`). This is the one invented convention that
    adds a wholly new top-level piece subdirectory rather than nesting
    inside one the TDD already named — flagged explicitly since it's a
    bigger liberty than the other three.
  - **Hero image**: `pieces/<id>/assets/hero-source.<ext>`, copied as-is to
    `assets/hero.<ext>` — TDD 10.7's unlabeled fourth table row
    ("screenshots: copy + manual review flag"), matched to the CLI stub's
    pre-existing `--only diagram|codecard|thumbnail|hero` help text and
    TDD 5.1's `Piece 1--* Asset (hero, diagram, code card, thumbnail,
    video)` line — `hero`/`video` are named asset *kinds* there with no
    corresponding §10.7 renderer; `video` stays out of scope entirely
    (§2.3: "Generate long-form video from text" is explicitly not done).
  - **Thumbnail background**: optional `pieces/<id>/assets/thumbnail-bg.<ext>`.
    TDD 10.7 lists thumbnail inputs as "title, screenshot, optional face" —
    "face" isn't built (no capture type for a face photo exists anywhere
    in this codebase, and it's not exercised by WP-11's Done-when line);
    "screenshot" is this hand-staged background file rather than an
    auto-picked `CaptureType.SCREENSHOT` capture, since nothing links a
    `Capture` to a `Piece` in the data model to pick one from correctly.
  - **Per-platform code-card dimensions**: hardcoded `_PLATFORM_DIMS` in
    `assets/codecard.py`, not read from `config/platforms/*.yml`. TDD 10.7
    asks for "per-platform dims" but those config files don't exist yet —
    WP-12's own Build line is "three platform configs"; WP-11 (`D: WP-09`
    only) has no dependency on WP-12 and genuinely cannot read a file that
    doesn't exist. Revisit once WP-12 builds real platform configs.

- **WP-11 · `playwright` is an optional extra
  (`pyproject.toml`'s `[project.optional-dependencies].assets`), not a hard
  dependency like every prior WP's new SDK (`numpy` WP-06, `google-genai`/
  `perplexityai` WP-07).** `pip install playwright` alone doesn't make it
  usable — `playwright install chromium` is a separate ~300MB download
  beyond what any other WP's dependency needed, and
  `PlaywrightScreenshotRenderer` already imports it lazily behind a
  `ScreenshotRenderer` Protocol (same DI shape as WP-04's `ffmpeg` seam),
  raising a readable `AssetError` if it's missing rather than crashing at
  import time. `mermaid-cli` has no `pyproject.toml` entry at all — it's a
  system/npm binary, never a Python package, same as `ffmpeg`/`gitleaks`.

- **WP-11 · `mermaid-cli`/`playwright + chromium` flipped to
  `required=True` in `doctor.py`, per this WP's own close-out convention
  (WP-04's `ffmpeg`, WP-05's `gitleaks`).** Neither is installed on this
  dev machine — `ce doctor` now exits 1 here until both are installed;
  confirmed this is the intended signal (the operator needs to know
  before trying to run `ce assets` for real), not a regression.

- **WP-10 · `external` claim verification reuses WP-07's `research_stance`
  prompt instead of a new one.** TDD 6.4 says `external` claims are
  "supported by a fetched source. Web search + fetch" but WP-10's Build
  line names only one new prompt (`claim_extract`) — no second prompt for
  "does this fetched source support this specific claim." Stance
  classification (`supports`/`contradicts`/`neutral` against a hypothesis)
  *is* that check: `gates/claims.py::_verify_external` searches for the
  claim text, fetches each hit in rank order via the existing
  `SearchClient`/`FetchClient` Protocols, and treats the first `supports`
  stance as verification. No new dependency, no new prompt.

- **WP-10 · promoted `produce/writer.py::_format_evidence_context` to
  public (`format_evidence_context`) and factored its capture/commit
  resolution out to a new `ce/evidence.py::resolve_capture_or_commit`.**
  `claim_extract` needs to see the *same* evidence material the article was
  drafted from, to correctly attribute a `grounded` claim's `ref` — without
  reuse this would've been ~70 lines duplicated between `produce/writer.py`
  and `gates/claims.py`. Deliberately **not** touched:
  `harvest/inventory.py`'s own (older, boolean-only, raw-JSON-shaped)
  citation-resolvability check — refactoring already-closed WP-08 code onto
  the new shared resolver was out of this WP's scope; three
  independent-but-related implementations of "does this ref resolve" now
  exist (`inventory.py`'s set-based check, and the shared resolver used by
  `writer.py`+`claims.py`) rather than one canonical version everywhere.

- **WP-10 · `config.gates.claims.block_on_unverifiable` (already defined in
  `config.py` since WP-01, unused until now) controls only whether an
  `unverifiable`-classified claim blocks `ce verify`.** TDD 6.4's table
  gives no toggle for this — `unverifiable` "blocks", full stop. A
  `grounded` claim that doesn't resolve, or an `external` claim no fetched
  source supports, still blocks unconditionally regardless of this flag;
  it only changes whether the softer, harder-to-mechanically-verify
  `unverifiable` class is treated as fatal. `--force` (TDD 9's CLI
  contract) is the separate, always-available bypass on top of that
  policy — `verification.json` and `piece.yml#verification` record every
  failure either way, `--force` only decides whether `ce verify` raises.

- **WP-10 · `opinion`-classified claims are never independently
  re-verified — trusted entirely to `claim_extract`'s own classification.**
  TDD 6.4 says opinion claims need "no verification" but must be
  "linguistically marked as opinion." There's no mechanical way to check
  "is this phrased as an opinion" without another LLM judgment call, which
  would just be re-classifying the same claim a second time; the
  `claim_extract` prompt is instructed to only use `opinion` when a claim
  is genuinely hedged/first-person-marked, and that instruction is the only
  enforcement.

- **WP-09 · `ce brief select <brief-id>` / `ce produce <piece-id>` take no
  `--project` (TDD 9's literal CLI contract), so both are found by scanning
  every project (`store.find_brief` / `store.find_piece`).** Brief and
  piece ids restart per project (`br-01`, `pc-0001`, ... — WP-08's
  `inventory.generate` / WP-09's `store.generate_piece_id`), so the same id
  existing in two projects is a real, unresolved ambiguity — both helpers
  raise `ConfigError` naming the colliding projects rather than silently
  picking one.

- **WP-09 · `article_draft`'s "cited evidence in full" (TDD 10.5) and
  "receives raw + clean transcripts" (TDD 11) resolve each
  `Brief.evidence[].ref` back to its real source** — a capture id to
  `Capture.derived`'s raw+clean transcript files, a commit SHA (full or
  7-char short, same match rule as WP-08's citation-resolvability check) to
  `git.json`'s already-condensed `summary` (never a raw diff), a research
  URL to `research.json`'s `summary`. Falls back to the brief's own
  MATCH-time `quote` only if the ref no longer resolves (harvest re-run,
  deleted capture) — never drops a citation outright. Required two new
  read helpers, `harvest.git.read_git_harvest` /
  `harvest.research.read_research_harvest`, since `ce produce` runs as a
  separate process invocation from `ce harvest` with no in-memory
  `GitHarvest`/`ResearchHarvest` left over to reuse (unlike WP-08's
  `inventory.generate`, called in the same `ce harvest` run that just
  produced them) — both default to an empty harvest if the file doesn't
  exist yet rather than raising, same "best-effort optional input" shape as
  WP-08's sweeps/inbound context. First pass at this WP resolved evidence
  only from the brief's own condensed `note`/`quote` fields; caught and
  fixed against the literal TDD language during this same session's
  `wp-spec-conformance` review before closing.

- **WP-09 · `grade.schema.json` has no `total` field — the model returns
  only per-dimension `scores` + `top_fixes`; `total` is computed in code
  from `config.produce.grade_weights` (`writer._weighted_total`).** Same
  "don't trust the model with deterministic bookkeeping" split WP-08 used
  for `Brief.id`/`dedupe_max_similarity`. The 9.5 ceiling ("a 10 isn't
  achievable by construction," TDD 10.5) is enforced at the schema level
  (`maximum: 9.5` per dimension, so a weighted sum of dimensions that each
  top out at 9.5 with weights summing to 1.0 can't exceed it either), not
  just stated in the prompt.

- **WP-09 · `grades.json`'s shape is invented — TDD names the file (§7's
  directory layout) and requires it to "record every attempt with prompt
  versions" (12's Done-when) but never specifies a schema.** Implemented as
  `{"attempts": [{attempt, total, scores, draft_prompt_version,
  grade_prompt_version, top_fixes}, ...]}` — `draft_prompt_version` is
  whichever prompt actually produced the draft being graded that attempt
  (`article_draft` for attempt 1, `article_revise` for later attempts,
  since revise — not draft — regenerates the article mid-loop).
  `piece.yml#grades` stays the terser TDD 5.2 example shape (attempt/total/
  scores only); `grades.json` is the richer sibling the Done-when line
  actually asks for.

- **WP-09 · a `top_fix`'s `impact` is a `high`/`medium`/`low` enum, not a
  number, and `writer._format_fixes` defensively re-sorts by it before the
  revise prompt sees them rather than trusting the model's array order.**
  TDD 10.5 says `top_fixes` are "ranked by impact" without specifying the
  field's type; an enum is simpler for the model to reason about and to
  sort deterministically than an unbounded numeric score.

- **WP-09 · `article_draft`'s "platform-agnostic length target" (TDD 10.5)
  is a hardcoded prompt constant (`writer._LENGTH_TARGET = "900-1500
  words"`), not a config field.** TDD gives no number and no config key for
  it; adding an `engine.yml` field for a single hardcoded prompt input felt
  like more machinery than the actual need — revisit if per-project tuning
  turns out to matter.

- **WP-09 · voice RAG (`voice/*.md` → top-5 chunks) is brute-force
  cosine similarity, re-embedding every paragraph chunk on every
  `produce()` call — no persistent index.** Same ADR-003 bet WP-06 made for
  piece dedupe (`gates/dedupe.py`), scaled down further: a single
  operator's own prior-writing corpus is smaller than the piece corpus
  ADR-003 already sized for.

- **WP-09 · `ce produce --force` is accepted (TDD 9) but not meaningfully
  enforced — `produce()` always redoes the full draft/grade/revise loop and
  overwrites `article.md`/`grades.json` on every call.** Same accepted gap
  as `ce harvest --force` (no stage-level resumability manifest built for
  either stage yet).

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
- **Playwright + chromium:** genuinely installed on this machine as of
  WP-13 (`ce doctor` now reports it present, not pending) — WP-13's
  REVIEW.html acceptance test drives a real browser. `assets/codecard.py`/
  `assets/thumbnail.py`'s `PlaywrightScreenshotRenderer` (WP-11) can now
  also be exercised for real here, not just via the fake in tests.
  `mermaid-cli` is still not invocable via `ce doctor` on this machine
  (`mmdc`/`mmdc.cmd` resolve on PATH but the subprocess call fails with
  `WinError 2`) — a pre-existing WP-11 gap, out of WP-13's scope, not
  touched this session.
- **`UMAMI_API_KEY`/`YOUTUBE_API_KEY` (WP-15):** neither is set on this
  machine, and there's no self-hosted Umami instance to point
  `config.analytics.umami.api_url` at yet — `ce doctor` now exits 1 here
  until both are set/deployed. `ce metrics pull` and `HttpxUmamiClient`/
  `YouTubeDataApiClient`'s real transport are untested against live
  services as a result (tests fake both clients — see STATUS.md
  deviations); functionally complete, just not yet exercised for real.
- **`config.sweep.topics`/`rss_feeds` (WP-16):** `config/engine.yml`'s
  defaults (DuckDB, AI agents, LLM evals, data engineering, Astro; two
  Reddit subreddit feeds) are this session's own illustrative starting
  point, marked `# EDIT THIS` same as `transcription.vocabulary` — replace
  with whatever this operator's actual beat is. `AlgoliaHNClient`/
  `HttpxRssClient`'s real transport *was* exercised live this session
  (unlike most other WPs' external clients) — a real sweep against these
  exact defaults surfaced two real findings folded into the implementation
  before close-out: Algolia's relevance search over-matches short topic
  strings (see the WP-16 deviation on HN title-filtering), and Reddit's
  `.rss` feeds are Atom, not RSS 2.0 (see the WP-16 deviation on
  `sweep/rss.py`'s parser). One Reddit feed also 429'd mid-smoke-test and
  was correctly isolated as a failed source rather than aborting the run.

---

## Open questions

None currently open.
