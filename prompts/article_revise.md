---
id: article_revise
version: 1
tier: default
inputs: [article, fixes]
---

<system>
Revise the article below to address the fixes listed — and only those
fixes. Do not rewrite sections that weren't flagged; do not change the
voice, structure, or claims outside the scope of a listed fix. Preserve
everything that already works.

Respond with the full revised article body only, in Markdown — the
complete article, not a diff or a description of the changes.
</system>

<user>
## Article
{{ article }}

## Fixes to apply, ranked by impact
{{ fixes }}
</user>
