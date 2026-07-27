---
id: _wp02_structured
version: 1
tier: default
output_schema: _schemas/_wp02_structured.schema.json
inputs: [topic]
---

<!-- Throwaway fixture for WP-02 gateway acceptance tests (TDD 12) —
     exercises the schema-validate-then-repair path. -->

<system>
You are a throwaway test prompt for the Content Engine LLM gateway. Respond
with JSON only, matching the schema, describing the given topic.
</system>

<user>
Describe: {{ topic }}
</user>
