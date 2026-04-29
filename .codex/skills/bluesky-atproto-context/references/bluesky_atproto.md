# Bluesky ATProto Notes

- Public AppView base URL: `https://public.api.bsky.app`.
- Web URL: `https://bsky.app/profile/{actor}/post/{rkey}`.
- AT URI: `at://{did}/app.bsky.feed.post/{rkey}`.

```python
from atproto import Client

client = Client(base_url="https://public.api.bsky.app")
did = client.resolve_handle(handle).did
thread = client.get_post_thread(uri=at_uri, depth=3, parent_height=2)
```

Normalize embeds:
- external links -> `ContextDocument(source_type="web")` candidates.
- image alt text and image URLs -> `ImageRef` and later `image` sources.
- quote posts -> `quoted_texts` plus citation source.

