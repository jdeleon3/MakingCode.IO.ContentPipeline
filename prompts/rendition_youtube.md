---
id: rendition_youtube
version: 1
tier: default
inputs: [article, canonical_url, title_max_chars, description_hook_chars, prior_violation]
---

<system>
Adapt the article below into a YouTube video's title, description, and
chapter markers, as if this article were the walkthrough script for that
video.

Everything below is mechanically checked after you respond. Violating any
of it fails validation and costs a wasted regeneration, so follow it
exactly:

- The title must be {{ title_max_chars }} characters or fewer.
- The description's first {{ description_hook_chars }} characters must
  contain this exact link (viewers only see this much before "show more"):
  {{ canonical_url }}
- The description holds no markdown syntax (no `**`, `_`, `#`, `[text](url)`).
- Chapters must start at `00:00` and each subsequent timestamp must be
  strictly greater than the one before it (ascending, no repeats, no gaps
  backward).

Respond in exactly this format, with these three labeled sections in this
order and no other text:

TITLE: <the title, one line>
DESCRIPTION:
<the description, one or more paragraphs, opening with the link>
CHAPTERS:
00:00 <label for the first chapter>
<MM:SS or HH:MM:SS> <label for the next chapter>
...

Previous attempt note (blank if this is your first attempt; if not blank,
it names a specific mechanical validation failure from your last response
-- fix exactly that, without otherwise changing the rest):
{{ prior_violation }}
</system>

<user>
## Article
{{ article }}
</user>
