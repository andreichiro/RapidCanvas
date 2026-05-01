"""Dev C-owned normalizer for Dev B-shaped retrieval output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from app.schemas.domain import ContextDocument, Evidence


@dataclass(frozen=True)
class EvidenceBundle:
    """Evidence, source documents, and diagnostics consumed by the explainer."""

    evidence: tuple[Evidence, ...] = ()
    documents: tuple[ContextDocument, ...] = ()
    warnings: tuple[str, ...] = ()
    guardrail_flags: tuple[str, ...] = ()
    source_safety_diagnostics: tuple[str, ...] = ()


RetrievalOutput = (
    EvidenceBundle | tuple[Sequence[Evidence], Sequence[ContextDocument]] | Mapping[str, Any] | Any
)
ModelT = TypeVar("ModelT", bound=BaseModel)


def normalize_retrieval_output(
    output: RetrievalOutput,
    *,
    retriever: Any | None = None,
) -> EvidenceBundle:
    """Normalize tuple, dict, object, or diagnostics-bearing Dev B retrieval output."""

    base = _base_bundle(output)
    diagnostics = _field(output, "diagnostics", "retrieval_diagnostics", default=None)
    if diagnostics is None and retriever is not None:
        diagnostics = getattr(retriever, "last_diagnostics", None)

    source_safety_diagnostics = _diagnostic_source_safety(base, diagnostics)
    explicit_guardrail_flags = _dedupe([*base.guardrail_flags, *_diagnostic_flags(diagnostics)])
    return EvidenceBundle(
        evidence=base.evidence,
        documents=base.documents,
        warnings=_diagnostic_warnings(base, diagnostics, retriever),
        guardrail_flags=_dedupe(
            [*explicit_guardrail_flags, *_derived_source_safety_flags(
                source_safety_diagnostics,
                explicit_guardrail_flags,
            )]
        ),
        source_safety_diagnostics=source_safety_diagnostics,
    )


def _base_bundle(output: RetrievalOutput) -> EvidenceBundle:
    if isinstance(output, EvidenceBundle):
        return output
    if _looks_like_tuple_output(output):
        evidence, documents = output
        return EvidenceBundle(
            evidence=_model_tuple(evidence, Evidence, "evidence"),
            documents=_model_tuple(documents, ContextDocument, "documents"),
        )
    return EvidenceBundle(
        evidence=_model_tuple(_field(output, "evidence", default=()), Evidence, "evidence"),
        documents=_model_tuple(
            _field(output, "documents", "context_documents", default=()),
            ContextDocument,
            "documents",
        ),
        warnings=_string_tuple(_field(output, "warnings", "retrieval_warnings", default=())),
        guardrail_flags=_string_tuple(
            _field(output, "guardrail_flags", "prompt_injection_flags", default=())
        ),
        source_safety_diagnostics=_string_tuple(
            _fields(
                output,
                "source_safety_diagnostics",
                "source_safety",
                "private_url_blocks",
            )
        ),
    )


def _diagnostic_warnings(
    base: EvidenceBundle,
    diagnostics: Any,
    retriever: Any | None,
) -> tuple[str, ...]:
    return _dedupe(
        [
            *base.warnings,
            *_string_tuple(_field(retriever, "warnings", default=())),
            *_string_tuple(_field(diagnostics, "warnings", "retrieval_warnings", default=())),
            *_string_tuple(
                _field(diagnostics, "source_safety_warnings", "source_warnings", default=())
            ),
        ]
    )


def _diagnostic_flags(diagnostics: Any) -> tuple[str, ...]:
    return _string_tuple(
        _field(
            diagnostics,
            "guardrail_flags",
            "prompt_injection_flags",
            "source_safety_flags",
            default=(),
        )
    )


def _diagnostic_source_safety(base: EvidenceBundle, diagnostics: Any) -> tuple[str, ...]:
    return _dedupe(
        [
            *base.source_safety_diagnostics,
            *_string_tuple(
                _fields(
                    diagnostics,
                    "source_safety_diagnostics",
                    "source_safety",
                    "private_url_blocks",
                )
            ),
        ]
    )


def _looks_like_tuple_output(output: Any) -> bool:
    return isinstance(output, tuple) and len(output) == 2


def _field(target: Any, *names: str, default: Any) -> Any:
    if target is None:
        return default
    if isinstance(target, Mapping):
        for name in names:
            if name in target:
                return target[name]
        return default
    for name in names:
        if hasattr(target, name):
            return getattr(target, name)
    return default


def _fields(target: Any, *names: str) -> tuple[Any, ...]:
    values: list[Any] = []
    for name in names:
        value = _field(target, name, default=())
        if value is None:
            continue
        if isinstance(value, (str, Mapping)):
            values.append(value)
        elif isinstance(value, Sequence):
            values.extend(value)
        else:
            values.append(value)
    return tuple(values)


def _model_tuple(value: Any, model_type: type[ModelT], field_name: str) -> tuple[ModelT, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"retrieval {field_name} must be a sequence")
    items = tuple(value)
    models: list[ModelT] = []
    invalid: list[Any] = []
    for item in items:
        if isinstance(item, model_type):
            models.append(cast(ModelT, item))
        elif isinstance(item, Mapping):
            models.append(model_type.model_validate(item))
        else:
            invalid.append(item)
    if invalid:
        raise TypeError(
            f"retrieval {field_name} must contain {model_type.__name__} objects or mappings"
        )
    return tuple(models)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(f"{key}:{val}" for key, val in value.items())
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return (str(value),)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return tuple(deduped)


def _source_safety_guardrail_flags(diagnostics: Sequence[str]) -> tuple[str, ...]:
    flags: list[str] = []
    for item in diagnostics:
        lowered = item.lower()
        if _is_private_url_block(lowered):
            flags.append("source_safety_private_url_blocked")
        elif "unsafe" in lowered or "blocked" in lowered:
            flags.append("unsafe_source")
    return tuple(flags)


def _derived_source_safety_flags(
    diagnostics: Sequence[str],
    explicit_guardrail_flags: Sequence[str],
) -> tuple[str, ...]:
    explicit = set(explicit_guardrail_flags)
    return tuple(
        flag
        for flag in _source_safety_guardrail_flags(diagnostics)
        if not (flag == "source_safety_private_url_blocked" and "private_url_blocked" in explicit)
    )


def _is_private_url_block(value: str) -> bool:
    return "blocked" in value and (
        "private" in value
        or "non_public_ip" in value
        or "localhost" in value
        or "127.0.0.1" in value
    )
