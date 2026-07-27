# Ingest Design — Idea Sweep + Grounding

**Companion to `DIY-Content-Engine-v2.md`.** Covers the two layers upstream of the writer: where ideas come from (trending web search) and what grounds them (audio + git repo).

---

## 1. The tension, and how to resolve it

You've specified two inputs that pull in opposite directions:

- **Trending search** says: *write about what people are talking about right now.*
- **Audio + git repo** says: *write about what you actually did.*

Naively combining them produces the worst of both: chasing topics you have no standing to discuss, or publishing work logs nobody searched for.

**The resolution: trending is a framing signal, not a topic source.**

You never let the trend pick the subject. Your work picks the subject; the trend picks the angle, the vocabulary, and the timing. The pipeline's job is to find where those two overlap:

```
   what I actually did          what people are asking
   (git + audio, last 7d)       (HN, RSS, search, last 14d)
            │                             │
            └──────────┬──────────────────┘
                       ▼
                  MATCH STEP
        "you spent Tuesday fighting X.
         14 people asked about X this week.
         here's the piece, and here's your evidence."
                       ▼
              3-5 candidate BRIEFS
              (not drafts — briefs)
                       ▼
                 YOU PICK ONE
```

This also solves the §2 problem from v2 outright. **The grounding gate is now satisfied automatically** — every candidate arrives with evidence already attached, because it was generated *from* evidence. You've removed the main failure mode of "idea first, AI drafts everything" by changing where ideas come from. That's a substantially better position than the previous design.

---

## 2. Layer A — Idea sweep (trending)

### Set expectations honestly first

**At one piece per week, you cannot catch trends.** By the time a topic is visibly trending, has been aggregated, and you've written 1,200 words about it, the wave has passed and you're competing with fifty faster publishers. Chasing trends is a daily-cadence game.

What actually works at weekly cadence is **persistent demand** — questions that keep getting asked, month after month, that you happen to have real experience with. Less exciting, dramatically more durable, and it compounds in search where trend pieces don't.

So configure the sweep to surface *recurring* questions, not spikes. Practically: weight a topic that appeared in three of the last four weekly sweeps far above one that exploded yesterday.

### Source ranking

| Source | Access | Cost | Verdict |
|---|---|---|---|
| **Hacker News (Algolia API)** | No auth, no key | **$0** | 🟢 **Best single source for technical topics.** Full-text search, date filtering, points/comment counts as velocity signal. Start here. |
| **RSS of 15–30 real blogs** | None | **$0** | 🟢 Most underrated. Signal-to-noise far better than any social feed. Curate by hand once, benefit for years. |
| **GitHub search API** | Token | **$0** | 🟢 `created:>DATE sort:stars` approximates GitHub Trending, which has no official API. Good for "what tooling is people adopting." |
| **Web search (your existing tooling)** | — | ~$0 | 🟡 Useful for *validating* a topic, weak for *discovering* one. See warning below. |
| **Lobste.rs, Dev.to** | Public APIs/RSS | $0 | 🟡 Narrow but clean |
| **Reddit** | ⚠️ See below | $0 non-commercial | 🔴 Not worth it now |
| **Google Trends** | Unofficial (`pytrends`) | $0 | 🔴 Breaks constantly, no stability guarantee. Don't build on it. |

### Two warnings

**⚠️ Reddit has effectively closed.** The free tier is non-commercial only and now requires pre-approval under the Responsible Builder Policy, with OAuth approval running 2–4 weeks. As of May 2026 Reddit began returning 403s on the unauthenticated JSON endpoints that most open-source tools quietly relied on — a lot of tooling went dark overnight. Commercial access starts around $0.24/1,000 calls. Skip it unless a specific subreddit is genuinely central to your niche, and if so, apply early.

**⚠️ Don't web-search for "trending topics in X."** Those results are now dominated by SEO farms and AI-generated listicles — you'd be grounding your content in other people's ungrounded content, which is exactly the doom loop to avoid. Point search at **primary sources**: specific communities, changelogs, release notes, conference schedules, and the actual blogs of people doing the work. Use search to *check* whether a topic has demand, not to *find* topics.

