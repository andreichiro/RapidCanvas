from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from app.agent.eval_support import ProviderQualityMetadata, RetrievalQualitySignals
from app.agent.quality_trace import AgentQualityTrace, GuardrailQualityOutput
from app.schemas.api import Trace

ROOT = Path(__file__).resolve().parents[3]
DEV_C_FILES = [
    ROOT / "app/agent/eval_support.py",
    ROOT / "app/agent/finalize.py",
    ROOT / "app/agent/judge_signatures.py",
    ROOT / "app/agent/quality_trace.py",
    ROOT / "app/agent/program.py",
    ROOT / "app/agent/service.py",
    ROOT / "app/ops/mlflow.py",
]
FORBIDDEN_IMPORT_PREFIXES = (
    "app.api",
    "app.clients",
    "app.deps",
    "app.ml",
    "app.eval.dataset",
    "app.eval.judge",
    "app.eval.metrics",
    "app.eval.report",
    "app.eval.runner",
)


def test_gate6_dev_c_public_trace_schema_stays_frozen() -> None:
    assert set(Trace.model_fields) == {
        "category",
        "queries",
        "warnings",
        "latency_ms",
        "trust_score",
        "fallback_mode",
        "guardrail_flags",
        "adapter_mode",
        "adapter_notes",
    }


def test_gate6_dev_c_quality_contract_exposes_required_fields() -> None:
    assert set(AgentQualityTrace.model_fields) >= {
        "schema_version",
        "category",
        "query_plan_summary",
        "bullet_evidence",
        "validation_issues",
        "guardrails",
        "provider",
        "retrieval",
        "trace_events",
        "chain_of_thought_exposed",
        "hidden_prompts_exposed",
    }
    assert set(GuardrailQualityOutput.model_fields) >= {
        "unsupported_claim_indicators",
        "fallback_reasons",
        "abstention_reasons",
        "prompt_injection_resistance_signals",
        "source_support_validation_status",
        "unsafe_output_flags",
        "revision_attempted",
        "revision_succeeded",
    }
    assert set(ProviderQualityMetadata.model_fields) >= {
        "requested_provider",
        "selected_provider",
        "provider_model",
        "provider_fallback_reason",
        "latency_ms",
        "cost_metadata",
    }
    assert set(RetrievalQualitySignals.model_fields) >= {
        "retrieval_scores",
        "source_diversity",
        "sanitizer_warnings",
        "prompt_injection_flags",
        "private_url_blocks",
        "pending_fields",
    }


def test_gate6_dev_c_quality_modules_keep_lane_boundaries() -> None:
    violations: list[str] = []
    for path in DEV_C_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            imported = _imported_module(node)
            if imported and imported.startswith(FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")

    assert violations == []


def test_gate6_quality_fixture_is_stable_serializable_and_secret_free() -> None:
    fixture_path = ROOT / "app/tests/fixtures/gate6_agent/quality_trace_fixture.json"
    payload = json.loads(fixture_path.read_text())
    AgentQualityTrace.model_validate(payload)

    serialized = json.dumps(payload, sort_keys=True).lower()
    assert payload["chain_of_thought_exposed"] is False
    assert payload["hidden_prompts_exposed"] is False
    assert not re.search(r"sk-[a-z0-9_-]{8,}", serialized)
    assert "secret" not in serialized
    assert "system prompt" not in serialized
    assert "developer message" not in serialized


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.ImportFrom):
        return node.module
    if isinstance(node, ast.Import):
        return node.names[0].name if node.names else None
    return None
