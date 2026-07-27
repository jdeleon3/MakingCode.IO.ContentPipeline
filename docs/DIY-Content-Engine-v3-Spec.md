# Content Engine v3 — Project-Triggered Spec

**Your model:** explore a project → build it in git → record audio reflection → AI assembles content for every platform, with assets, for your review.

**Verdict: this is the right architecture,** and it's better than what I proposed in v2/v2.1. It also reverses two of my earlier recommendations. Supersedes the pipeline sections of v2 and v2.1; the platform gotchas in v2 §5 still stand.

---

## 1. What your model gets right

Worth being explicit, because these are the things most content systems get wrong:

**Grounding is structural, not enforced.** In v2 I designed a "grounding gate" that would refuse to draft without evidence — a discipline you'd have to maintain against the temptation to skip it. In your model, grounding is unavoidable: the content is *downstream of work that actually happened*. There's nothing to enforce. That's a much more robust design and it makes the v2 §2 risk mostly disappear.

**It's a proven format.** Build-in-public / learning-in-public retrospectives are one of the few content shapes that reliably works for technical solo operators, because it's the one thing you have that nobody else does: your specific experience of a specific thing going wrong.

**The trigger is real work, not a calendar.** Calendar-triggered content asks "what should I write this week?" — a question with no good answer. Yours asks "what did I just learn?", which always has one.

**"Good, bad, lessons learned" is exactly the right audio prompt.** The "bad" section is where the value is. Most technical content documents success; almost none documents the eight hours of confusion, which is what readers are actually searching for.

---

## 2. The one thing missing from your four steps

**Step 4 assumes one project produces one round of content. It should produce six to eight pieces.**

This is the highest-leverage change to your model, and it fixes a problem you'll hit around week three.

Projects don't take a week. They take two days or three weeks, unpredictably. If publishing is coupled to project completion, your output is lumpy — a burst, then three weeks of silence, then a burst. Audiences and algorithms both punish that, and worse, the silence is demoralizing enough that most people quit during it.

**Decouple them.** One substantial project is a *content inventory* you draw down from over the following weeks while building the next one:

| # | Piece | Source material | Best platform | Note |
|---|---|---|---|---|
| 1 | **Why I'm exploring X** | Selection research, first commits | LinkedIn, site | Publish at project *start*. Free content, creates anticipation. |
| 2 | **The build walkthrough** | Git history + README | Site (SEO), YouTube | Your main searchable asset |
| 3 | **What went wrong** | Audio "bad" section | LinkedIn, site | Reliably the highest-engagement piece |
| 4 | **I was wrong about X** | Revert commits + audio | LinkedIn | Highest credibility. Rare and valuable. |
| 5 | **\<Tool\> after two weeks of real use** | Dependency changes + audio | Site, LinkedIn | High persistent search demand |
| 6 | **The specific gotcha** | One commit + one audio moment | Site | Narrow, technical, ranks for years |
| 7 | **Would I do it again** | Audio "lessons" section | LinkedIn, Facebook | Best discussion-starter |
| 8 | **Video walkthrough** | Screen capture + your audio | YouTube | See §4 |

Adapted across four platforms, that's **4–6 weeks of publishing from one project.** Your build cadence and your publishing cadence become independent, which is the thing that makes this sustainable.

**Implementation:** the harvest step outputs a `content-inventory.md` with all candidates ranked and a suggested publish order. You pick one per week. You are never staring at an empty queue, and you are never rushing a project to feed the machine.

---

## 3. Where trend search actually belongs

Not in content generation. **In step 1 — choosing what to explore.**

This is the strongest version of your model. If the trend sweep informs *project selection*, then everything downstream is automatically both grounded (you built it) and demand-matched (people are asking about it). You've solved the trending-vs-grounded tension by moving the decision upstream, before any content exists.

```
TREND SWEEP  →  candidate projects, ranked by:
                  demand signal  ×  your genuine interest  ×  feasibility
                                       ↓
                              YOU PICK ONE
                                       ↓
                  everything after this is grounded by construction
```

**Project selection is now your highest-leverage decision.** A boring project produces boring content and no amount of downstream AI fixes that. Spend real time here — it's the one step worth deliberating over.

Rank candidates on:

- **Demand** — recurring in sweeps, not spiking. HN threads, RSS, your `inbound.md`.
- **Contestedness** — topics where smart people publicly disagree are worth far more than settled ones. Consensus topics have nothing to say.
- **Your actual interest** — you have to survive two weeks of it. Interest beats demand when they conflict; a project you abandon produces nothing.
- **Failure surface** — counterintuitively, *pick things likely to go wrong*. A project that works first try is a bad content project. Friction is the raw material.
- **Feasibility** — can you get to something demonstrable in your available time?

---

## 4. Reversal #1 — build YouTube now, not later

In v2 I said defer YouTube, because "AI drafts everything" doesn't extend to long-form video and the alternatives cost $99/mo (HeyGen Pro) or produce low-retention slideshows.

**Your model invalidates that.** You have two things that change the math completely:

