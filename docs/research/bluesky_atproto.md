# Bluesky ATProto Research

## Source links
- Bluesky `getPostThread`: https://docs.bsky.app/docs/api/app-bsky-feed-get-post-thread
- Bluesky `searchPosts`: https://docs.bsky.app/docs/api/app-bsky-feed-search-posts
- Bluesky post structure guide: https://docs.bsky.app/docs/advanced-guides/posts
- Python AT Protocol SDK client: https://atproto.blue/en/latest/atproto_client/client.html

## Exact syntax snippets
```python
from atproto import Client, models

client = Client(base_url="https://public.api.bsky.app")
did = client.resolve_handle(handle).did
thread = client.get_post_thread(uri=at_uri, depth=3, parent_height=2)
posts = client.app.bsky.feed.search_posts(
    models.AppBskyFeedSearchPosts.Params(q=query, limit=limit, sort="top")
)
```

```text
https://bsky.app/profile/{actor}/post/{rkey}
at://{did}/app.bsky.feed.post/{rkey}
```

## Selected default
- Use Bluesky public AppView reads for public post/thread context.
- Parse only Bluesky post URLs locally, resolve handles to DID through the SDK, and construct AT URIs explicitly.
- Normalize parent replies, quote embeds, external links, image URLs, and image alt text into `PostContext`.

## Rejected alternatives
- Do not use authenticated write-capable endpoints for explanation.
- Do not scrape `bsky.app` HTML when the public API can provide the thread.
- Do not infer deleted or unavailable post content from surrounding replies.

## Implementation consequence
Dev A owns the real client. Dev D eval cases include reply, quote, image, unavailable/deleted, and malicious Bluesky-context fixtures so the client and final agent can be checked without network drift.

