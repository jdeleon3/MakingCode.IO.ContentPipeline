---
id: rendition_facebook
version: 1
tier: default
inputs: [article, canonical_url_utm, max_chars, prior_violation]
---

<system>
Adapt the article below into a Facebook post. Same facts, same voice --
condensed and reformatted for a feed, not a summary that drops the
specifics. Facebook readers tolerate a more conversational, emoji-friendly
register than LinkedIn -- feel free to use it if it fits the voice.

Everything below is mechanically checked after you respond. Violating any
of it fails validation and costs a wasted regeneration, so follow it
exactly:

- Plain text only. No markdown syntax survives into the body -- Facebook
  displays `**`, `_`, `#`, `[text](url)` literally instead of rendering
  them, so none of that syntax should appear.
- The post must include this exact link, inline in the body (unlike
  LinkedIn, Facebook links are fine in the body itself -- no separate
  comment needed): {{ canonical_url_utm }}
- The body must not exceed {{ max_chars }} characters total.

Respond with the post body only -- no labels, no headers, no other
commentary before or after it.

Previous attempt note (blank if this is your first attempt; if not blank,
it names a specific mechanical validation failure from your last response
-- fix exactly that, without otherwise changing the post):
{{ prior_violation }}
</system>

<user>
## Article
{{ article }}
</user>
