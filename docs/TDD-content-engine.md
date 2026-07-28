# Content Engine — Technical Design Document

**Version:** 1.0
**Date:** 2026-07-26
**Status:** Approved for implementation
**Supersedes:** `DIY-Content-Engine-v3-Spec.md` (product spec — still the source of truth for *why*; this document is *how*)

---

## §0 — How to use this document across sessions

This TDD is written to be picked up cold by a session with no prior context.

**At the start of every implementation session:**

1. Read §0–§3 (orientation, ~5 min).
2. Read `STATUS.md` in the repo root to find the next unstarted work package.
3. Read the full spec for that one work package in §12.
4. Read only the sections §12 references.
5. Implement. Run acceptance tests. Update `STATUS.md`.

**`STATUS.md` is the single source of progress truth.** It is created in WP-00 and updated at the end of every session. Format:

```markdown
# Implementation Status
Last session: 2026-07-28 — completed WP-02

| WP | Name | Status | Notes |
|----|------|--------|-------|
| WP-00 | Scaffold & CLI | ✅ done | |
| WP-01 | Config & store | ✅ done | |
| WP-02 | LLM gateway | ✅ done | cache in data/.llm-cache/ |
| WP-03 | Project lifecycle | 🔵 next | |
| WP-04 | Capture & transcription | ⬜ | |

## Deviations from TDD
- WP-02: used `httpx` not `requests` (async needed later)

## Open questions
- none
```

**Rules for implementing sessions:**

- Work one WP at a time. Do not start the next until acceptance criteria pass.
- If you deviate from this TDD, record it under "Deviations" in `STATUS.md`. The TDD is not sacred; undocumented drift is.
- Every WP must leave the repo in a working state. `ce --help` must always run.
- Do not build ahead. WP-11's assets are not needed to validate WP-09.

---

## §1 — Table of contents

**Part I — High-level design**
- §2 Purpose and scope
- §3 System overview
- §4 Architecture decisions (ADRs)
- §5 Data model
- §6 Safety architecture

**Part II — Detailed design**
- §7 Repository layout
- §8 Configuration
- §9 CLI contract
- §10 Component specifications
- §11 Prompt contracts

**Part III — Delivery**
- §12 Work packages
- §13 Testing strategy
- §14 Operational concerns
- §15 Future / explicitly out of scope

---

# PART I — HIGH-LEVEL DESIGN

## §2 Purpose and scope

### 2.1 Problem statement

A solo technical operator explores projects, builds them in git, and records audio reflections. That raw material — commits, voice, screenshots — contains publishable content, but converting it into finished pieces for four channels (personal site, LinkedIn, Facebook, YouTube) is manual, slow, and therefore doesn't happen.

### 2.2 What the system does

Ingests a completed project (git history + audio captures + screen captures), enriches it with external research, and produces a **content inventory** of 6–8 candidate pieces. For each piece the operator selects, it drafts, grades, revises, verifies, and renders a publish-ready package with assets and per-platform copy.

### 2.3 What the system explicitly does not do

| Not doing | Why |
|---|---|
| Publish to LinkedIn / Facebook / YouTube via API | Manual posting by design — removes all OAuth, audits, token refresh |
| Multi-tenant / multi-user | Single operator |
| Real-time or scheduled unattended execution | Human is present at every stage; no server needed |
| Replace operator editing | The 30-minute human edit is a required stage, not a fallback |
| Generate long-form video from text | Screen capture + real audio is the design |

### 2.4 Success criteria

| # | Criterion | Measure |
|---|---|---|
| S1 | Operator time per published piece | ≤ 45 min |
| S2 | Pieces harvested per project | ≥ 6 candidate briefs |
| S3 | Running cost | ≤ $20/month |
| S4 | Zero secret leakage | No credential ever reaches a draft or published artifact |
| S5 | Resumability | Any stage re-runnable without redoing prior work |

### 2.5 Scale assumptions

These bound every design decision. Revisit the design if any is exceeded by 10×.

- ~1 project per 2–3 weeks
- ~6–8 pieces per project, ~1 published per week
- Lifetime corpus < 1,000 pieces
- Audio < 5 hours/month
- Single operator, single machine, no concurrency

---

## §3 System overview

### 3.1 Stage pipeline

```
 STAGE 0        STAGE 1         STAGE 2          STAGE 3         STAGE 4
 SELECT    →    BUILD      →    HARVEST     →    PRODUCE    →    SHIP
 (human)        (human)         (automated)      (mixed)         (human)

 sweep          git commits     git extract      pick brief      post manually
 rank           audio clips     transcribe       draft           paste URLs back
 pick           screenshots     research         grade/revise    metrics later
                friction.md     dedupe           verify
                                → inventory      assets
                                                 renditions
                                                 → REVIEW.html
```

### 3.2 Execution model

**Every stage is a CLI invocation the operator runs deliberately.** There is no daemon, no scheduler, no server. This is a direct consequence of §2.5 — at one project per fortnight, unattended execution solves a problem that does not exist, and would add a VPS, process supervision, and failure alerting for zero benefit.

The optional local GUI (ADR-009) does not change this: it is a thin, operator-launched wrapper over the same CLI invocations, not a background service, and it has no existence when not explicitly running.

Each stage is **idempotent and resumable**: it writes a `_manifest.json` recording an input hash; re-running with unchanged inputs is a no-op unless `--force`.

### 3.3 Component map

```
┌──────────────────────────────────────────────────────────┐
│                      ce (CLI)                             │
└───┬──────────┬──────────┬──────────┬──────────┬──────────┘
    │          │          │          │          │
┌───▼───┐ ┌────▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼─────┐
│capture│ │ harvest │ │produce │ │ assets │ │ package │
└───┬───┘ └────┬────┘ └───┬────┘ └───┬────┘ └───┬─────┘
    │          │          │          │          │
    └──────────┴────┬─────┴──────────┴──────────┘
                    │
        ┌───────────┼───────────┬──────────────┐
        │           │           │              │
   ┌────▼────┐ ┌────▼────┐ ┌────▼────┐  ┌──────▼──────┐
   │  store  │ │   llm   │ │  gates  │  │   config    │
   │ (files) │ │ gateway │ │(safety) │  │             │
   └────┬────┘ └─────────┘ └─────────┘  └─────────────┘
        │
   ┌────▼────┐
   │ index   │  derived, rebuildable: embeddings, metrics
   │(sqlite) │
   └─────────┘
```

---

## §4 Architecture decisions

Recorded as ADRs so future sessions know what is settled and what is open.

### ADR-001 — Python 3.11+ for the pipeline
**Decision:** Pipeline in Python. Site remains Astro/Node.
**Rationale:** Transcription clients, git parsing (`pygit2`/subprocess), Playwright, image handling, and LLM SDKs are all strongest in Python. The site is a separate concern with no code sharing.
**Consequences:** Two toolchains in one repo. Acceptable — they interact only through the filesystem and a `git push`.
**Reversible:** Yes, but only cheaply before WP-04.

### ADR-002 — Filesystem is the source of truth; SQLite is a derived index
**Decision:** All content artifacts are files (markdown, YAML, media) under `data/`. SQLite holds only derived data (embeddings, metrics cache) and must be fully rebuildable via `ce index rebuild`.
**Rationale:** Content in git is diffable, inspectable, and portable — a stated product value. But dedupe needs vector search and metrics need aggregation, which are miserable in flat files.
**Consequences:** Some duplication. `index.db` is gitignored.
**Alternatives rejected:** Postgres (operational weight for a single user); pure-filesystem (dedupe becomes O(n) file reads — tolerable now, unpleasant at 500 pieces).

