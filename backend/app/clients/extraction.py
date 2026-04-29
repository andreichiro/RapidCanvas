"""Readable text extraction helpers for safe web fetching."""

from __future__ import annotations

import importlib
from html.parser import HTMLParser
from typing import Any

from app.guardrails.prompt_injection import sanitize_untrusted_text


class _TextExtractor(HTMLParser):
    """Small stdlib fallback when optional extraction dependencies are absent."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() == "title":
            self._in_title = False
            self.title = sanitize_untrusted_text(" ".join(self._title_parts), max_chars=200)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._parts.append(data)

    @property
    def text(self) -> str:
        """Return compact extracted text."""

        return sanitize_untrusted_text(" ".join(self._parts))


def extract_page_text(raw: str, content_type: str = "text/html") -> tuple[str, str]:
    """Extract title and readable text with trafilatura first, then fallbacks."""

    if content_type in {"text/plain", "text/xml", "application/xml"}:
        return "", sanitize_untrusted_text(raw)

    trafilatura_text = _extract_with_trafilatura(raw)
    if trafilatura_text:
        return _extract_title(raw), sanitize_untrusted_text(trafilatura_text)

    soup_title, soup_text = _extract_with_bs4(raw)
    if soup_text:
        return soup_title, soup_text

    parser = _TextExtractor()
    parser.feed(raw)
    return parser.title, parser.text


def _extract_with_trafilatura(raw: str) -> str:
    try:
        trafilatura: Any = importlib.import_module("trafilatura")
    except ImportError:
        return ""
    extracted = trafilatura.extract(raw, include_comments=False, include_tables=False)
    return str(extracted or "")


def _extract_with_bs4(raw: str) -> tuple[str, str]:
    try:
        bs4: Any = importlib.import_module("bs4")
    except ImportError:
        return "", ""
    soup = bs4.BeautifulSoup(raw, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    title = sanitize_untrusted_text(soup.title.get_text(" ") if soup.title else "", max_chars=200)
    text = sanitize_untrusted_text(soup.get_text(" "))
    return title, text


def _extract_title(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw)
    return parser.title
