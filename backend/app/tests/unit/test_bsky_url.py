from __future__ import annotations

from pytest import raises

from app.clients.bsky_url import (
    InvalidBlueskyPostUrlError,
    at_uri_for_post,
    is_did,
    parse_post_url,
    post_ref_for_did,
    post_url_for_author,
    rkey_from_at_uri,
    validate_actor,
)


def test_parse_post_url_accepts_trailing_slash_query_and_fragment() -> None:
    actor, rkey = parse_post_url("https://bsky.app/profile/example.com/post/3abcxyz/?x=1#fragment")

    assert actor == "example.com"
    assert rkey == "3abcxyz"


def test_parse_post_url_rejects_invalid_actor_and_rkey() -> None:
    with raises(InvalidBlueskyPostUrlError):
        parse_post_url("https://bsky.app/profile/bad_actor/post/3abcxyz")
    with raises(InvalidBlueskyPostUrlError):
        parse_post_url("https://bsky.app/profile/bad-.example.com/post/3abcxyz")
    with raises(InvalidBlueskyPostUrlError):
        parse_post_url("https://bsky.app/profile/example.com/post/bad/rkey")


def test_did_and_at_uri_helpers_round_trip_post_reference() -> None:
    ref = post_ref_for_did("example.com", "3abcxyz", "did:plc:example")

    assert is_did("did:plc:example") is True
    assert validate_actor("example.com") == "example.com"
    assert ref.at_uri == "at://did:plc:example/app.bsky.feed.post/3abcxyz"
    assert at_uri_for_post("did:plc:example", "3abcxyz") == ref.at_uri
    assert rkey_from_at_uri(ref.at_uri) == "3abcxyz"
    assert post_url_for_author("example.com", ref.at_uri) == (
        "https://bsky.app/profile/example.com/post/3abcxyz"
    )


def test_at_uri_helpers_do_not_construct_public_urls_from_invalid_parts() -> None:
    assert rkey_from_at_uri("https://example.com/app.bsky.feed.post/3abcxyz") is None
    assert rkey_from_at_uri("at://did:plc:example/app.bsky.feed.post/bad/rkey") is None
    assert post_url_for_author(
        "bad-.example.com", "at://did:plc:example/app.bsky.feed.post/3abcxyz"
    ) == ("at://did:plc:example/app.bsky.feed.post/3abcxyz")