### The best source isn't on that list

**Your own inbound.** Comments on your posts, DMs, questions in calls, things people email you. At solo scale this beats every automated trend source combined, because it's demand you can verify is real and directed at *you specifically*.

There's no API for this. Keep an `inbound.md` file and paste questions into it as they arrive, with a date. Ten seconds each. After two months it will be the highest-value file in the repo.

### Output format

The sweep writes `sweep/2026-07-26.md` — never drafts, just observations:

```markdown
## Recurring (3+ of last 4 sweeps)  ← prioritize these
- Cost control in agentic AI pipelines — HN 4 threads, 2 blogs, 1 inbound question
- "Do I need a vector DB" — HN, 2 blogs, recurring since June

## Emerging (new, high velocity)
- <topic> — HN 340pts, 2 days old

## Fading
- <topic> — dropped from previous sweeps
```

---

## 3. Layer B — Audio grounding

Voice memo → transcript → evidence. This is your highest-value input and the thing no competitor can replicate.

### Pipeline

```
audio file (.m4a/.wav)  →  ffmpeg (trim silence, normalize)
                        →  transcription API
                        →  raw.txt  +  cleaned.md  +  claims.json
                        →  grounding/2026-07-26-topic/
```

### Tooling and cost

**Use the API, not local Whisper.** At a few hours a month the arithmetic isn't close:

| Option | Cost | Notes |
|---|---|---|
| `gpt-4o-mini-transcribe` | **$0.003/min** | 2 hrs/month = **$0.36**. Start here. |
| `whisper-1` / `gpt-4o-transcribe` | $0.006/min | 2 hrs/month = $0.72 |
| Self-hosted `faster-whisper` | "$0" + GPU + ops | Identical accuracy to Whisper (same weights, CTranslate2 runtime), 4–8× faster. Only rational above ~2,400 hrs/month. |

Self-hosting is a hobby decision at your volume, not an economic one.

### Gotchas

**⚠️ Whisper hallucinates on silence.** Long silent or noisy stretches produce confident fabrications — classically "Thanks for watching!" or repeated phrases. Always pre-process:
```bash
ffmpeg -i in.m4a -af "silenceremove=stop_periods=-1:stop_duration=1.5:stop_threshold=-40dB,loudnorm" out.wav
```

**⚠️ Technical jargon and proper nouns get mangled.** Pass a vocabulary hint via the `prompt` parameter — your product names, stack, frequently-used acronyms. Costs nothing, dramatically reduces cleanup.

**⚠️ Don't over-clean the transcript.** This is the important one. The instinct is to have an LLM tidy the rambling into clean prose — and that step is exactly where your voice dies. The tangents, the self-corrections, the *"actually, no, the real problem was…"* — that's the differentiated thinking. Keep both files. The writer should read `raw.txt` for voice and `cleaned.md` for structure.

**Recording habits matter more than model choice:**
- One idea per file. Don't record a 40-minute brain dump; record six 5-minute ones.
- State the thesis in the first 15 seconds, then argue with yourself.
- Record right after something goes wrong. That's when you know the most and remember the details.

---

## 4. Layer C — Git repo grounding

Commits are a factual record of what you did, when, and what broke. Excellent raw material — and the layer with the only genuinely dangerous failure mode in this whole system.

### ⚠️ Secret leakage — read this before writing any code

**Diffs contain credentials.** `.env` files, API keys, tokens, internal hostnames, staging URLs, customer names in test fixtures, S3 buckets. If you pipe `git diff` into an LLM and then into a public article, you will eventually publish something you can't unpublish.

**Mandatory, non-negotiable, before anything reaches a model:**

1. **Scan with `gitleaks` or `trufflehog`.** Hard-fail the run on any hit — don't warn, don't continue.
2. **Never send raw diffs to the LLM.** Send commit messages, file paths, and line-count stats. If you need code context, hand-select the snippet.
3. **Never publish a diff verbatim.** Extract the *lesson*, not the code.
4. **Deny-list by path**: `.env*`, `*.pem`, `*.key`, `secrets/`, `config/credentials*`, fixtures, seed data.

