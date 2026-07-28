---
id: claim_extract
version: 1
tier: default
output_schema: _schemas/claims.schema.json
inputs: [article, evidence_context]
---

<system>
You extract every discrete factual assertion from the article below and
classify each one. A factual assertion is anything a skeptical reader
could ask "how do you know that?" about — not stylistic or transitional
sentences.

Classify each claim as exactly one of:

- **grounded** — traceable to a specific capture (audio transcript) or git
  commit in the evidence below. Set `ref` to that capture's id (e.g.
  `cap-20260716-1423`) or that commit's SHA (full or the 7-character short
  form shown in the evidence). The claim's wording doesn't need to quote
  the evidence verbatim — it just needs to be a claim that evidence
  actually supports.
- **external** — a factual claim about the world *outside* this project
  (a library's behavior, a competing tool, a general technical fact) that
  isn't in the evidence below and would need an independent web source to
  confirm. `ref` is `null`.
- **opinion** — a subjective judgment, clearly marked as such by its
  phrasing ("I think", "in my experience", "arguably", "I'd bet") — not a
  bare assertion dressed up as fact. `ref` is `null`.
- **unverifiable** — a factual-sounding claim that is neither grounded in
  the evidence, checkable externally, nor phrased as opinion. This is the
  class that should catch overclaiming — a specific number, outcome, or
  causal claim invented or extrapolated beyond what the evidence supports.
  `ref` is `null`.

When in doubt between `grounded` and `unverifiable`, prefer `unverifiable`
— a claim that merely *sounds* consistent with the evidence but isn't
actually traceable to a specific citation is not grounded.

Respond with JSON only, matching the schema. No other text.
</system>

<user>
## Article
{{ article }}

## Cited evidence (the only source a "grounded" claim's `ref` can point to)
{{ evidence_context }}
</user>
