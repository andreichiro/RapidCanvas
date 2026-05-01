from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, cast, overload

from app.ml.c2_policy import diagnostic_strings, safe_evidence_for_documents
from app.ml.diagnostics import dedupe_limited_values_with_warnings, make_retrieval_result
from app.schemas.domain import ContextDocument, Evidence


class RaisingDiagnostics:
    def __iter__(self) -> Iterator[str]:
        yield "first_flag"
        raise RuntimeError("diagnostic iterator failed")


class SetupFailingDiagnostics:
    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("diagnostic setup failed")


class BadString:
    def __str__(self) -> str:
        raise RuntimeError("diagnostic string failed")


class BadFloat:
    def __float__(self) -> float:
        raise RuntimeError("score failed")


class BadLimit:
    def __int__(self) -> int:
        raise RuntimeError("limit failed")


class BadSequence(Sequence[object]):
    def __len__(self) -> int:
        return 1

    @overload
    def __getitem__(self, index: int) -> object: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[object]: ...

    def __getitem__(self, index: int | slice) -> object | Sequence[object]:
        del index
        raise RuntimeError("sequence item failed")


class ExplodingAfterLimitSequence(Sequence[object]):
    def __len__(self) -> int:
        return 100

    @overload
    def __getitem__(self, index: int) -> object: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[object]: ...

    def __getitem__(self, index: int | slice) -> object | Sequence[object]:
        if isinstance(index, slice):
            return ["a", "b"]
        if index < 2:
            return f"item-{index}"
        raise RuntimeError("iterated past limit")


def _document() -> ContextDocument:
    return ContextDocument(
        id="D1",
        source_type="web",
        title="Doc",
        url="https://example.com",
        text="Mars context.",
        metadata={"sanitized": True},
    )


def _evidence() -> Evidence:
    return Evidence(id="E1", document_id="D1", source_id="D1", text="Mars context.", score=0.5)


def test_diagnostic_strings_handles_raising_iterables() -> None:
    assert diagnostic_strings(RaisingDiagnostics()) == [
        "first_flag",
        "diagnostic_iter_failed:RuntimeError",
    ]


def test_diagnostic_strings_handles_iterator_setup_failures() -> None:
    assert diagnostic_strings(SetupFailingDiagnostics()) == [
        "diagnostic_iter_failed:RuntimeError",
    ]


def test_diagnostic_strings_handles_bad_string_coercion() -> None:
    assert diagnostic_strings([BadString()]) == ["diagnostic_text_failed:RuntimeError"]


def test_safe_evidence_handles_bad_iterable_container() -> None:
    result = safe_evidence_for_documents(cast(Any, SetupFailingDiagnostics()), [_document()])

    assert result.evidence == []
    assert result.warnings == ["retrieval_evidence_iter_failed:RuntimeError"]


def test_safe_evidence_handles_score_coercion_failures() -> None:
    evidence = Evidence.model_construct(
        id="E1",
        document_id="D1",
        source_id="D1",
        text="Mars context.",
        score=BadFloat(),
    )

    result = safe_evidence_for_documents([evidence], [_document()])

    assert result.evidence[0].score == 0.0
    assert result.warnings == ["retrieval_evidence_invalid_score:E1"]


def test_make_retrieval_result_normalizes_query_values() -> None:
    result = make_retrieval_result(
        documents=[_document()],
        evidence=[_evidence()],
        queries=cast(Any, [BadString()]),
        prompt_flags=[],
        warnings=[],
        private_url_blocks=[],
    )

    assert result.queries == ["diagnostic_text_failed:RuntimeError"]
    assert result.diagnostics.search_queries == ("diagnostic_text_failed:RuntimeError",)


def test_limited_dedupe_handles_bad_sequence_container() -> None:
    values, overflow, warnings = dedupe_limited_values_with_warnings(
        BadSequence(), 5, "sequence_iter_failed"
    )

    assert values == []
    assert overflow is None
    assert warnings == ["sequence_iter_failed:RuntimeError"]


def test_limited_dedupe_does_not_iterate_sequences_past_limit() -> None:
    values, overflow, warnings = dedupe_limited_values_with_warnings(
        ExplodingAfterLimitSequence(), 2, "sequence_iter_failed"
    )

    assert values == ["item-0", "item-1"]
    assert overflow == 98
    assert warnings == []


def test_limited_dedupe_treats_bad_limit_as_zero() -> None:
    values, overflow, warnings = dedupe_limited_values_with_warnings(
        ["a"], cast(Any, BadLimit()), "sequence_iter_failed"
    )

    assert values == []
    assert overflow == 1
    assert warnings == []