### ⚠️ Confidentiality — default deny

Client work, employer work, and anything under NDA must never enter the pipeline. Use an explicit **allowlist**, not a blocklist:

```yaml
# grounding/repos.yml
allowed:
  - path: ~/code/my-side-project
    visibility: public
    publishable: full
  - path: ~/code/personal-tooling
    visibility: private
    publishable: lessons-only   # concepts yes, code/specifics no
# everything not listed here is invisible to the pipeline
```

`lessons-only` is the useful middle setting: the pipeline may reason about what you learned without quoting code, naming the project, or reproducing architecture.

### What to extract

Weekly sweep across allowlisted repos:

```bash
git log --since="7 days ago" --numstat --pretty=format:'%H|%ad|%s'
```

Then **filter for significance**, because 80% of commits are noise:

| Signal | Weight | Why |
|---|---|---|
| **Reverts / rewrites of recent code** | ⭐ Highest | You changed your mind. That's the most interesting content you will ever have. |
| Commit messages over ~100 chars | High | You explained yourself because it was non-obvious |
| Large deletions | High | "What I removed and why" outperforms "what I added" |
| A fix landing days after the feature | High | There's a war story attached |
| New dependency added or removed | Medium | Tooling decisions are searchable |
| `fix typo`, `bump`, formatting | Zero | Drop |

Also pull PR descriptions and closed issues via the GitHub API (free), and any ADRs or `docs/` changes — those are already written thinking.

### The content that actually works

Not *"this week I added feature X."* Nobody cares.

What works: **"I built X the obvious way, it failed for this specific reason, here's what I do instead."** Your git history is unusually good at surfacing these, because the revert commits mark them precisely. Weight for them.

---

## 5. The MATCH step

The core of the design. Runs weekly, reads all three inputs, outputs **briefs — never drafts**.

**Input:** `sweep/<date>.md`, `grounding/audio/*`, `grounding/git/<date>.md`, `inbound.md`, `brand-brief.md`, `posted.yml` (for dedupe)

**Output:** `briefs/<date>.md` — 3–5 candidates, each with:

```markdown
### Brief 2 — "The vector DB you probably don't need"

**Demand signal:** recurring 3/4 sweeps · 2 HN threads (410 pts combined) ·
                   1 inbound question from @someone, Jul 14
**Your evidence:**
  - git: removed pgvector dep, 2026-07-22, -340 lines, commit msg 180 chars
  - audio: voice-2026-07-22.m4a @ 2:10 — "the embedding lookup was never
    the bottleneck, it was the chunking"
**Angle:** counter-position. Most coverage assumes you need one.
**Grounding strength:** 🟢 STRONG (first-hand, reversed decision, specific numbers)
**Dedupe:** 0.31 max similarity vs last 90 days — clear
**Risk flags:** none — public repo, no secrets in referenced commits
**Weakest point:** n=1. Say so explicitly in the piece.
```

### Design rules

- **Briefs, not drafts.** You choosing between five briefs takes two minutes and is where your judgment enters the system. Auto-drafting all five wastes tokens and removes the only step that requires you.
- **Grounding strength is a visible, blocking field.** Anything scoring 🔴 WEAK cannot proceed to drafting. This is the v2 §2 gate, now automatic.
- **Always surface the weakest point.** Forcing the brief to name its own flaw is the cheapest possible defense against confident AI slop, and it usually improves the finished piece — the honest caveat is often the most credible line in it.
- **Dedupe at brief stage, not draft stage.** Cheaper, and stops you rediscovering the same idea monthly.

---

## 6. Weekly operating rhythm