### ADR-003 — Brute-force cosine similarity, not a vector database
**Decision:** Embeddings stored as a numpy array; similarity by full scan.
**Rationale:** At <1,000 documents (§2.5) a full scan is sub-millisecond. `sqlite-vec`, Chroma, or pgvector would be dependencies bought with no measurable benefit.
**Trigger to revisit:** corpus > 10,000 documents.

### ADR-004 — Prompts are versioned files, not inline strings
**Decision:** Every LLM call loads a prompt from `prompts/<id>.md` with YAML frontmatter declaring model tier, output schema, and version.
**Rationale:** Prompts are the highest-churn, highest-impact part of this system. Inline strings can't be diffed meaningfully, A/B'd, or reviewed. Output quality regressions must be traceable to a prompt version.
**Consequences:** Every LLM response records the prompt version that produced it.

### ADR-005 — Safety gates fail closed
**Decision:** `gitleaks`, repo allowlist, dedupe, and claim verification all halt the pipeline on failure. No warn-and-continue.
**Rationale:** The failure mode (publishing a credential, or a fabricated claim under your own name) is unrecoverable. A blocked run costs minutes.
**Consequences:** `--force` exists but must never bypass `gitleaks` or the allowlist. This is enforced in code, not convention.

### ADR-006 — Single-file, serverless `REVIEW.html`
**Decision:** The package output is one self-contained HTML file — inlined CSS/JS, no network requests, no build step.
**Rationale:** Must work by double-clicking from a file manager, forever, with no running process.
**Consequences:** URL write-back can't POST to a server. Instead it generates a `ce posted ...` command for the operator to paste. See §10.8.

### ADR-007 — LLM responses are cached by content hash
**Decision:** All LLM calls cache to `data/.llm-cache/<sha256>.json`, keyed on `(prompt_id, version, rendered_vars, model)`.
**Rationale:** Development iteration on a downstream stage would otherwise re-pay for upstream calls repeatedly. Also makes tests deterministic and free.
**Consequences:** `--no-cache` needed when deliberately regenerating.

### ADR-008 — Human edit is a pipeline stage, not an optional step
**Decision:** `ce produce` stops after generating `article.md` and exits with instructions. Publishing requires a separate `ce publish` invocation that refuses to run unless `article.md` mtime is newer than its generation timestamp.
**Rationale:** The quality difference between edited and unedited AI drafts is the whole ballgame. Making it structurally impossible to skip is worth the friction.
**Consequences:** Overridable with `--no-edit-check` for testing only.

### ADR-009 — On-demand local web GUI, not a daemon
**Decision:** `ce gui` starts a FastAPI/Uvicorn server bound to `127.0.0.1` only, for as long as the operator has it open. No scheduled task, no background service, no process that outlives the operator closing it.
**Rationale:** §3.2's "no daemon, no scheduler, no server" ruled out *unattended* execution, not a locally-launched, operator-present convenience surface — the GUI still requires the operator to launch it, and every action it takes shells out to the same `ce` CLI commands (§9) a human would type, so every safety gate (§6) and the ADR-008 edit check still run exactly as they would from a terminal. §15 originally deferred a web UI until "REVIEW.html + CLI proves insufficient after 10 published pieces" — overridden 2026-07-28, before that trigger fired (zero pieces published at the time), by explicit operator decision after being walked through the tradeoff. See STATUS.md deviations.
**Consequences:** Two new optional dependencies, `fastapi` and `uvicorn`, under `[project.optional-dependencies].gui` — same "optional extra" shape as WP-11's `playwright` (`pip install` alone doesn't make the pipeline itself need a running server). No authentication: binding to loopback only is the entire security model, matching this repo's existing "single operator, single machine" scale assumption (§2.5). The GUI must never become the only way to do something — every screen is a thin wrapper over an existing CLI command; the CLI stays fully functional with the GUI never installed.
**Reversible:** Yes — deleting `src/ce/gui/` and the `gui` extra fully removes it. Nothing outside `gui/` depends on it (the GUI depends on the CLI/store, never the reverse).

---

## §5 Data model

### 5.1 Entity relationships

```
Project 1──* Capture       (audio | screenshot | screencast | friction)
        1──1 Harvest       (git extract + research + redaction report)
        1──* Brief         (candidate pieces, 6-8 per project)
Brief   1──0..1 Piece      (a brief becomes a piece when selected)
Piece   1──* Rendition     (one per target platform)
        1──* Asset         (hero, diagram, code card, thumbnail, video)
        1──* PostRecord    (one per platform actually posted)
PostRecord 1──* MetricSnapshot
```

### 5.2 Schemas

Stored as YAML on disk. Validated with Pydantic models at load.

**`project.yml`**
```yaml
slug: streaming-etl-duckdb        # [a-z0-9-]+, immutable, primary key
title: "Streaming ETL with DuckDB"
status: active                     # active | harvested | complete | abandoned
started_at: 2026-07-14
ended_at: null
repos:                             # must all appear in config allowlist
  - name: streaming-etl
    path: ~/code/streaming-etl
    publishable: full              # full | lessons-only
selection:
  demand_signals: ["HN 3 threads", "inbound x2"]
  hypothesis: "DuckDB replaces Spark for <100GB workloads"
  expected_failure_surface: "memory limits on joins"
tags: [duckdb, etl, data]
```

**`capture.yml`** (one per capture, in `captures/`)
```yaml
id: cap-20260716-1423
project: streaming-etl-duckdb
type: audio                        # audio | screenshot | screencast | friction
moment: in_situ                    # in_situ | retro
captured_at: 2026-07-16T14:23:00Z
source_path: captures/audio/raw/20260716-1423.m4a
derived:
  transcript_raw: captures/audio/transcript/cap-20260716-1423.raw.txt
  transcript_clean: captures/audio/transcript/cap-20260716-1423.clean.md
  duration_sec: 94
context: "hit the OOM on the 40GB join"
```

**`brief.yml`** (array in `harvest/briefs.yml`)
```yaml
- id: br-01
  project: streaming-etl-duckdb
  archetype: what_went_wrong       # see §5.3
  title: "DuckDB's memory limit is not what the docs imply"
  angle: "counter-position"
  target_platforms: [site, linkedin]
  demand:
    recurrence: 3                  # sweeps out of last 4
    signals: ["HN thread 412pts", "inbound @user 2026-07-14"]
  evidence:
    - kind: git
      ref: "a3f9c21"
      note: "reverted the streaming join, -340 lines"
    - kind: audio
      ref: "cap-20260716-1423@02:10"
      quote: "the spill-to-disk never triggered, it just died"
  grounding_strength: strong       # strong | moderate | weak  (weak = blocked)
  dedupe_max_similarity: 0.31
  weakest_point: "n=1, single workload shape, 40GB"
  risk_flags: []
  status: candidate                # candidate | selected | produced | published | dropped
```

**`piece.yml`**
```yaml
id: pc-0007
brief_id: br-01
project: streaming-etl-duckdb
slug: duckdb-memory-limit-reality
status: drafted                    # drafted | edited | verified | published
created_at: 2026-07-26T09:00:00Z
article_path: article.md
generated_at: 2026-07-26T09:04:11Z  # ADR-008 edit check compares mtime to this
grades:
  - attempt: 1
    total: 6.8
    scores: {hook: 6, evidence: 8, specificity: 7, voice: 6, cta: 5}
  - attempt: 2
    total: 8.4
    scores: {hook: 9, evidence: 9, specificity: 8, voice: 7, cta: 7}
verification:
  claims_checked: 7
  claims_failed: 0
  ran_at: 2026-07-26T10:30:00Z
published:
  url: https://example.com/blog/duckdb-memory-limit-reality
  at: 2026-07-26T11:00:00Z
```

