---
id: rendition_linkedin
version: 1
tier: default
inputs: [article, canonical_url_utm, max_chars, hook_chars, prior_violation]
---

<system>
Adapt the article below into a LinkedIn post. Same facts, same voice --
condensed and reformatted for a feed, not a summary that drops the
specifics.

Everything below is mechanically checked after you respond. Violating any
of it fails validation and costs a wasted regeneration, so follow it
exactly:

- Plain text only. No markdown syntax survives into the body -- no `**bold**`,
  no `_italic_`, no `# heading` lines, no `[text](url)` links.
- ASCII characters and standard punctuation only. No unicode "styling"
  characters (accessibility: a screen reader must read this correctly).
- The post body itself must not contain a URL anywhere. The link goes only
  in the separate first comment below -- never inline in the body.
- The first {{ hook_chars }} characters of the body are the visible preview
  before LinkedIn folds the rest behind "see more". That span must contain
  no URL, and must end at a sentence boundary (a period, question mark, or
  exclamation point) -- not be chopped mid-sentence.
- The body must not exceed {{ max_chars }} characters total.

Respond in exactly two parts, separated by a line containing only three
dashes (`---`):

1. The post body.
2. The first comment -- one or two sentences that include this exact link:
   {{ canonical_url_utm }}

No labels, no headers, no other commentary before, between, or after the
two parts.

Previous attempt note (blank if this is your first attempt; if not blank,
it names a specific mechanical validation failure from your last response
-- fix exactly that, without otherwise changing the post):
{{ prior_violation }}
</system>

<user>
## Article
{{ article }}
</user>
