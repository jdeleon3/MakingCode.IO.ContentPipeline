---
name: close-wp
description: Close out the current work package in Content Engine (ce) — run tests/lint, verify acceptance criteria, get an independent spec-conformance check, update STATUS.md, flip doctor required-flags, and stage a commit for your confirmation. Use when a WP's implementation looks done and you're ready to wrap it up.
---

Run these steps in order. Stop and report if any step fails — do not skip ahead.

1. **Identify the WP.** Read `STATUS.md`, find the 🔵 row. That's the WP being closed.

2. **Tests and lint.** Run `pytest`, `ruff check`, and `ruff format --check`. If anything fails, fix it before continuing — a WP is not done with failing tests or lint.

3. **Acceptance criteria.** Read the WP's section in `docs/TDD-content-engine.md` §12. Walk through each acceptance criterion and confirm the code satisfies it, citing `file:line`. If a criterion isn't met, stop here and report exactly what's missing — do not touch `STATUS.md`.

4. **Independent check.** Dispatch the `wp-spec-conformance` subagent (pass it the WP number) to verify the implementation against the same TDD section from a fresh read. This repo treats "one WP per session, acceptance criteria must pass" as a hard rule — this is the second pair of eyes that backs that up. Resolve anything it flags before continuing.

5. **Update `STATUS.md`.**
   - Flip the WP's status cell to ✅ done.
   - Add any deviations from the TDD you made along the way to "Deviations from the TDD" — record them now, not from memory later.
   - Update "Last session" and "Open questions" if anything changed.

6. **Doctor flags.** If this WP was listed in `STATUS.md`'s Notes column as flipping a dependency to required (e.g. "flip `X` to required"), make that change in `src/ce/doctor.py`.

7. **Stage, don't commit.** Run `git add` on the specific files that changed (not a blanket `-A`). Show the user `git status` and a `git diff --stat` summary, and propose a commit message. **Wait for explicit confirmation before running `git commit`** — this repo's permission settings intentionally keep commits in the ask-list, even for the routine end-of-WP commit.