**`posted.yml`** (global, at `data/posted.yml`)
```yaml
- piece_id: pc-0007
  platform: linkedin
  url: https://linkedin.com/posts/...
  posted_at: 2026-07-26T12:00:00Z
  metrics:
    - at: 2026-07-27T12:00:00Z
      impressions: 4200
      reactions: 87
      comments: 14
      site_clicks: 133          # from UTM, authoritative
```

### 5.3 Brief archetypes

Fixed enum. The inventory generator must attempt one brief of each applicable archetype.

| Archetype | Primary source | Default platforms |
|---|---|---|
| `why_this_project` | selection metadata, early commits | site, linkedin |
| `build_walkthrough` | git history, README | site, youtube |
| `what_went_wrong` | audio `in_situ` clips | linkedin, site |
| `i_was_wrong` | revert commits + audio | linkedin |
| `tool_review` | dependency changes + audio | site, linkedin |
| `specific_gotcha` | one commit + one audio moment | site |
| `retrospective` | audio `retro` | linkedin, facebook |
| `video_walkthrough` | screencast + audio | youtube |

### 5.4 Directory-as-database

Path conventions are load-bearing. See §7.

---

## §6 Safety architecture

Four gates. Each is a module in `src/ce/gates/` exposing `check(ctx) -> GateResult`. A `GateResult` with `passed=False` and `blocking=True` halts the run.

### 6.1 G1 — Repo allowlist (blocking, non-bypassable)

Runs before any git access. A repo path not present in `config.repos.allowed` raises immediately. Path comparison is on resolved absolute paths — no symlink or `..` escapes.

`publishable: lessons-only` propagates into every downstream prompt as a hard constraint: no code quotes, no repo name, no file paths, no architecture specifics.

### 6.2 G2 — Secret scan (blocking, non-bypassable)

`gitleaks detect --source <repo> --report-format json --no-git` over the commit range, plus a deny-list path filter applied before any content is read:

```
.env*  *.pem  *.key  *.p12  *.pfx  id_rsa*  secrets/  credentials*
*.tfstate  .npmrc  .pypirc  **/fixtures/**  **/seed*/**
```

**Additionally, and this is the part tooling cannot do for you:** raw diffs are never sent to an LLM. Only commit messages, file paths, and line-count statistics. If code context is genuinely needed for a piece, the operator hand-selects the snippet into `evidence/` explicitly.

Screenshots are scanned by *nothing*. The packager emits a mandatory manual review checklist (§10.8) listing every image at full path. This is a known, accepted residual risk — document it in `REVIEW.html`, do not pretend it's automated.

### 6.3 G3 — Dedupe (blocking, bypassable with `--force`)

Cosine similarity of the candidate's embedding against all published pieces. Threshold `0.88` (configurable). Above threshold, the brief is blocked with the colliding piece named.

### 6.4 G4 — Claim verification (blocking, bypassable with `--force`)

After drafting, extract discrete factual assertions, classify each, and verify:

| Class | Verification |
|---|---|
| `grounded` | Must map to a `capture` or commit ref. Fail if unmappable. |
| `external` | Must be supported by a fetched source. Web search + fetch. |
| `opinion` | No verification; must be linguistically marked as opinion |
| `unverifiable` | Blocks. Either ground it, soften it, or cut it. |

Output `verification.json`; block on any `unverifiable` or failed `grounded`.

### 6.5 Budget governor

Not a gate but the same shape. Before every LLM call, `llm.gateway` checks the month-to-date total in `data/ledger.jsonl` against `config.llm.budget.monthly_usd`. On exceed: `halt` (default) or `degrade` (drop to the cheap model tier). Per-run cap likewise.

---

# PART II — DETAILED DESIGN

## §7 Repository layout

```
content-engine/
├─ STATUS.md                      ← session progress. Read first.
├─ README.md
├─ pyproject.toml                 ← package + deps + ruff/pytest config
├─ .gitignore                     ← data/.llm-cache, data/index.db, *.m4a, *.mp4
│
├─ config/
│  ├─ engine.yml                  ← §8
│  ├─ brand-brief.md              ← hand-written, highest-leverage file
│  └─ platforms/
│     ├─ linkedin.yml
│     ├─ facebook.yml
│     ├─ youtube.yml
│     └─ site.yml
│
├─ prompts/                       ← ADR-004
│  ├─ _schemas/
│  │  ├─ briefs.schema.json
│  │  ├─ grade.schema.json
│  │  └─ claims.schema.json
│  ├─ brief_generate.md
│  ├─ article_draft.md
│  ├─ article_grade.md
│  ├─ article_revise.md
│  ├─ claim_extract.md
│  ├─ rendition_linkedin.md
│  ├─ rendition_facebook.md
│  ├─ rendition_youtube.md
│  ├─ commit_summarize.md
│  └─ transcript_clean.md
│
├─ src/ce/
│  ├─ __init__.py
│  ├─ cli.py                      ← Typer app, subcommand registration only
│  ├─ config.py                   ← Pydantic settings, loads engine.yml
│  ├─ models.py                   ← all Pydantic entities (§5.2)
│  ├─ store.py                    ← filesystem CRUD, path resolution, manifests
│  ├─ index.py                    ← SQLite + embeddings, rebuildable
│  ├─ llm/
│  │  ├─ gateway.py               ← §10.1
│  │  ├─ prompts.py               ← loader, frontmatter, rendering
│  │  ├─ cache.py
│  │  └─ ledger.py                ← cost accounting
│  ├─ gates/
│  │  ├─ allowlist.py             ← G1
│  │  ├─ secrets.py               ← G2
│  │  ├─ dedupe.py                ← G3
│  │  └─ claims.py                ← G4
│  ├─ capture/
│  │  ├─ audio.py                 ← ffmpeg preprocess + transcribe
│  │  └─ ingest.py                ← screenshots, screencasts, friction.md
│  ├─ harvest/
│  │  ├─ git.py                   ← extract + significance scoring
│  │  ├─ research.py              ← external sources
│  │  └─ inventory.py             ← brief generation (the MATCH step)
│  ├─ produce/
│  │  ├─ writer.py                ← draft → grade → revise loop
│  │  └─ renditions.py            ← per-platform adaptation
│  ├─ assets/
│  │  ├─ diagram.py               ← Mermaid → PNG
│  │  ├─ codecard.py              ← Playwright HTML → PNG
│  │  ├─ thumbnail.py
│  │  └─ templates/               ← HTML/CSS for the above
│  ├─ package/
│  │  ├─ builder.py               ← outbox assembly
│  │  └─ review_html.py           ← §10.8
│  ├─ publish/
│  │  └─ site.py                  ← Astro frontmatter + git commit/push
│  ├─ sweep/
│  │  ├─ hn.py
│  │  └─ rss.py
│  ├─ metrics/
│  │  ├─ umami.py
│  │  └─ youtube.py
│  └─ gui/                        ← §10.10, ADR-009 — optional, `pip install ce[gui]`
│     ├─ app.py                   ← FastAPI app factory, `ce gui` entry point
│     ├─ runner.py                ← shells out to `ce`, tails its §14 run log
│     ├─ routes/                  ← one module per screen
│     ├─ templates/                ← Jinja2, server-rendered, HTMX partials
│     └─ static/                  ← vendored htmx.js + CSS, no CDN
│
├─ data/                          ← §5.4
│  ├─ projects/<slug>/
│  │  ├─ project.yml
│  │  ├─ captures/
│  │  │  ├─ audio/{raw,transcript}/
│  │  │  ├─ screens/
│  │  │  ├─ screencast/
│  │  │  ├─ friction.md
│  │  │  └─ *.capture.yml
│  │  ├─ harvest/
│  │  │  ├─ _manifest.json
│  │  │  ├─ git.json
│  │  │  ├─ redaction-report.json
│  │  │  ├─ research.json
│  │  │  ├─ briefs.yml
│  │  │  └─ inventory.md          ← human-readable, what you actually read
│  │  └─ pieces/<piece-id>/
│  │     ├─ piece.yml
│  │     ├─ article.md            ← you edit this
│  │     ├─ grades.json
│  │     ├─ verification.json
│  │     ├─ renditions/{linkedin,facebook,youtube}.yml
│  │     └─ assets/
│  ├─ posted.yml
│  ├─ inbound.md                  ← hand-maintained
│  ├─ sweeps/<date>.md
│  ├─ ledger.jsonl                ← append-only cost log
│  ├─ index.db                    ← derived, gitignored
│  └─ .llm-cache/                 ← gitignored
│
├─ outbox/<piece-id>/             ← gitignored; the deliverable
├─ voice/                         ← your prior writing, for RAG
└─ tests/
   ├─ fixtures/sample-project/
   ├─ golden/
   └─ test_*.py
```

