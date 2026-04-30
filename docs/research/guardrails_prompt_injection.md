# Guardrails Prompt Injection Research

## Source links
- OWASP LLM prompt injection overview: https://owasp.org/www-community/attacks/PromptInjection
- Bluesky public API docs: https://docs.bsky.app/docs/api/app-bsky-feed-get-post-thread
- OpenAI vision guide: https://platform.openai.com/docs/guides/images-vision
- Ragas metrics: https://docs.ragas.io/en/stable/concepts/metrics/

## Exact syntax snippets
```text
UNTRUSTED_POST_TEXT
UNTRUSTED_THREAD_CONTEXT
UNTRUSTED_WEB_CONTEXT
UNTRUSTED_IMAGE_ALT_TEXT
UNTRUSTED_IMAGE_DESCRIPTION
```

```python
INJECTION_TERMS = (
    "ignore previous instructions",
    "system prompt",
    "developer message",
    "api key",
    "do not cite",
    "disable citations",
)
```

## Selected default
- Treat all retrieved text as data, never instructions.
- Scan posts, thread context, web pages, image alt text, and image descriptions before agent reasoning.
- Use fallback modes `none`, `partial`, `abstain`, and `safe_summary`.

## Rejected alternatives
- Do not echo malicious instructions as if they are normal explanatory text.
- Do not let search results trigger private/local URL fetches.
- Do not return confident uncited claims when evidence is weak or contradictory.

## Implementation consequence
Dev D eval includes web, Bluesky, image-alt, private URL, contradictory-source, unavailable, and low-evidence fixtures. Metrics report prompt-injection resistance, guardrail trigger accuracy, abstention precision/recall, unsafe output, and source quote leakage.
