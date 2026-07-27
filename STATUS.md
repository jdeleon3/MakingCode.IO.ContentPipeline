# Implementation Status

**Project:** Content Engine (`ce`)
**Spec:** `docs/TDD-content-engine.md`
**Last session:** 2026-07-27 — completed WP-01

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
| WP-02 | LLM gateway | 🔵 **next** | flip `ANTHROPIC_API_KEY` to required in `doctor.py` |
| WP-03 | Project lifecycle | ⬜ | |
| WP-04 | Capture & transcription | ⬜ | flip `ffmpeg`, `OPENAI_API_KEY` to required |
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
- **Media backup target:** _TODO — decide in WP-03._ `data/` is committed to git
  except `.llm-cache/`, `index.db`, `runs/`, and media (see `.gitignore`).
  Audio and video are large and regenerable-never; they need a home outside git.
- **API keys:** environment variables only, never `engine.yml` (TDD §14).

---

## Open questions

- Media backup location (blocks nothing until WP-04 produces real audio).
- `config/brand-brief.md` must be hand-written before WP-08. Template drafted;
  not yet filled in.
