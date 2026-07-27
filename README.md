# Content Engine (`ce`)

Turns a finished project — its git history, your voice memos, your screen
captures — into publish-ready content for a static site, LinkedIn, Facebook
and YouTube.

Publishing to the three social platforms is **manual by design**. The engine
produces a package with per-platform copy, assets, and a review page; you post
it. That decision removes OAuth, platform audits, token refresh and API fees
from the system entirely.

---

## Status

**WP-00 complete.** The CLI contract is fully registered; `ce doctor` works.
Every other command is a stub that names the work package implementing it.

See [`STATUS.md`](STATUS.md) for progress and the next work package.

---

## Quick start

```powershell
# from the repo root
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"

ce doctor          # verify the environment
ce --help          # the full command contract
pytest             # 62 tests
```

`ce doctor` reports a △ for dependencies that later work packages need. Those
are informational — it only exits non-zero on something required *now*. Use
`ce doctor --strict` to see the full future requirement set.

---

## How it works

```
SELECT  →  BUILD  →  HARVEST  →  PRODUCE  →  SHIP
(human)    (human)   (auto)      (mixed)     (human)
```

1. **Select** — `ce sweep` surfaces recurring demand; you pick a project.
2. **Build** — you build it. Commit as normal. Record voice memos *while*
   things are going wrong, not after. `ce capture` ingests them.
3. **Harvest** — `ce harvest` extracts git history behind two non-bypassable
   safety gates, transcribes audio, researches externally, and produces 6–8
   candidate briefs.
4. **Produce** — you pick one brief. `ce produce` drafts, grades and revises
   until it scores, then stops for your edit. `ce verify` checks every factual
   claim. `ce assets` and `ce render` build the visuals and platform copy.
5. **Ship** — `ce package` writes `outbox/<piece>/REVIEW.html`. You post from
   it in about ten minutes and paste the URLs back.

One project yields several weeks of content. Build cadence and publish cadence
stay independent.

---

## Safety

Two gates cannot be bypassed, including by `--force`:

- **G1 · repo allowlist** — a repo not listed in `config/engine.yml` is
  invisible to the pipeline. Default deny.
- **G2 · secret scan** — `gitleaks` over the commit range, plus a path
  deny-list. Raw diffs are *never* sent to a language model; only commit
  messages, paths and line counts.

**Screenshots are not automatically scanned.** Nothing catches a token in
terminal scrollback. `REVIEW.html` carries a mandatory manual checklist listing
every image. This is a known, accepted residual risk — see TDD §6.2.

---

## Layout

```
config/     engine.yml, brand-brief.md, per-platform rules
docs/       the TDD and the product specs behind it
prompts/    versioned prompt files (ADR-004)
src/ce/     the package
data/       projects, captures, harvests, pieces  ← source of truth
outbox/     generated packages (gitignored)
tests/
```

`data/` is the source of truth and lives in git. `data/index.db` and
`data/.llm-cache/` are derived and rebuildable (`ce index rebuild`).

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/TDD-content-engine.md`](docs/TDD-content-engine.md) | **The spec.** Architecture, data model, CLI contract, work packages. |
| [`docs/DIY-Content-Engine-v3-Spec.md`](docs/DIY-Content-Engine-v3-Spec.md) | Product rationale — why the pipeline is shaped this way |
| [`docs/DIY-Content-Engine-v2.md`](docs/DIY-Content-Engine-v2.md) | Per-platform manual-posting gotchas |
| [`docs/DIY-Content-Engine-v2.1-Ingest.md`](docs/DIY-Content-Engine-v2.1-Ingest.md) | Transcription and git-extraction detail |
| [`config/brand-brief.md`](config/brand-brief.md) | Fill this in by hand before WP-08 |

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Unexpected error |
| 2 | Gate blocked — the message names the gate |
| 3 | Budget exceeded |
| 4 | Precondition unmet (e.g. article not edited) |