1. **A working project to show on screen.** Screen capture is free, native to the format, and what the audience actually wants to see.
2. **Audio you're already recording.** That's your narration. It exists as a byproduct of step 3.

Screen recording + your real voice is not the cheap fallback — it's **the highest-quality option available**, and it costs nothing. AI avatars would be a downgrade. Faceless slideshow video would be a large downgrade.

**Stack:** OBS Studio (free) for capture · your existing audio as narration · ffmpeg for assembly · Mermaid or Excalidraw for diagram cutaways. Total: **$0.**

I looked at the code-aware auto-video tools that read a repo and generate a walkthrough (RepoClip and similar). They're early, paid, and produce generic output. Not worth it when you're already recording the audio and can capture the screen in one take.

**Practical notes:**
- Capture as you build, not after. Re-staging a demo of finished work is tedious and looks it.
- 1080p is fine. 4K is a waste of upload time and disk.
- Bump your terminal and editor font size before recording. The single most common mistake in dev screencasts is unreadable text on mobile.
- Verify your YouTube channel now (2 minutes, needs a phone number) — custom thumbnails require it.

---

## 5. Reversal #2 — most assets should not be AI-generated

You asked for images, thumbnails, and video. For *technical* content, generated imagery is usually a downgrade — it reads as decorative filler, and readers of technical posts are unusually allergic to it.

What you already have is better:

| Asset | Best source | Cost | Why |
|---|---|---|---|
| **Article hero** | Annotated screenshot of the real thing | $0 | Concrete beats abstract. A terminal showing the actual error outperforms any generated image. |
| **Architecture diagram** | **Mermaid** → PNG (or Excalidraw) | $0 | Version-controlled, diffable, looks technical and credible. Mermaid lives in the repo as text. |
| **Code snippets** | HTML template → Playwright → PNG | $0 | Carbon-style cards. Templated once, free forever. Great LinkedIn carousels. |
| **Before/after** | Real diff, rendered | $0 | The most persuasive visual in technical content |
| **Screenshots** | Capture as you build | $0 | ⚠️ **Redact before publishing** — see §7 |
| **YouTube thumbnail** | Your face + 3–4 words + one real screenshot | ~$0 | Faces outperform. Generated backgrounds are fine as a layer. |
| **Quote cards** | Pull quotes from your audio transcript | $0 | Your own words, templated |

**Generated imagery earns its place in exactly one spot:** thumbnail backgrounds and the occasional conceptual header where no real artifact exists. Budget maybe $1–3/month. Everything else is Playwright and Mermaid, which is free and better.

Net effect: **this build is now nearly free.** The expensive line item in every previous version was AI video, and screen capture replaces it at zero cost with a better result.

---

## 6. Reversal-adjacent — record audio *during*, not after

Your step 3 says you record after the project. Move most of it inside step 2.

**Post-hoc reflection is sanitized.** Once something works, you genuinely cannot reconstruct what was confusing about it — the knowledge reorganizes itself and the confusion becomes invisible. This is the curse of knowledge, it's automatic, and willpower doesn't fix it.

The specific detail that makes your content useful — *the error message that sent you the wrong direction for four hours, the doc paragraph you misread, the assumption you didn't know you had* — is only available while you're still inside the problem.

**Do this:**

- **During (60–90 seconds, at the moment):** hit record when you're stuck, frustrated, or just surprised. Say what you expected, what happened, what you're about to try. Don't edit. Don't be articulate.
- **After (10–15 minutes, structured):** the good/bad/lessons retrospective you already planned. This gives narrative and framing.

The in-the-moment clips are where the differentiated content is. The retrospective is the connective tissue. You need both, and only the first one is time-sensitive.

Lowest-friction capture: phone voice memo, or a bound hotkey to a recording script. If it takes more than two seconds to start, you won't do it when you're annoyed — which is exactly when it matters.

Pair it with a `friction.md` in the repo: one line whenever something surprises you, with a timestamp. Ten seconds each, and it gives the harvest step an index into the audio.

---

## 7. Risks specific to this model

**⚠️ Secrets and screenshots.** From v2.1, but now broader. Screenshots leak more than diffs do: terminal scrollback with keys in it, browser tabs, notification popups, `.env` open in a split pane, real customer data in a local database. `gitleaks` catches the git side; nothing catches the screenshot side but your eyes. Review every image at full size before publishing, and use a clean recording profile — separate browser profile, notifications off, dummy data.

**⚠️ The n=1 problem.** One project is an anecdote, not evidence. "X is slow" is unsupportable from a single use; "X was slow *for this specific workload, and here's the shape of it*" is honest and more useful. Have the writer scope every claim to what you actually observed, and say the sample size out loud. This is also a credibility *advantage* — the honest caveat is usually the most trusted line in the piece.

**⚠️ Survivorship framing.** Retrospectives written after success narrate a clean path that didn't exist. If your in-the-moment clips contradict the tidy story, keep the contradiction. It's the interesting part.

**⚠️ The meta-risk: this system becomes the project.** A content engine is an appealing thing to build and it can quietly eat all the time meant for the projects it's supposed to document. Six months in with a beautiful pipeline and four published pieces is a real and common outcome.

