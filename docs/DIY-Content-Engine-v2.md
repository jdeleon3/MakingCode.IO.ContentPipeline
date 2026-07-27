# DIY Content Engine — v2 (revised scope)

**Targets:** personal website (static site) · LinkedIn · Facebook · YouTube
**Posting:** website auto-published; the three socials posted manually by you
**Origin:** idea first, AI drafts everything
**Volume:** ~1 piece/week to start, must scale without a rebuild
**Date:** July 2026

> Supersedes `DIY-Blotato-Build-Plan.md`. The earlier constraints (9 platforms, API publishing) made this a hard project. These constraints make it a genuinely easy one — and flip the build-vs-buy answer.

---

## 1. What changed

Dropping API publishing removes every hard problem in the previous plan:

| Previously the blocker | Now |
|---|---|
| TikTok audit (posts forced to `SELF_ONLY`) | **Gone** — not a target platform |
| YouTube compliance audit + OAuth verification | **Gone** for posting. Still relevant if you later want *read-only* analytics, which is a much lower bar |
| X pay-per-use (~$0.20/post with a link) | **Gone** — not a target platform |
| Meta App Review / dev-mode cliff | **Gone** for posting |
| OAuth token refresh across 9 platforms | **Gone** — no tokens to manage |
| LinkedIn Community Management API | **Gone** — you're posting by hand |

**Verdict, reversed: don't buy Blotato.** Its entire moat was being an audited publishing client for TikTok/Instagram/X. You're not using any of those, and you're not publishing via API. Paying $29/mo would buy you AI writing you can do better yourself, plus nine integrations you'd never touch. Build it.

**New cost reality: ~$5–15/month** for everything except YouTube video (see §6). Build time for something genuinely useful: **8–15 hours**, not 60.

The hard part is no longer engineering. It's §2.

---

## 2. The one thing that will kill this project

**"Idea first, AI drafts everything" + a personal website + SEO ambitions is the single highest-risk configuration in content automation.** Not for technical reasons. Be clear-eyed about this before building anything.

Google does not penalize AI-generated content as such — production method isn't the signal. What it does penalize, explicitly, is **scaled content abuse** and **fabricated expertise**: unoriginal content produced at volume that doesn't demonstrate real experience. An ungrounded topic-in/article-out pipeline produces exactly that, by construction. So does a LinkedIn feed of confident takes assembled from model priors.

The failure isn't a penalty notice. It's quieter: nothing ranks, nobody comments, and you can't tell why because every individual piece reads fine.

**The fix is architectural, and it's the most important thing in this document: put a mandatory grounding gate between the idea and the draft.** No piece may be written until it has at least one of:

1. **Your own experience** — something you did, tried, measured, or got wrong. Even three bullet points of raw voice-note transcript is enough. This is the highest-value input and the only truly defensible one.
2. **A primary source you fed it** — a doc, a dataset, a paper, a transcript, a real conversation.
3. **Original synthesis across ≥3 fetched sources** — genuinely comparative, with the disagreements between them named rather than smoothed over.

If none of the three exists, the pipeline should refuse to draft. That refusal is a feature. It converts "AI writes my content" into "AI writes *up* my thinking," which is the version that works.

**Practical implementation:** a `grounding` field in the idea record that must be non-empty, plus a pre-draft LLM check that scores evidence density and rejects anything that reads as generic. Ten lines of workflow. It's the difference between this project working and quietly wasting a year.

Second-order: keep a `voice/` folder of things you've actually written or said, and RAG over it. "Idea first" doesn't have to mean "voiceless" — but it will by default unless you build against it.

---

## 3. Architecture

Everything is a folder on disk and a git repo. No database until you need one.