| When | What | Who | Time |
|---|---|---|---|
| Continuously | Voice memo after anything notable breaks or clicks | You | 5 min each |
| Continuously | Paste questions into `inbound.md` | You | 10 sec each |
| Mon AM | Trend sweep + git sweep + transcription run | Automated | 0 |
| Mon AM | MATCH → 3–5 briefs | Automated | 0 |
| Mon | **Pick one brief.** Add 3 bullets of your own take | **You** | **10 min** |
| Mon | Draft → grade → revise loop → article | Automated | 0 |
| Tue | Edit the article. Do not skip this. | **You** | **30 min** |
| Tue | Publish to site; generate `outbox/` package | Automated | 0 |
| Tue | Post to LinkedIn + Facebook from `REVIEW.html` | **You** | **10 min** |
| Fri | Metrics pull → `performance.md` | Automated | 0 |

**~50 minutes of your time per published piece.** That's the actual product.

---

## 7. Updated costs

| Item | Cost |
|---|---|
| Transcription (`gpt-4o-mini-transcribe`, ~2 hrs/mo) | **$0.36** |
| HN Algolia API | $0 |
| RSS | $0 |
| GitHub API | $0 |
| `gitleaks` | $0 |
| Web search (existing tooling) | ~$0 |
| **Added by this layer** | **< $1/mo** |

Total for the whole system stays at **$5–15/month**. Audio and git grounding are essentially free — which is a good deal for the two inputs that make the content worth reading.

---

## 8. Gotcha summary

| # | Gotcha | Severity |
|---|---|---|
| 1 | **Secrets in diffs reaching a published article** | 🔴 Critical — `gitleaks` hard-fail, never send raw diffs |
| 2 | **Client/NDA repos entering the pipeline** | 🔴 Critical — allowlist, default deny |
| 3 | Chasing trends at weekly cadence — always late | 🟠 Strategic — optimize for recurrence, not spikes |
| 4 | Web-searching "trending topics" returns AI slop | 🟠 Grounding your content in ungrounded content |
| 5 | Whisper hallucinating on silence | 🟡 Trim + normalize first |
| 6 | Over-cleaning transcripts kills your voice | 🟡 Keep `raw.txt`; writer reads both |
| 7 | Reddit API now gated (pre-approval, 403s on unauth) | 🟡 Skip, or apply 4 weeks early |
| 8 | `pytrends` breaking without warning | 🟡 Don't build on unofficial APIs |
| 9 | Git noise — 80% of commits are worthless | 🟡 Significance filter, weight reverts highest |
| 10 | Jargon mangled in transcription | 🟢 Vocabulary hint in `prompt` param |

---

## 9. Build order for these layers

Slot into v2's plan between Phase 1 and Phase 2:

1. **`inbound.md` + a voice-memo habit.** Zero code. Start today — the pipeline is worthless without input, and this is the input that takes weeks to accumulate.
2. **Transcription script.** ffmpeg → API → `raw.txt` + `cleaned.md`. ~30 lines. Immediately useful on its own.
3. **Git sweep + `gitleaks` + `repos.yml` allowlist.** Build the safety gate in the same commit as the extractor — never as a follow-up. ~80 lines.
4. **HN Algolia + RSS sweep.** ~60 lines. Add other sources only if these prove insufficient.
5. **MATCH step.** One well-constructed LLM call over the above. This is where the thinking goes; budget real time on the prompt.

Steps 1–3 are worth having even if you never build the writer. A searchable archive of your own voice memos and a filtered log of decisions you reversed is a genuinely valuable personal asset independent of publishing anything.

---

## Sources

- [Reddit API pricing, access and 2026 changes](https://www.socialcrawl.dev/blog/reddit-data-api-2026) · [free tier + Responsible Builder Policy](https://prowlo.com/blog/reddit-api-pricing)
- [OpenAI transcription pricing, July 2026](https://costgoat.com/pricing/openai-transcription) · [Whisper API vs self-host economics](https://brasstranscripts.com/blog/openai-whisper-api-pricing-2025-self-hosted-vs-managed)
- [faster-whisper vs Whisper — identical accuracy, CTranslate2 speedup](https://www.localalternative.io/compare/whisper-vs-faster-whisper)
- [Google spam policies — scaled content abuse, 2026](https://www.jsonhouse.com/posts/google-ai-content-penalties-2026/)