---

## §8 Configuration

**`config/engine.yml`** — complete reference.

```yaml
identity:
  name: John
  site_url: https://example.com
  site_repo: ~/code/site
  timezone: America/New_York

repos:
  allowed:
    - name: content-engine
      path: ~/code/content-engine
      publishable: full
    - name: client-thing
      path: ~/code/client-thing
      publishable: lessons-only

llm:
  provider: anthropic
  models:
    reasoning: claude-opus-5        # briefs, grading
    default:   claude-sonnet-5      # drafting, renditions
    cheap:     claude-haiku-4-5     # classification, cleanup
  budget:
    monthly_usd: 20
    per_run_usd: 2.00
    on_exceed: halt                 # halt | degrade
  retry:
    max_attempts: 4
    backoff_base_sec: 2

transcription:
  provider: openai
  model: gpt-4o-mini-transcribe     # $0.003/min
  vocabulary:                       # prompt hint — reduces jargon mangling
    - DuckDB
    - Astro
    - Cloudflare
  preprocess:
    silence_threshold_db: -40
    silence_min_sec: 1.5
    loudnorm: true

embeddings:
  provider: openai
  model: text-embedding-3-small

gates:
  allowlist: hard_fail              # not configurable to anything else
  secrets: hard_fail                # not configurable to anything else
  dedupe:
    threshold: 0.88
    scope_days: 365
  claims:
    enabled: true
    block_on_unverifiable: true

produce:
  min_grade: 8.0
  max_attempts: 3
  grade_weights:
    hook: 0.30
    evidence: 0.30
    specificity: 0.20
    voice: 0.10
    cta: 0.10

harvest:
  git:
    lookback_days: 60
    min_significance: 2
  research:
    max_sources: 8
  inventory:
    min_briefs: 6
    max_briefs: 8

utm:
  template: "?utm_source={platform}&utm_medium=social&utm_campaign={slug}"
```

**`config/platforms/linkedin.yml`**
```yaml
name: linkedin
max_chars: 3000
hook_chars: 200                     # must land above "see more"
links_in_body: false                # → first comment (v2 §5)
supports_markdown: false
allow_unicode_styling: false        # accessibility
line_break_style: double
assets:
  image: {w: 1200, h: 1200, formats: [png]}
extras:
  - first_comment                   # required when a link exists
```

---

## §9 CLI contract

Built with Typer. `ce --help` must always work, even mid-implementation.

```
ce project new <slug> [--title T] [--repo PATH]...
ce project list [--status S]
ce project show <slug>
ce project close <slug> [--abandoned]

ce capture audio <file> [--project P] [--moment in_situ|retro] [--context TEXT]
ce capture screen <file> [--project P] [--context TEXT]
ce capture friction "<one line>" [--project P]
ce capture list <project>

ce harvest <project> [--force] [--skip-research]
      → runs: G1 → git extract → G2 → transcribe pending → research
              → dedupe → inventory
      → writes harvest/{git.json,research.json,briefs.yml,inventory.md}

ce brief list <project> [--status S]
ce brief select <brief-id>            → creates a Piece, returns piece-id

ce produce <piece-id> [--force] [--no-cache]
      → draft → grade → revise loop → article.md
      → STOPS. prints "edit article.md, then: ce verify <piece-id>"

ce verify <piece-id> [--force]        → G4 claim verification
ce assets <piece-id> [--only KIND]
ce render <piece-id> [--platform P]...
ce package <piece-id>                 → outbox/<piece-id>/ + REVIEW.html
ce publish site <piece-id> [--dry-run]

ce posted <piece-id> --platform P --url URL   ← pasted from REVIEW.html
ce metrics pull [--since DATE]

ce sweep [--sources hn,rss]
ce index rebuild
ce cost [--month YYYY-MM]
ce doctor                             → verify env: ffmpeg, gitleaks, playwright, keys

ce gui [--port 8420]                  → localhost web dashboard, §10.10 / ADR-009
```

**Global flags:** `--verbose`, `--dry-run`, `--config PATH`

**Exit codes:** `0` ok · `1` unexpected error · `2` gate blocked (message names the gate) · `3` budget exceeded · `4` precondition unmet (e.g. unedited article)

---

## §10 Component specifications

### 10.1 `llm/gateway.py`

```python
def complete(
    prompt_id: str,
    vars: dict,
    *,
    schema: dict | None = None,     # JSON schema → structured output
    tier: str = "default",          # reasoning | default | cheap
    cache: bool = True,
) -> LLMResult
```

`LLMResult`: `{content, parsed, model, prompt_version, in_tokens, out_tokens, usd, cache_hit}`

**Sequence:**
1. Load prompt (id + frontmatter version) from `prompts/`.
2. Render with `vars` (Jinja2, `StrictUndefined` — missing var is an error, not a silent blank).
3. Compute cache key `sha256(prompt_id|version|rendered|model|schema)`. On hit, return with `cache_hit=True`, no ledger entry.
4. Budget check (§6.5). Exceed → raise `BudgetExceeded` (exit 3).
5. Call provider. Retry on 429/5xx with exponential backoff + jitter, `max_attempts` from config.
6. If `schema`: validate. On failure, one repair attempt appending the validation error; then raise.
7. Append to `ledger.jsonl`, write cache, return.

**`ledger.jsonl` record:**
```json
{"ts":"2026-07-26T09:04:11Z","prompt":"article_draft","version":3,
 "model":"claude-sonnet-5","in":8200,"out":1900,"usd":0.0512,
 "piece":"pc-0007","cache_hit":false}
```

### 10.2 `capture/audio.py`

```python
def ingest(path: Path, project: str, moment: str, context: str) -> Capture
def transcribe(capture: Capture) -> Capture   # idempotent
```

**Preprocess** (ffmpeg, before transcription — mitigates the silence-hallucination failure):
```
-af "silenceremove=stop_periods=-1:stop_duration=1.5:stop_threshold=-40dB,loudnorm"
-ar 16000 -ac 1
```

**Transcribe:** provider from config, passing `config.transcription.vocabulary` as the `prompt` parameter.