The clean defense: **make the content engine itself your first project.** It's genuinely interesting, there's real demand for "I automated my content pipeline," it will go wrong in instructive ways, and it's self-documenting — you'll be dogfooding it while building it. If it turns out you don't enjoy the projects enough to write about them, you'll learn that in two weeks instead of six months.

**⚠️ Project abandonment.** Some projects die halfway. That's fine — *abandoned projects are content*. "I spent a week on X and stopped, here's why" is a legitimately good post and rarer than the success version. Give the harvest step an `abandoned` mode so a dead project still produces something.

---

## 8. The revised pipeline

```
┌─ STAGE 0 · SELECT ────────────────────────────────────────┐
│  trend sweep (HN + RSS + inbound.md) → candidate projects  │
│  ranked: demand × interest × failure-surface × feasibility │
│  ▸ YOU PICK ONE                                    ~30 min │
│  ▸ optional: publish "why I'm exploring X"                 │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─ STAGE 1 · BUILD ─────────────────── you, days to weeks ──┐
│  git commits accumulate (the factual record)               │
│  🎙 in-the-moment audio clips  ← the critical habit        │
│  📝 friction.md, one line per surprise                     │
│  🎥 screen capture as you go                               │
│  📄 structured retro audio at the end                      │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─ STAGE 2 · HARVEST ───────────────────── automated, ~$0.50 ┐
│  git log + gitleaks HARD FAIL + repo allowlist             │
│  transcribe all audio (~$0.003/min)                        │
│  external research: what others claim about this tech      │
│  dedupe vs published archive                               │
│  ▸ OUTPUT: content-inventory.md — 6-8 ranked briefs        │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─ STAGE 3 · PRODUCE ────────────────── per piece, weekly ──┐
│  ▸ YOU pick one brief from the inventory           ~5 min │
│  draft → grade → revise (≥8/10 or 3 tries)                │
│  ▸ YOU edit. Non-negotiable.                      ~30 min │
│  auto-publish to site (git push → Cloudflare Pages)       │
│  assets: mermaid · code cards · screenshots · thumbnail   │
│  adapt: LinkedIn (+first comment) · Facebook · YT metadata│
│  ▸ OUTPUT: outbox/<slug>/REVIEW.html                      │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─ STAGE 4 · SHIP + DRIP ───────────────────────────────────┐
│  ▸ YOU post from REVIEW.html, copy buttons        ~10 min │
│  ▸ paste 3 URLs back → posted.yml                         │
│  remaining inventory drips weekly while you build next    │
│  metrics pull → performance.md → next writer run          │
└───────────────────────────────────────────────────────────┘
```

**Your time per published piece: ~45 minutes.** Your time per project: the project itself, plus ~30 minutes of selection and the audio habit, which costs nothing because you're already sitting there.

---

## 9. Costs, final

| Item | Monthly |
|---|---|
| Domain | $1 |
| Cloudflare Pages, GitHub, OBS, ffmpeg, Mermaid, Playwright, gitleaks, HN API, RSS | **$0** |
| Transcription (~2–3 hrs) | **~$0.50** |
| LLM (writing, grading, harvest, research) | **$5–12** |
| Occasional generated imagery | **$1–3** |
| Umami analytics (self-hosted) | $0 |
| **Total** | **~$8–17/mo** |

No VPS needed yet — nothing runs unattended. No n8n yet, for the same reason. No Blotato, no Postiz, no social API developer apps, no audits, no HeyGen.

For comparison: Blotato Creator is $97/mo and could not produce any of this, because it has no access to your git history or your voice.

---

## 10. Build order

**Week 1 — habits, zero code.** Voice memo hotkey. `friction.md` in your next repo. `inbound.md`. OBS installed and configured with a clean recording profile. Verify your YouTube channel. These take an hour total and everything downstream depends on having the inputs.

**Week 2 — Stage 0 + Stage 1, manually.** Pick a project the old-fashioned way. Build it. Record audio during and after. Capture screen. Don't automate anything yet.

**Week 3 — Stage 2, the harvest.** This is the highest-value component and the one worth building first: transcription + git extract + gitleaks + allowlist + the inventory generator. Roughly 200 lines. Run it against the project you just did.

**Week 4 — Stage 3, produce one piece by hand** with Claude's help, publish it, note the friction.

**Week 5 — automate Stage 3** based on what actually annoyed you. Build `REVIEW.html`.

**Later, only if you're shipping consistently:** trend sweep automation, metrics loop, n8n.

**Suggested first project: the content engine itself.** Solves the meta-risk in §7, has real demand, will break in interesting ways, and you'll be documenting it as you build it.

---

## Related documents

- `DIY-Content-Engine-v2.md` — platform-specific manual-posting gotchas (§5) and `REVIEW.html` design (§4) still apply
- `DIY-Content-Engine-v2.1-Ingest.md` — transcription and git-extraction detail, secret-redaction specifics, trend source ranking
- `DIY-Blotato-Build-Plan.md` — superseded; relevant only if you ever want API publishing to TikTok/Instagram/X