```
IDEA INBOX  (ideas.md, or a Notion table — anything appendable)
      │
      ▼
GROUNDING GATE  ◄── §2. Refuses to proceed without evidence.
   voice note · source doc · 3+ fetched sources
      │
      ▼
RESEARCH PASS
   web fetch · your voice/ corpus · prior posts (dedupe check)
      │
      ▼
CANONICAL ARTICLE  ← the website piece. Written first, always.
   draft → grade (0-10) → revise → repeat until ≥8 or 3 tries
      │
      ├──────────► AUTO-PUBLISH: git commit → push → Cloudflare Pages
      │            URL exists BEFORE any social post is written
      ▼
REPURPOSE FAN-OUT  (reads the published URL)
   ├→ LinkedIn post + first-comment text
   ├→ Facebook post
   └→ YouTube script + metadata block
      │
      ▼
ASSET RENDER
   hero image (Flux) · quote cards + carousels (HTML→Playwright, free)
   YouTube thumbnail · optional video
      │
      ▼
PACKAGE → /outbox/2026-07-26-slug/
      │
      ▼
YOU POST MANUALLY  (~10 min, one review page, copy buttons)
      │
      ▼
LOG BACK  paste the 3 URLs into posted.yml
      │
      ▼
METRICS (read-only, easy) → feeds next week's writer
```

### Why the website is written first and published first

Three reasons, all practical:

1. **The social posts need the URL.** Writing them first means find-and-replacing a placeholder later, which is where broken links come from.
2. **Open Graph tags must be live before you share the link,** or the preview card renders blank — and Facebook caches its first scrape aggressively. Publish, verify the card in Facebook's Sharing Debugger, *then* post.
3. **It's the only asset you own.** LinkedIn and Facebook are rented. The article is the thing that compounds, gets indexed, and still exists if a platform changes its mind about you.

### The stack

| Layer | Choice | Why |
|---|---|---|
| Site | **Astro** | Best-in-class for content sites, markdown-native, near-zero JS shipped, trivial OG tag handling. Hugo is faster to build but a worse authoring experience; Next.js is overkill for a content site. |
| Hosting | **Cloudflare Pages** | Free, fast, git-push deploys, no cold starts |
| Content store | **The git repo itself** | Every draft, every revision, diffable. No database. |
| Orchestration | **Claude skills + scripts to start.** n8n later. | See §7 — at 1 piece/week with manual posting, an always-on automation server solves a problem you don't have yet |
| Analytics | **Umami or Plausible, self-hosted** | Free, no cookie banner, and UTM-aware — which matters a lot here (§5) |
| Assets | **Playwright** (HTML→PNG) | Free, unlimited, fully branded. Better than any SaaS carousel tool once templated. |

---

## 4. The packaging layer — your replacement for "publish"

This is the part no off-the-shelf tool does, and it's what makes manual posting take 10 minutes instead of 45. The output of every run is one folder:

```
outbox/2026-07-26-why-most-automation-fails/
├── REVIEW.html              ← open this. It's the whole interface.
├── 00-checklist.md
├── 01-website/
│   ├── article.md           (already published — URL in checklist)
│   └── hero.png
├── 02-linkedin/
│   ├── post.txt             (link-free body, hook above the fold)
│   ├── first-comment.txt    (the link, with UTM)
│   └── image.png            (1200×1200)
├── 03-facebook/
│   ├── post.txt
│   └── image.png            (1200×630)
└── 04-youtube/
    ├── script.md
    ├── metadata.txt         (title / description / chapters / tags)
    ├── thumbnail.png        (1280×720)
    └── video.mp4            (if generated)
```

**`REVIEW.html`** is a single self-contained local file — no server, no build step. It shows each platform's copy in a box with a **Copy** button, the image with a **download/reveal-in-folder** link, a character counter against that platform's limits, and a checkbox per platform. At the bottom, three input fields to paste the resulting post URLs, which write back to `posted.yml`.

That last bit matters more than it sounds: **manual posting breaks the feedback loop unless you deliberately close it.** Pasting three URLs is the cheapest possible fix, and it's what lets §9's learning loop work at all.

---

## 5. Manual posting playbook + gotchas