**Outputs two files.** `raw.txt` is verbatim, never modified. `clean.md` is a `transcript_clean` LLM pass that adds paragraph breaks, fixes obvious ASR errors, and **preserves self-corrections, tangents, and hedges verbatim** — the prompt states this explicitly as its primary constraint. Downstream, `article_draft` receives *both*: raw for voice, clean for structure.

**Chunking:** files > 24MB are split on silence boundaries (never mid-word), transcribed separately, concatenated with a timestamp offset.

### 10.3 `harvest/git.py`

```python
def extract(project: Project, lookback_days: int) -> GitHarvest
```

1. G1 allowlist check per repo (raise on miss).
2. `git log --since --numstat --pretty=format:'%H|%aI|%an|%s%n%b'`
3. Apply path deny-list (§6.2) — matched files are dropped before any content is read.
4. G2 `gitleaks` over the range. Any finding → raise, write `redaction-report.json`, exit 2.
5. Score significance:

```python
SIGNIFICANCE = [
    (r"^(revert|fixup)", +3, "reversal"),
    ("reverts_recent_commit_within_14d", +3, "reversal"),
    ("message_len > 100", +2, "explained"),
    ("deletions > 100", +2, "large_deletion"),
    ("touches_dependency_manifest", +2, "tooling_change"),
    ("fix_after_feature_gap_gt_2d", +1, "war_story"),
    ("touches docs/ or adr/", +1, "written_thinking"),
    (r"^(chore|style|typo|bump|wip|fmt|lint)", -5, "noise"),
]
# keep if score >= config.harvest.git.min_significance
```

6. `commit_summarize` LLM pass over kept commits — **messages, paths, and stats only, never diffs** (§6.2).

**Output `git.json`:** `{repo, range, total_commits, kept, dropped, commits:[{sha, at, msg, files_changed, insertions, deletions, score, reasons[], summary}], redaction:{scanned, findings:0}}`

### 10.4 `harvest/inventory.py` — the MATCH step

The most important component. Single `reasoning`-tier call.

**Inputs assembled into the prompt:**
- `brand-brief.md`
- `project.yml` (incl. selection hypothesis and expected failure surface)
- `git.json` (summarized commits)
- All transcripts — **raw and clean**, with capture IDs and timestamps for citation
- `friction.md`
- `research.json`
- Recent `sweeps/*.md` and `inbound.md` for demand signals
- Titles + one-line summaries of the last 90 days of published pieces (dedupe context)
- Archetype list (§5.3)

**Output:** validated against `briefs.schema.json`, 6–8 briefs.

**Hard prompt constraints:**
- Every `evidence` entry must cite a real capture ID or commit SHA present in the input. Post-validate: any citation not resolvable → reject and retry once.
- `grounding_strength: weak` briefs are emitted but marked `status: dropped` and cannot be selected.
- `weakest_point` is required and non-empty for every brief.
- For `publishable: lessons-only` repos: no code, no repo names, no file paths.

**Post-processing:** run G3 dedupe on each brief; annotate `dedupe_max_similarity`; mark blocked. Write both `briefs.yml` (machine) and `inventory.md` (human-readable, ranked, what the operator actually reads).

### 10.5 `produce/writer.py`

```python
def produce(piece: Piece, *, force=False) -> Piece
```

Loop:
```
draft = complete("article_draft", {...})
for attempt in 1..max_attempts:
    grade = complete("article_grade", {article: draft}, schema=grade.schema.json)
    record grade
    if grade.total >= min_grade: break
    draft = complete("article_revise", {article: draft, fixes: grade.top_fixes})
write article.md
set piece.generated_at = now()      # ADR-008
print next-step instructions
```

**`article_draft` receives:** brand brief, the selected brief, all cited evidence *in full* (relevant transcript excerpts, commit summaries, research), voice RAG (top-5 chunks from `voice/`), and platform-agnostic length target.

**Grade rubric** (`grade.schema.json`), weights from config:

| Dimension | What it measures |
|---|---|
| `hook` | Does the first 200 chars earn the next 200? Scored standalone. |
| `evidence` | Fraction of claims traceable to a cited capture/commit/source. **The dimension that makes this system different.** |
| `specificity` | Concrete numbers, names, versions, error messages vs. generalities |
| `voice` | Similarity to `voice/` corpus and brand brief; penalizes LLM register |
| `cta` | Is the next action clear and singular? |

Returns per-dimension scores, weighted total, and `top_fixes: [{dimension, issue, suggested_change, impact}]` ranked by impact.

**A 10 is not achievable by construction** — the prompt states the ceiling is 9.5, to prevent the loop terminating on flattery.

### 10.6 `produce/renditions.py`

Per platform, load `config/platforms/<p>.yml` and call `rendition_<p>`.

Post-generation **mechanical validation** (not LLM-judged):
- `len(body) <= max_chars`
- if `links_in_body: false` → assert no URL in body; assert `first_comment` present and contains the UTM'd canonical URL
- if `supports_markdown: false` → assert no `**`, `_`, `#`, `[](...)` survive
- if `allow_unicode_styling: false` → assert body is ASCII + standard punctuation only
- LinkedIn: assert first `hook_chars` contain no URL and end at a sentence boundary
- YouTube: `len(title) <= 60`; description first 150 chars contain the URL; chapters start at `00:00` and ascend

Validation failure → one regeneration attempt with the specific violation appended, then exit 1.

### 10.7 `assets/`

| Module | Input | Method | Output |
|---|---|---|---|
| `diagram.py` | Mermaid source (LLM-generated or hand) | `mermaid-cli` → PNG | 1600px wide, transparent |
| `codecard.py` | snippet + lang | Jinja HTML → Playwright screenshot | per-platform dims |
| `thumbnail.py` | title, screenshot, optional face | Jinja HTML → Playwright | 1280×720 |
| — | screenshots | copy + **manual review flag** | as-is |

All Playwright renders use `deviceScaleFactor=2`. Templates in `assets/templates/`, styled from `config/brand.css` so every asset matches the site.

### 10.8 `package/review_html.py`

Single self-contained HTML file (ADR-006). Inlined CSS/JS. Images referenced by **relative path** so the folder is portable.

**Contents:**
1. Header: piece title, canonical URL, publish timestamp.
2. **⚠️ Manual review checklist** — every image at full path with a checkbox, and explicit text: *"Screenshots are not automatically scanned for secrets. Open each at full size and check for tokens, customer data, notifications, and open tabs."* (§6.2 residual risk.)
3. Per platform: copy box with **Copy** button (`navigator.clipboard`), live character counter against that platform's limit turning red on exceed, image preview + path, and a posting-order checklist.
4. LinkedIn shows body and first-comment as two separate copy boxes, labelled in posting order.
5. Facebook shows a **"Run the Sharing Debugger first"** link to `developers.facebook.com/tools/debug/?q=<url>` — pre-filled. (v2 §5.)
6. Footer: three URL input fields; a **Generate command** button producing the exact `ce posted` invocations to paste into a terminal. No server, no localStorage.

### 10.9 `publish/site.py`

1. Assert `article.md` mtime > `piece.generated_at` (ADR-008), else exit 4.
2. Assert `verification.json` exists and passed.
3. Transform to Astro content collection format: frontmatter (`title`, `description`, `pubDate`, `tags`, `heroImage`, `canonical`).
4. Copy assets into the site repo's asset dir.
5. Commit and push to `config.identity.site_repo`.
6. Poll the canonical URL until 200 (max 120s) — Cloudflare Pages build.
7. Fetch and assert `og:title`, `og:description`, `og:image` are present and non-empty. **This must pass before renditions are packaged**, because Facebook caches its first scrape.
8. Write `piece.published.url`.

