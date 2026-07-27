---
id: _wp02_echo
version: 1
tier: cheap
inputs: [message]
---

<!-- Throwaway fixture for WP-02 gateway acceptance tests (TDD 12).
     Not part of the §11 prompt registry — real prompts arrive with the
     WPs that produce them (WP-08 brief_generate, WP-09 article_draft, ...). -->

<system>
You are a throwaway test prompt for the Content Engine LLM gateway. Reply
with exactly the message you are given and nothing else.
</system>

<user>
{{ message }}
</user>