The gotchas are now about *human* posting mechanics, and they're the difference between a post that reaches 200 people and one that reaches 2,000.

### LinkedIn

- **Never put an outbound link in the post body.** Reach suppression on link posts is well-documented and large. Link goes in the **first comment**, posted by you immediately after. Your pipeline should generate both, separately.
- **The hook must land above the "see more" fold** — roughly the first 2–3 short lines on mobile. Everything after is optional reading. Your grader should score the first 200 characters as a standalone unit.
- **LinkedIn strips markdown.** No bold, no italics, no headers. Unicode-bold characters render as gibberish in screen readers and hurt accessibility — don't use them. Structure with line breaks and spacing instead.
- Single line breaks sometimes collapse. Use double.
- Rate reality: ~1 post/day maximum before your own audience tunes out. This is a human limit, not an API one.

### Facebook

- **Decide Page vs personal profile now.** A Page gets you analytics and is the right call for anything business-adjacent, but organic Page reach is brutal — low single-digit percentages of followers. Personal profile reaches more people but has no metrics and mixes your work with your life.
- Unlike LinkedIn, **links in the body are fine**, but native photo posts still outperform link posts. Best pattern: upload the image natively, put the link in the body text.
- **Run every URL through Facebook's Sharing Debugger once before posting.** Facebook caches its first OG scrape and will happily serve a blank preview card for days. The Debugger forces a re-scrape. This is the single most common self-inflicted wound in this workflow.

### YouTube

- **Thumbnail is ~80% of click-through.** Everything else is rounding error. Generate it deliberately, not as an afterthought.
- Custom thumbnails require a **verified channel** — do this today, it takes 2 minutes and a phone number.
- Title: keep the meaningful part inside ~60 characters; it truncates in search and suggested feeds.
- Description: **the first ~150 characters** are what shows above the fold and what gets indexed. Put the link and the hook there.
- **Chapters require a `00:00` entry** and at least three timestamps, ascending. They're free retention and most people skip them.
- Tags are near-worthless for ranking now. Don't spend generation budget on them.

### Website

- Publish, then **verify the canonical URL and OG tags render**, then generate social copy against the live URL.
- **UTM-tag every social link** (`?utm_source=linkedin&utm_medium=social&utm_campaign=<slug>`). Because you're posting manually, this is your *only* attribution mechanism — there's no API telling you where clicks came from. Bake it into the packaging step so you can't forget.
- Keep the article's slug stable. Changing it after you've posted three links is how you get 404s in someone else's feed.

### Closing the metrics loop (read-only is easy)

Posting APIs are gated. **Reading your own analytics mostly isn't.**

| Source | Difficulty | Notes |
|---|---|---|
| Your site (Umami/Plausible) | 🟢 Trivial | Self-hosted, full API, UTM breakdown |
| YouTube Analytics API | 🟢 Easy | Your own channel, standard OAuth, no audit needed for read |
| Facebook Page Insights | 🟡 Moderate | Dev mode as Page admin works |
| LinkedIn personal post metrics | 🔴 Effectively closed | No API. Manual entry into `posted.yml`, or skip it and use site referrals as the proxy |

The LinkedIn gap is real but survivable — UTM-tagged clicks to your own site tell you most of what you need.

---

## 6. The YouTube reality check

This deserves its own section because there's a widespread misconception worth heading off.

**"AI drafts everything" does not extend to long-form video.** Veo, Kling, and Sora generate **5–10 second clips**. There is no model that takes a script and returns an 8-minute video. Your realistic options:

| Approach | Cost | Quality | Honest take |
|---|---|---|---|
| **You record, AI scripts** | $0 | Highest | Best ROI by a wide margin. AI writes the script, you talk. |
| Screen recording + AI script + TTS | ~$5/mo | Good for tutorial/explainer | Excellent fit if your topics are demonstrable |
| Slideshow + TTS narration | ~$5/mo | Low retention | YouTube's algorithm punishes this. Fine for a podcast-style upload, poor for growth. |
| **AI avatar (HeyGen)** | Creator $29/mo ≈ **10 min of Avatar IV**; Pro $99/mo ≈ 100 min; API ~$3/min | Uncanny but improving | At 1 six-minute video/week (~24 min/mo) you'd need Pro. **$99/mo is more than the rest of this stack combined.** |
| Generated b-roll stitched with ffmpeg | $30–90/mo | Inconsistent | Expensive and fiddly for long-form |

**Recommendation: defer YouTube.** It is 5–10× the effort per piece of the other three, it's the one target where "AI drafts everything" genuinely doesn't work, and at "just getting started" volume it will be the thing that makes you abandon the whole system.

Build website + LinkedIn + Facebook first. Prove you can ship weekly for six weeks. *Then* add YouTube — and when you do, start with "AI scripts, you record," which is both free and better than every automated alternative.

---

## 7. Accounts and costs

### Sign-ups needed

| Service | Purpose | Cost |
|---|---|---|
| Domain registrar | Your site | ~$12/yr = **$1/mo** |
| **Cloudflare Pages** | Static hosting + deploys | **$0** |
| GitHub | Content repo | **$0** |
| Anthropic or OpenAI API key | Writing, grading, research | **$3–10/mo** at this volume |
| fal.ai or Replicate | Hero images (Flux) | **$1–3/mo** |
| Umami Cloud or self-hosted | Analytics | **$0** self-hosted |
| Facebook Page | If going the Page route | $0 |
| YouTube channel + **verify it** | Custom thumbnails | $0 |

**Not needed:** VPS (yet), n8n (yet), Postiz, Blotato, any social API developer app, any audit.

### Monthly total

| Phase | Cost |
|---|---|
| **Phase 1–2** (website + LinkedIn + Facebook, no video) | **$5–15/mo** |
| Add TTS-narrated video | +$5/mo |
| Add HeyGen avatar video (Pro) | +$99/mo ⚠️ |
| Add VPS + n8n when volume justifies | +$8–15/mo |

Compare: Blotato Starter $29, Creator $97. **At your scope, DIY is both cheaper and strictly more capable** — because the capability you need (grounded long-form → canonical site → repurpose) is precisely what Blotato doesn't do.

### Why no n8n yet

You picked self-hosted n8n earlier, and it's the right call *eventually*. But n8n's value is unattended scheduled execution. With a human posting every piece by hand at one piece per week, nothing runs unattended — you're present for every step anyway. An always-on server would be infrastructure you maintain for zero benefit.

**Trigger to add it:** when you're producing 3+ pieces/week, or when you want the metrics loop pulling automatically each morning, or when idea-inbox scraping (RSS/competitor watch) becomes worth running nightly. Design everything as scripts with clean inputs and outputs now, and wrapping them in n8n later is an afternoon.

---

## 8. Build order

Deliberately small. The failure mode at this stage is building a beautiful pipeline and publishing nothing through it.

### Phase 0 — before any code (1 hour)
1. Register domain, create GitHub repo, deploy an empty Astro site to Cloudflare Pages. Confirm push → live.
2. Verify your YouTube channel (2 min, unlocks thumbnails later).
3. Decide Facebook Page vs profile.
4. Write `brand-brief.md` by hand: who you're for, what you believe that others don't, what you want readers to do, three phrases you'd never say. **This file is the highest-leverage artifact in the system.** Everything reads it.

### Phase 1 — ship one piece manually, end to end (2 hours)
No automation at all. Write one article with Claude's help, publish it, post it to LinkedIn and Facebook by hand. Time each step and write down what was annoying.

**You cannot design the packaging layer until you've felt the friction.** Skipping this produces a tool that automates the wrong things.