### 10.10 `gui/` — local web dashboard (ADR-009)

FastAPI + Jinja2 + HTMX, server-rendered. No Node/npm build step, no SPA framework, no CDN — `static/` vendors htmx.js so the GUI works offline like everything else in this repo. Binds `127.0.0.1` only; no authentication (§2.5 single-operator scale, same trust boundary as running the CLI itself).

**Hard rule the whole module follows:** the GUI never imports pipeline modules (`harvest/`, `produce/`, `gates/`, ...) and never reimplements their logic. Every action is either (a) a **read** of a file `store.py` already knows how to read, or (b) a **write** to the exact file the CLI would write, or (c) a subprocess invocation of the real `ce` entry point. This is what keeps the GUI from drifting out of sync with the CLI it wraps — there is exactly one implementation of "what harvest does," and the GUI is never it.

```python
# runner.py
def run_command(args: list[str], *, cwd: Path) -> RunHandle
def stream_run(run_id: str) -> Iterator[RunEvent]   # tails the §14 run log
```

`run_command` launches `["ce", *args]` as a subprocess (never an in-process import) and returns immediately with the run's log path (§14: every run already writes `data/runs/<ts>-<command>.log`). `stream_run` tails that file over Server-Sent Events rather than piping the subprocess's stdout directly — a run keeps executing if the browser tab is closed, and reloading the page mid-run (or after it finished) replays the same log from the top instead of showing a blank console. `RunEvent = {line: str} | {done: True, exit_code: int}`.

**Screens** (routes/, one module each):

| Route | Reads | Writes | Runs |
|---|---|---|---|
| `/` dashboard | every `project.yml` | — | — |
| `/projects/<slug>` | project + capture/harvest/piece counts | — | — |
| `/projects/<slug>/briefs` | `briefs.yml`, `inventory.md` | — | `ce brief select` |
| `/pieces/<id>` | `article.md`, `grades.json`, `verification.json` | `article.md` | `ce verify`, `ce assets`, `ce render` |
| `/pieces/<id>/renditions` | `renditions/*.yml`, `assets/`, `outbox/<id>/REVIEW.html` | `renditions/*.yml` | `ce package`, `ce publish site`, `ce posted` |
| `/runs` | `data/runs/*.log` | — | any §9 command |
| `/doctor` | — | — | `ce doctor` |

**Editing.** `article.md` and `renditions/*.yml` textareas save by writing the file directly at its normal path — indistinguishable from a manual edit made in a text editor. This is deliberate: ADR-008's edit check compares `article.md`'s mtime to `piece.generated_at`, and a GUI save must satisfy it the same way a manual edit does, with no special-cased bypass.

**Mechanical validation shown live** (character counters, URL-in-body checks) reuses the exact constants `produce/renditions.py`'s own §10.6 validation reads from `config/platforms/<p>.yml` — never a second hardcoded copy of `max_chars`/`hook_chars`.

**Confirm-gated actions.** Any action that reaches outside this machine — `ce publish site` (git push to `identity.site_repo`) — requires an explicit confirmation step in the UI before the run is submitted, on top of whatever the CLI itself already checks (`--dry-run`, the edit check, OG-tag assertion). `ce posted` (recording a URL after manual posting) is not confirm-gated — it writes local data only, nothing leaves the machine.

**REVIEW.html stays authoritative.** The renditions screen's "package preview" embeds the real `outbox/<id>/REVIEW.html` an actual `ce package` run produced (an `<iframe>` over the file, or an equivalent fetch-and-inline), never a GUI-side reimplementation of §10.8's layout — one canonical review artifact, viewable from two places.

---

## §11 Prompt contracts

Every prompt file:

```markdown
---
id: article_grade
version: 3
tier: reasoning
output_schema: _schemas/grade.schema.json
inputs: [article, brand_brief, voice_samples, weights]
---

<system>
...
</system>

<user>
{{ article }}
</user>
```

**Registry:**

| id | tier | schema | Notes |
|---|---|---|---|
| `transcript_clean` | cheap | — | **Must preserve self-corrections verbatim** |
| `commit_summarize` | cheap | — | Messages/paths/stats only — never diffs |
| `brief_generate` | reasoning | `briefs` | §10.4. Highest-value prompt in the system. |
| `article_draft` | default | — | Receives raw + clean transcripts |
| `article_grade` | reasoning | `grade` | Ceiling 9.5 |
| `article_revise` | default | — | Takes `top_fixes` only |
| `claim_extract` | default | `claims` | Classifies grounded/external/opinion/unverifiable |
| `rendition_linkedin` | default | — | No links in body; separate first comment |
| `rendition_facebook` | default | — | Links OK; native image |
| `rendition_youtube` | default | — | Title ≤60, desc hook 150, chapters from 00:00 |

**Versioning:** bump `version` on any semantic change. `LLMResult.prompt_version` is recorded in `grades.json` and `ledger.jsonl`, so a quality regression is traceable to a prompt diff.

---

# PART III — DELIVERY

## §12 Work packages

Each WP is one session. **Do not start a WP until the previous one's acceptance criteria pass.**

Legend: **D** = depends on.

---

### WP-00 — Scaffold, CLI skeleton, `doctor`
**D:** none
**Build:** `pyproject.toml` (typer, pydantic, pyyaml, jinja2, httpx, pytest, ruff). `src/ce/cli.py` with all §9 subcommands registered as stubs raising `NotImplementedError`. `ce doctor` checking: python ≥3.11, `ffmpeg`, `gitleaks`, `mermaid-cli`, playwright chromium, and presence of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. Create `STATUS.md` per §0.
**Done when:** `ce --help` lists every §9 command; `ce doctor` reports each dependency ✓/✗ and exits 1 if any required one is missing.

### WP-01 — Config, models, store
**D:** WP-00
**Build:** `config.py` (Pydantic, loads `engine.yml` + platform files, expands `~`, resolves paths). `models.py` — all §5.2 entities. `store.py` — path resolution, YAML read/write, `_manifest.json` read/write with input hashing.
**Done when:** round-trip test writes and reads every entity; `ce project show` on a hand-written fixture prints correctly; invalid config produces a readable validation error naming the field.

### WP-02 — LLM gateway
**D:** WP-01
**Build:** `llm/prompts.py` (frontmatter loader, Jinja2 `StrictUndefined`), `llm/cache.py`, `llm/ledger.py`, `llm/gateway.py` per §10.1. Two throwaway prompts for testing. `ce cost`.
**Done when:** identical call twice → one ledger entry, second `cache_hit=True`; schema validation failure triggers exactly one repair then raises; budget exceeded raises `BudgetExceeded` (exit 3); `ce cost --month` prints a per-prompt breakdown.

### WP-03 — Project lifecycle
**D:** WP-01
**Build:** `ce project new|list|show|close`. Slug validation. Directory scaffolding.
**Done when:** `ce project new test-proj --repo ~/code/x` creates the full tree; duplicate slug is rejected; `--abandoned` sets status correctly.

### WP-04 — Capture & transcription
**D:** WP-02, WP-03
**Build:** `capture/audio.py` (§10.2), `capture/ingest.py`, `prompts/transcript_clean.md`. Chunking for >24MB.
**Done when:** a 90-second fixture m4a produces `raw.txt` and `clean.md`; re-running is a no-op; `clean.md` demonstrably retains a self-correction present in the fixture (golden test); `ce capture list` shows all types.

