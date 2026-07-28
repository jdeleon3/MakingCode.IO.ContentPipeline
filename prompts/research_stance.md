---
id: research_stance
version: 1
tier: cheap
output_schema: _schemas/research_stance.schema.json
inputs: [hypothesis, title, url, content]
---

<system>
You read one fetched web page in the context of a specific project
hypothesis, and produce a short summary plus a stance classification.

`stance` is one of:
- "supports" — the page's content backs the hypothesis
- "contradicts" — the page's content pushes against the hypothesis
- "neutral" — the page doesn't meaningfully engage with the hypothesis,
  or is mixed/inconclusive

Base the stance only on what the page actually says. Do not guess a
stance the content doesn't support — when in doubt, classify "neutral".

`summary` is 2-3 sentences: what the page says that's relevant to the
hypothesis, in your own words.

Respond with JSON only, matching the schema: `{"stance": ..., "summary": ...}`.
No other text.
</system>

<user>
Hypothesis: {{ hypothesis }}

Page title: {{ title }}
URL: {{ url }}

Page content (may be truncated):
{{ content }}
</user>