### Phase 2 — the writing engine (4–6 hours)
1. `brand-brief.md` + `voice/` folder with anything you've written.
2. **Grounding gate** (§2) — refuses to draft without evidence. Build this first, not last.
3. Writer → grader → revise loop. The grader scores hook, specificity, evidence density, and CTA out of 10 and returns the three highest-impact fixes; loop until ≥8 or 3 attempts.
4. Output: `article.md` in the repo, ready to commit.

### Phase 3 — packaging (3–4 hours)
1. Repurpose fan-out: article → LinkedIn body + first comment, Facebook post.
2. Playwright templates for hero image and quote cards.
3. `REVIEW.html` generator with copy buttons, character counters, and URL write-back.
4. UTM injection.

**After Phase 3 you have the whole product for your scope.** Everything below is optional.

### Phase 4 — the loop (2–3 hours)
`posted.yml` → weekly metrics pull (site + YouTube + FB Page) → a `performance.md` the writer reads as few-shot examples.

### Phase 5 — only if you're actually shipping weekly
Idea inbox automation, n8n, YouTube.

---

## 9. Features worth adding that Blotato doesn't have

Revised for this setup, ranked by impact:

**1. The grounding gate ⭐** — §2. The whole project's success rests on it. Nothing on the market has this because it *reduces* output volume, which is the opposite of what content tools sell.

**2. Canonical-first architecture with UTM attribution** — every social post is a pointer to an asset you own, and you can measure which platform actually sends humans. Most creators post into platforms and never learn this.

**3. The `REVIEW.html` briefcase** — turns manual posting from a 45-minute chore into 10 minutes. The reason human-in-the-loop systems get abandoned is friction at exactly this step.

**4. Repetition guard** — embed each piece, compare against the last 90 days, hard-block anything above ~0.9 similarity. AI pipelines drift into saying the same thing repeatedly; you notice long after your audience does.

**5. Claim verification gate** — extract factual assertions before publish, verify each with a search. With AI drafting everything, this is not optional — it's the thing standing between you and confidently publishing something false under your own name.

**6. Voice RAG over your own writing** — retrieval over `voice/` so drafts sound like you rather than like an LLM's median blog post. Directly counteracts the main weakness of "idea first."

**7. Git-native content history** — every draft and revision diffable. Change the brand brief, see exactly when and what shifted. No export, no lock-in, no vendor.

**8. Idea backlog with a staleness sweep** — ideas rot. Auto-flag anything sitting unwritten for 60+ days for kill-or-commit, so the inbox doesn't become a guilt pile.

**9. Cost governor** — hard monthly ceilings per API with graceful degradation. Trivial now, essential the moment you add video.

**10. Evergreen recycling** — surface articles still getting traffic 6+ months later and regenerate fresh social angles for them. At 1 piece/week your archive is your most underused asset within a year.

---

## 10. What I'd do next week

1. **Phase 0 + Phase 1.** Domain, empty Astro site live, then publish one real piece and post it by hand. Three hours total. You'll learn more from that than from any further planning.
2. Write `brand-brief.md` before anything else touches an LLM.
3. **Don't build the pipeline until you've shipped two pieces manually.** The friction you feel in week one is the spec.

Then Phase 2. The writer/grader loop with a grounding gate is genuinely fun to build and it's ~80% of the value of everything described here.

---

## Sources

- [Google spam policies — scaled content abuse & AI content, 2026](https://www.jsonhouse.com/posts/google-ai-content-penalties-2026/) · [policy clarification May 2026](https://ppc.land/google-spam-policies-now-officially-cover-ai-overviews-and-ai-mode-in-search/)
- [HeyGen pricing 2026 — plans and credit math](https://www.arcade.software/post/heygen-pricing) · [eesel breakdown](https://www.eesel.ai/blog/heygen-pricing)
- [AI video generation API pricing, July 2026](https://www.buildmvpfast.com/api-costs/ai-video)
- [YouTube Data API — quota and compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) (relevant only if you later automate uploads)
- [Blotato pricing](https://www.blotato.com/pricing) — for the build-vs-buy comparison
