# Implementation Status

**Project:** Content Engine (`ce`)
**Spec:** `docs/TDD-content-engine.md`
**Last session:** 2026-07-27 — completed WP-03

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
| WP-04 | Capture & transcription | 🔵 **next** | flip `ffmpeg`, `OPENAI_API_KEY` to required |
| WP-05 | Git harvest & safety gates ⚠️ | ⬜ | flip `gitleaks` to required. Planted-secret test is mandatory. |
| WP-06 | Index & dedupe | ⬜ | |
| WP-07 | External research | ⬜ | |
| WP-08 | Inventory generator (MATCH) ⭐ | ⬜ | **MVP milestone** — usable system after this |
| WP-09 | Writer & grader | ⬜ | |
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
