# Brand Brief

## §1 — Standing

**I have standing to write about:**
- 14 years in enterprise software, insurance industry — C# microservices for carrier/web integrations, promoted developer → Lead Software Developer → Software Engineer.
- 5 years as Java Technical Lead directing an event-driven Claims System implementation with the software provider.
- MS in Computer Science (Angelo State University, Dec 2025), ML focus, Python coursework.
- Built a DOD-funded capstone (Kafka/Spark/Neo4j/TimescaleDB pipeline training GNN models for anomaly detection with explainability) against a real IEEE Dataport hardware-in-the-loop testbed dataset.
- Built a text-classification fraud detector for job postings, with a full backend/frontend/AWS CDK deployment around it.
- Directed an AI-assisted build of a production ordering site (Astro/Supabase/Cloudflare) — prompting, reviewing, and evaluating Claude Code's output — and configured the self-hosted n8n automation around it.
- 14 years of enterprise software experience now expanding deliberately into AI and business automation. That's the throughline, not a side note.

**I explicitly do not have standing on:**
- Performance engineering and security — I think about them, I don't have deep expertise.
- Frontend design — mid at best; I lean on AI tooling to do the actual design work.

---

## §2 — Audience

**Who is reading this:** Engineers with real fundamentals — often years of "unglamorous" enterprise experience — trying to translate that into AI/ML and business-automation work rather than start over from zero. Closer to my own transition point than to a bootcamp grad or a career-switcher with no background.

**What they already know:** The basics of the tools and languages involved. They don't need syntax explained — they want practical application.

**What they're stuck on:** How to actually translate existing skills into AI/ML work, in a landscape full of fluff content and empty-promise clickbait that never shows the real translation.

**What they'd be embarrassed to ask:** What's my actual path forward? I have a decade-plus of experience — is that an asset or a liability given ageism in tech? How do I upskill and stay ahead of the curve without starting from zero?

**Technical calibration:** `practitioner` — skewing toward beginner on ML/AI-specific material, practitioner on general engineering.

---

## §3 — What I believe that others don't

1. Most AI/ML content in the wild is either impractical for real-world use, or deliberately half-baked — just enough to get you to sign up for someone's course, newsletter, or product.
2. "Boring" enterprise experience transfers to AI/ML work more than the industry pretends. You're not starting from zero.
3. Ageism in tech is real — the answer isn't panic, but it might mean genuinely finding a new path forward rather than bolting AI onto the old one, and that requires a deliberate upskilling plan.
4. None of this is passive. There's no do-it-in-your-sleep version — actually understanding the business applications of AI and automation takes real time and effort, not just running a demo.

**Where the consensus is right and I'm not fighting it:** Don't reinvent the wheel. Standards exist for a reason — I'd rather follow an approach with real examples to learn from than pioneer a new one if it ends in the same result.

---

## §4 — Scope

**In scope:** translating experienced-engineer skills into AI/ML and business automation; honest build logs of real projects (what actually happened, not tutorial gloss); AI-assisted development practice (prompting, reviewing, evaluating — not just "AI wrote it"); the career-transition angle for people well past entry-level.

**Out of scope:** generic "AI will change everything" hype, career advice unrelated to tech, crypto, politics.

**Adjacent, only when it intersects my work:** insurance-industry specifics — only as a source of transferable engineering lessons, never insurance-domain content for its own sake.

---

## §5 — Voice

**Instead of X, I'd say Y:**

| A generic post would say | I'd say |
|---|---|
| "There are several considerations to keep in mind" | "Here's what actually matters. The rest is noise." |
| "This can be a game-changer for your workflow" | "This saved me real time. It might not for you — here's what would have to be true first." |
| "Let's dive into the details" | *(cut entirely — just start)* |

**Three sentences that sound like me:**
1. "Most demonstrations wouldn't fly in real-world application, a lot of people are just feeding you enough to get you to sign up for something from them."
2. "None of this happens passively in your sleep. It takes time and effort to actually understand the business applications."
3. "I have all this experience, and ageism is a thing.  The question is how to upskill and stay ahead of the curve."

**How I handle being wrong:** State the correction flatly and move on (no self-flagellation, no over-explaining).

**How I handle uncertainty:** Name the specific unknown rather than hedge the whole claim — e.g. "I don't know if this translates to your stack" instead of "results may vary."

---

## §6 — Sentence-level rules

- Lead with the finding, not the setup. No throat-clearing.
- Every claim gets a number, a name, a version, or an error message. Vague claims get cut.
- Prefer the specific noun to the category. "DuckDB 1.1" not "the database."
- One idea per paragraph. Max ~4 sentences.
- No rhetorical questions as section openers.
- No "in today's fast-paced world" style scene-setting. Ever.
- Contractions are fine. Sentence fragments are fine when they land.
- If a sentence could appear in any post on this topic, delete it.
- Name the tradeoff. Anything presented as free is a lie of omission.
- Second person for instructions, first person for experience. Never "we" for a solo project.
- No urgency/FOMO framing ("act now or get left behind") — say what actually changed and let the reader decide.
- No vague "upskill" advice without a concrete next action attached.

---

## §7 — Banned phrases

```
delve                          in today's landscape
dive into / deep dive          it's important to note
unlock / unleash               at the end of the day
game-changer                   when it comes to
revolutionize                  navigate the complexities
harness the power of           testament to
seamless / seamlessly          leverage (as a verb)
robust (unqualified)           elevate your
cutting-edge                   supercharge
in the ever-evolving world     transformative
that's where X comes in        the beauty of X is
let's face it                  here's the kicker
buckle up                      but here's the thing
I'll be honest                 the truth is
not just X, but Y              it's not about X — it's about Y
```

**Structural bans:**
- Rule-of-three lists where the third item is filler
- Em-dash asides stacked more than once per paragraph
- Ending on a rhetorical flourish instead of a concrete next step
- "In conclusion" or any labelled summary of a piece under 2,000 words

**My additions:**
- "stay ahead of the curve" (unqualified — earn it with a specific or cut it)
- "unlock your potential" / "level up" / other bootcamp-marketing language
- anything that reads like a funnel toward a course, newsletter, or signup, even implicitly

---

## §8 — Evidence and honesty standards

**When I have one data point, I say:** the exact project, its scale, and what I haven't tested beyond it.

**When I'm extrapolating, I mark it by:** prefixing "my guess is," and naming what would change my mind.

**Numbers I will always include when relevant:** version numbers, dataset/workload size, hardware, time spent, and whether it was a class project, side project, or production.

**I will never:**
- present a single benchmark as a general claim
- omit the workload shape when quoting performance
- imply I've used something in production when I've used it in a side project or class project
- give performance or security guidance as if it's a strength — it isn't (see §1)

---

## §9 — Call to action

**Primary:** Reply with their own experience.

**My CTA, phrased how I'd actually say it:** "If you've hit this same wall translating years of experience into AI/automation work, reply and tell me what actually worked for you."

**What I never do:** "Drop a comment below," newsletter popups, anything that reads as a funnel.

---

## §10 — Platform deltas

Left blank — §5's voice applies everywhere until publishing a few pieces surfaces real platform-specific needs.

---

## §11 — What a bad piece looks like

**A piece I'd be embarrassed to publish:** A post indistinguishable from every other "I upskilled into AI" LinkedIn post — vague, no real numbers, secretly funneling toward a course or signup.

**The most likely way this system fails me:** Smoothing the actual messiness of translating a 14-year enterprise career into AI/automation work into a tidy "here's how I did it" narrative, when the honest version is still in progress and not fully resolved.
