from __future__ import annotations

import re

from app.schemas.domain import PostRef

POST_URL_PATTERN = re.compile(
    r"^https://bsky\.app/profile/(?P<actor>[^/\s?#]+)/post/(?P<rkey>[^/\s?#]+)/?"
    r"(?:[?#].*)?$"
)
_DID_RE = re.compile(r"^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$")
_HANDLE_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z][A-Za-z0-9-]{0,61}[A-Za-z0-9]$"
)
_RKEY_RE = re.compile(r"^[A-Za-z0-9._~:-]{1,512}$")


class InvalidBlueskyPostUrlError(ValueError):
    """Raised when the URL is not a supported Bluesky post URL."""


def parse_post_url(url: str) -> tuple[str, str]:
    match = POST_URL_PATTERN.match(url)
    if not match:
        raise InvalidBlueskyPostUrlError("Expected https://bsky.app/profile/{actor}/post/{rkey}")
    actor = validate_actor(match.group("actor"))
    rkey = validate_rkey(match.group("rkey"))
    return actor, rkey


def validate_actor(actor: str) -> str:
    actor_text = actor.strip()
    if is_did(actor_text):
        return actor_text
    if _HANDLE_RE.match(actor_text):
        return actor_text
    raise InvalidBlueskyPostUrlError("Bluesky actor must be a handle or DID.")


def validate_rkey(rkey: str) -> str:
    rkey_text = rkey.strip()
    if not _RKEY_RE.match(rkey_text):
        raise InvalidBlueskyPostUrlError("Bluesky post rkey is invalid.")
    return rkey_text


def is_did(actor: str) -> bool:
    return bool(_DID_RE.match(actor.strip()))


def post_ref_for_did(actor: str, rkey: str, did: str) -> PostRef:
    actor_text = validate_actor(actor)
    rkey_text = validate_rkey(rkey)
    did_text = validate_did(did)
    return PostRef(
        actor=actor_text,
        rkey=rkey_text,
        did=did_text,
        at_uri=at_uri_for_post(did_text, rkey_text),
    )


def validate_did(did: str) -> str:
    did_text = did.strip()
    if not is_did(did_text):
        raise InvalidBlueskyPostUrlError("Resolved Bluesky DID is invalid.")
    return did_text


def at_uri_for_post(did: str, rkey: str) -> str:
    return f"at://{validate_did(did)}/app.bsky.feed.post/{validate_rkey(rkey)}"


def rkey_from_at_uri(at_uri: str) -> str | None:
    parts = at_uri.split("/")
    if len(parts) != 5 or parts[0] != "at:" or parts[1] != "":
        return None
    if parts[-2] != "app.bsky.feed.post":
        return None
    try:
        return validate_rkey(parts[-1])
    except InvalidBlueskyPostUrlError:
        return None


def post_url_for_author(author: str, at_uri: str) -> str | None:
    rkey = rkey_from_at_uri(at_uri)
    if not rkey:
        return at_uri or None
    try:
        actor = validate_actor(author)
    except InvalidBlueskyPostUrlError:
        return at_uri or None
    return f"https://bsky.app/profile/{actor}/post/{rkey}"