### WP-05 — Git harvest + safety gates ⚠️
**D:** WP-02, WP-03
**Build:** `gates/allowlist.py`, `gates/secrets.py`, `harvest/git.py` (§10.3), `prompts/commit_summarize.md`.
**Done when:**
- A repo outside the allowlist raises before any git command runs (assert via mock).
- **A fixture repo containing a planted fake AWS key causes exit 2 and writes `redaction-report.json`.** This test is mandatory and must not be skipped.
- Assert by code inspection *and* test that no diff content is ever passed to `gateway.complete`.
- Significance scoring matches a golden fixture of 30 commits.
- `lessons-only` propagates into prompt vars.

### WP-06 — Index & dedupe
**D:** WP-02
**Build:** `index.py` (SQLite schema, embeddings as numpy per ADR-003), `gates/dedupe.py`, `ce index rebuild`.
**Done when:** `index rebuild` reconstructs entirely from `data/` after deleting `index.db`; two near-identical texts score >0.9, unrelated <0.5; dedupe blocks above threshold and names the colliding piece.

### WP-07 — External research
**D:** WP-02
**Build:** `harvest/research.py` — search + fetch, dedupe by domain, extract to `research.json` with `{url, title, fetched_at, summary, stance}`. Cap at `max_sources`.
**Done when:** returns ≥3 usable sources for a fixture topic; fetch failures degrade gracefully rather than aborting.

### WP-08 — Inventory generator (MATCH) ⭐
**D:** WP-04, WP-05, WP-06, WP-07
**Build:** `harvest/inventory.py` (§10.4), `prompts/brief_generate.md`, `_schemas/briefs.schema.json`, `ce harvest`.
**Done when:**
- Fixture project yields 6–8 briefs covering ≥4 archetypes.
- **Every evidence citation resolves to a real capture ID or commit SHA** — unresolvable citations trigger one retry, then fail the run.
- Every brief has non-empty `weakest_point`.
- `weak` briefs are marked `dropped` and `ce brief select` refuses them.
- `inventory.md` is readable and ranked.

> **MVP milestone.** After WP-08 the system delivers real value: run it on a finished project and get briefs. Consider using it manually for a cycle before continuing.

### WP-09 — Writer & grader
**D:** WP-08
**Build:** `produce/writer.py` (§10.5), prompts `article_draft` / `article_grade` / `article_revise`, `grade.schema.json`, `ce brief select`, `ce produce`.
**Done when:** loop terminates on `>=min_grade` or `max_attempts`; `grades.json` records every attempt with prompt versions; grade ≥2 is a strict improvement over attempt 1 on the fixture; `article.md` written; `piece.generated_at` set; next-step instructions printed.

### WP-10 — Claim verification
**D:** WP-09, WP-07
**Build:** `gates/claims.py` (§6.4), `prompts/claim_extract.md`, `claims.schema.json`, `ce verify`.
**Done when:** a fixture article with one planted unverifiable claim exits 2 naming that claim; `grounded` claims not mapping to a real capture/commit fail; `verification.json` written.

### WP-11 — Asset pipeline
**D:** WP-09
**Build:** `assets/*` (§10.7) + templates + `config/brand.css`. `ce assets`.
**Done when:** Mermaid source renders to PNG at correct dims; code card renders at 2× and is legible at 50%; thumbnail is 1280×720; `--only diagram` runs just that; missing `mermaid-cli` produces a clear error, not a stack trace.

### WP-12 — Renditions
**D:** WP-09
**Build:** `produce/renditions.py` (§10.6), three rendition prompts, three platform configs.
**Done when:** **every mechanical validation in §10.6 has a passing test with a deliberately-violating fixture** — over-length, URL in LinkedIn body, markdown surviving into LinkedIn, unicode styling, YouTube title >60, chapters not starting at 00:00. One regeneration attempt on violation, then exit 1.

### WP-13 — Packager & REVIEW.html
**D:** WP-11, WP-12
**Build:** `package/builder.py`, `package/review_html.py` (§10.8), `ce package`.
**Done when:** `outbox/<piece-id>/` matches the v3 §4 layout; `REVIEW.html` opens from `file://` with no network and no console errors; copy buttons work; counters turn red past the limit; **the screenshot review checklist is present and lists every image**; Sharing Debugger link is pre-filled; Generate-command button emits valid `ce posted` invocations.

### WP-14 — Site publish
**D:** WP-10
**Build:** `publish/site.py` (§10.9), `ce publish site`.
**Done when:** `--dry-run` prints the frontmatter and file plan without writing; edit check blocks an unedited article with exit 4; **OG tag assertion fails loudly if tags are missing**; canonical URL polling times out cleanly at 120s.

### WP-15 — Post-back & metrics
**D:** WP-13, WP-14
**Build:** `ce posted`, `metrics/umami.py`, `metrics/youtube.py`, `ce metrics pull`, `performance.md` generation.
**Done when:** `ce posted` appends correctly to `posted.yml`; UTM-attributed clicks resolve per platform; LinkedIn is correctly recorded as manual-entry-only; re-running `metrics pull` is idempotent per snapshot date.

### WP-16 — Trend sweep
**D:** WP-02
**Build:** `sweep/hn.py` (Algolia, no auth), `sweep/rss.py`, recurrence scoring across the last 4 sweeps, `ce sweep`.
**Done when:** writes `sweeps/<date>.md` with Recurring / Emerging / Fading sections; a topic present in 3 of 4 prior sweeps ranks above a same-day spike; network failure on one source doesn't abort the others.

---

**GUI work packages (ADR-009).** Added 2026-07-28, after all 16 original WPs closed — see STATUS.md deviations for why the §15 "after 10 published pieces" trigger was overridden rather than waited on. Same one-WP-per-session discipline; each Build/Done-when below follows the same rigor as WP-00–16.

