# CLAUDE.md

Instructions for working in this repo. Global defaults still apply except where overridden below.

## Session start (do this automatically, don't wait to be asked)

1. Read `STATUS.md`.
2. Find the next 🔵 work package in its table.
3. Read only that WP's section in `docs/TDD-content-engine.md` §12 (not the whole doc — orient once per session from TDD §0–3, then go straight to the current WP's section).

## Work package discipline — hard rule

One WP per session. Do not start a new WP until the current one's acceptance criteria pass and `STATUS.md` is updated. If asked to skip ahead, combine WPs, or start the next one early, push back and ask for explicit override before proceeding.

## Per-WP workflow

1. Implement the WP.
2. When it looks done, run the `close-wp` skill — it runs acceptance criteria, dispatches the `wp-spec-conformance` subagent as an independent check, updates `STATUS.md`, flips doctor required-flags, and stages a commit for your confirmation. See `.claude/skills/close-wp/SKILL.md` for the exact steps.

`ce --help` must run without error at all times — never leave it broken mid-WP. Commits stay in the permission ask-list even for this routine end-of-WP commit (see `.claude/settings.json`) — always confirm the message before it runs.

## Code style (overrides the global "minimal comments" default for this repo)

- DRY and SOLID: extract shared logic, keep modules single-purpose, prefer composition/dependency injection over ad-hoc coupling.
- Comment enough that someone with minimal context on this project can follow what a function/module is doing and why. This project wants more comments than the terse global default — but still comment intent and non-obvious decisions, not a line-by-line narration of obvious code.
- Match existing ruff config (`pyproject.toml`): line-length 100, py311, `E F I UP B SIM PTH` selected.

## Safety gates — never bypass, not even with `--force`

- **G1** repo allowlist (`config/engine.yml`) — a repo not listed is invisible to the pipeline.
- **G2** secret scan (gitleaks + path deny-list) — raw diffs never go to an LLM, only commit messages/paths/line counts.

## Key docs (read only what's needed, not the whole set every session)

- `docs/TDD-content-engine.md` — spec; work packages are in §12
- `STATUS.md` — current progress, next WP, deviations log
- `config/brand-brief.md` — must be hand-filled before WP-08
