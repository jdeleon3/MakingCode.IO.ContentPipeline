---
name: pre-publish-review
description: Runs the site's own voice/brand check against a piece's article.md before ce publish site ships it. Use when a piece has passed ce verify and is about to be published, or when the operator asks to review a piece before it goes live.
---

Run these steps in order. This is an *additional* gate on top of this repo's own ones (ADR-008's
edit-check, `ce verify`'s claim gate G4) — it does not replace either, and does not touch git.

1. **Identify the piece.** Get the piece id from the request, or from context (e.g. the piece just
   returned by `ce verify`). Resolve its `article.md`: `data/projects/<slug>/pieces/<piece-id>/article.md`.
   If the slug isn't known, grep `data/projects/*/pieces/<piece-id>/piece.yml` to find it.

2. **Confirm the precondition gates this skill doesn't replace are actually satisfied** — don't take
   it on faith:
   - `piece.yml`'s `status` should be `verified` (not `drafted`/`edited`) — if it isn't, `ce verify
     <piece-id>` hasn't passed yet and this review is premature.
   - `article.md`'s mtime should be newer than `piece.yml`'s `generated_at` — if not, it hasn't been
     edited since generation yet (ADR-008), and `ce publish site` would refuse it anyway.

3. **Dispatch the `content-editor` agent** against the resolved `article.md` path. Let it do the
   actual review — don't duplicate its checklist here.

4. **Report the findings to the operator.** If clean, say so and name the piece as ready for
   `ce publish site <piece-id>`. If not, list what's flagged and stop — don't run `ce publish site`
   yourself, and don't edit `article.md` yourself either; that's the operator's call, and editing it
   is also what satisfies ADR-008 if they act on a finding.

5. **Never run `ce publish site` as part of this skill.** This skill only ever reviews and reports;
   publishing (the git push) stays a separate, deliberate action the operator takes themselves.