### WP-17 — GUI scaffold, process runner, doctor screen
**D:** WP-16
**Build:** `[project.optional-dependencies].gui` (`fastapi`, `uvicorn`). `src/ce/gui/app.py`, `runner.py` (§10.10). `ce gui [--port 8420]` — starts the server bound to `127.0.0.1` and best-effort opens the default browser. Base Jinja2 layout + vendored `static/htmx.min.js` (no CDN, per ADR-006's "no network" spirit applied here too). `/doctor` screen: triggers a real `ce doctor` run through `runner.py` and streams its output.
**Done when:** `ce gui` serves on `127.0.0.1` only; `/doctor` streams real `ce doctor` output line-by-line and shows the correct exit code; reloading `/doctor` mid-run resumes from the tailed log rather than blanking; `ce --help` still runs unmodified (repo-wide invariant); stopping the GUI process leaves no orphaned `ce doctor` child process.

### WP-18 — Project dashboard
**D:** WP-17
**Build:** `gui/routes/dashboard.py` — `/` lists every project (`store.py`'s existing read helpers over `data/projects/*/project.yml`) with status; `/projects/<slug>` rolls up capture/harvest/brief/piece counts.
**Done when:** the dashboard lists every project on disk with the correct status; a fixture project's detail page shows accurate counts at every stage; a project with no harvest yet renders a clear "not harvested" state, not an error or a blank section.

### WP-19 — Pipeline run/log console
**D:** WP-17
**Build:** `gui/routes/runs.py` — `/runs`: pick any §9 stage command for a project/piece id, submit, watch its real subprocess output stream live via `runner.py`. Actions reaching outside this machine (`ce publish site`, anything that ends in `git push`) require an explicit confirm step before submission.
**Done when:** triggering `ce doctor` from `/runs` shows live output and the real exit code; a gate-blocked run (exit code 2) is visibly distinguished from success, not shown as a silent pass; `publish site` cannot be submitted without the confirm step; closing the browser tab mid-run does not kill the subprocess, and reopening `/runs/<run-id>` replays the same log (§10.10's tail-the-log-file design, not direct stdout piping).

### WP-20 — Brief review & selection
**D:** WP-18, WP-19
**Build:** `gui/routes/briefs.py` — `/projects/<slug>/briefs`: list from `briefs.yml`/`inventory.md` with archetype, recurrence/demand, evidence, dedupe score, risk flags; "Select" shells to `ce brief select <brief-id>` via WP-19's runner and redirects to the resulting piece.
**Done when:** a `dropped`/weak brief's Select control is disabled in the UI itself, not just rejected after a click (matches WP-08's `assert_selectable`); selecting a real candidate creates a `Piece` and lands on WP-21's review page; a dedupe collision is surfaced with the colliding piece named, matching what `ce brief select` itself reports on the CLI.

### WP-21 — Article & grade review
**D:** WP-19
**Build:** `gui/routes/pieces.py` — `/pieces/<id>`: `article.md` in an editable textarea saving straight back to that file; full `grades.json` attempt history with per-dimension scores and `top_fixes`; `verification.json` results once run; buttons to trigger `verify`/`assets`/`render` via WP-19.
**Done when:** editing and saving `article.md` in the GUI bumps its mtime past `piece.generated_at` exactly like a manual edit — `ce verify`'s ADR-008 edit check passes afterward with zero special-casing; grade history renders every attempt in order; a not-yet-verified piece clearly states that, rather than showing a blank or misleading verification section.

### WP-22 — Rendition editing & package preview
**D:** WP-19, WP-21
**Build:** `gui/routes/renditions.py` — `/pieces/<id>/renditions`: per-platform `renditions/*.yml` view with editable body/first-comment/title/chapters textareas saving back to the same file; live character counters reading the same `config/platforms/<p>.yml` numbers §10.6's mechanical validation uses; asset previews; an embedded view of the real `outbox/<id>/REVIEW.html` once `ce package` has run; confirm-gated `publish site`/`ce posted` triggers.
**Done when:** the character counter turns red past the platform's actual `max_chars` (same constant `renditions.py` validates against, not a second hardcoded copy); saving an edited rendition writes to the file the CLI reads, and a subsequent `ce package` run reflects the edit; the package preview shows the literal `REVIEW.html` `ce package` produced, not a GUI-side reimplementation of §10.8.

---

### 12.1 Dependency graph

```
WP-00 ─┬─ WP-01 ─┬─ WP-02 ─┬─ WP-04 ─┐
       │         │         ├─ WP-06 ─┤
       │         └─ WP-03 ─┴─ WP-05 ─┼─ WP-08 ⭐ ── WP-09 ─┬─ WP-10 ── WP-14 ─┐
       │                   WP-07 ────┘                     ├─ WP-11 ─┬─ WP-13 ┴─ WP-15
       │                                                   └─ WP-12 ─┘
       └────────────────────────────────── WP-16 (independent after WP-02)

All 16 above ── WP-17 ─┬─ WP-18 ─────────┐
                       └─ WP-19 ─┬───────┼─ WP-20
                                 └─ WP-21 ── WP-22
```

**Critical path (original 16):** 00 → 01 → 02 → 05 → 08 → 09 → 12 → 13. Everything else can slip.

**Minimum useful system:** WP-00 through WP-09, publishing by hand. WP-13 is the next-biggest quality-of-life win.

**GUI critical path:** 17 → 19 → 21 → 22 (the edit/review/package loop). WP-18 and WP-20 (dashboard, brief selection) can slip behind it without blocking the review workflow.

---

## §13 Testing strategy

**Framework:** pytest. Target ~70% coverage on `gates/`, `store.py`, and rendition validation; lower elsewhere is fine.

**LLM determinism:** tests run with a pre-primed `data/.llm-cache/` committed under `tests/fixtures/llm-cache/`. Zero API calls in CI, deterministic output. Refresh deliberately with `pytest --refresh-llm-cache` when a prompt version bumps.

**Fixture project** (`tests/fixtures/sample-project/`): a real git repo with ~30 commits including a genuine revert, two 90-second audio files (one containing an audible self-correction, for the WP-04 golden test), three screenshots, and a populated `friction.md`.

**Mandatory security tests** — these must never be marked skip or xfail:
1. Repo outside allowlist → raises before any git subprocess (assert via mock that `subprocess.run` was never called).
2. Planted fake AWS key in a fixture repo → exit 2 + `redaction-report.json`.
3. No code path passes diff content to `gateway.complete` (mock-based assertion on call args).
4. `lessons-only` repo → prompt vars contain no file paths or repo name.

**Golden files** (`tests/golden/`): rendition outputs, `inventory.md`, significance scoring. Update deliberately, review the diff.

---

## §14 Operational concerns

**Secrets:** API keys via environment only. Never in `engine.yml`. `.env` is gitignored; `ce doctor` verifies presence without printing values.

**Backup:** `data/` is committed to git except `.llm-cache/`, `index.db`, and media (`*.m4a`, `*.mp4`, `*.mov`). Media goes to a local backup target — it's large, regenerable-never, and doesn't belong in git. Decide a location in WP-03 and record it in `STATUS.md`.

**Cost monitoring:** `ce cost` after every produce run. Investigate any single run above $2. The most likely runaway is a revision loop on a long article.

**Failure recovery:** every stage is resumable via `_manifest.json`. If a run dies mid-stage, re-run it; completed sub-steps are skipped. `--force` re-does a stage. `--force` cannot bypass G1 or G2 (ADR-005) — enforced in code.

**Upgrades:** model IDs live in `engine.yml`. Changing a model invalidates cache entries naturally (model is in the cache key). Bump prompt versions when adapting prompts to a new model, so `grades.json` history stays interpretable.

**Logging:** structured to stderr; `--verbose` enables debug. Every run writes `data/runs/<ts>-<command>.log`.

---

## §15 Out of scope

Explicitly not building. Revisit only if the trigger fires.

| Item | Trigger to reconsider |
|---|---|
| API publishing to social platforms | Never, under current product decisions |
| n8n / scheduler / VPS | ≥3 pieces/week, or wanting unattended morning metrics |
| Vector database | Corpus >10,000 pieces (ADR-003) |
| Postgres | Multi-user, or concurrent runs |
| ~~Web UI~~ | Superseded 2026-07-28 — built as WP-17–WP-22 (ADR-009, §10.10) ahead of the original "after 10 published pieces" trigger, by explicit operator decision. See STATUS.md deviations. |
| Multi-tenant / client work | Different product |
| AI avatar video | Screen capture proves inadequate — unlikely (v3 §4) |
| Automated screenshot secret-scanning | If a viable OCR+entropy approach emerges; currently manual (§6.2) |

---

## Appendix A — First-session checklist

```bash
mkdir content-engine && cd content-engine && git init
# WP-00 starts here.
# 1. Read §0, §2, §3, §4 of this document.
# 2. Create STATUS.md from the §0 template.
# 3. Implement WP-00 per §12.
# 4. Run acceptance criteria. Update STATUS.md. Commit.
```

**Before WP-04, install:** `ffmpeg`, `gitleaks`, `@mermaid-js/mermaid-cli`, `playwright install chromium`.

**Write `config/brand-brief.md` by hand before WP-08.** It is the highest-leverage file in the repository and no amount of engineering compensates for a vague one.
