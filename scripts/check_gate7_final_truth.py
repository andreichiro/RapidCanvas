#!/usr/bin/env python3
"""Read-only Gate 7 final-truth audit for G7-C submission claims."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


GATE6_MAIN = "4728cc3"
BRANCH = "codex/g7bc-final-integration"
EXPECTED_CASES = 19
EXPECTED_PUBLIC = 10
EXPECTED_SYNTHETIC = 9
EXPECTED_TRUTH = {
    "Search/RAG runtime": "real", "Adaptive retrieval": "real",
    "Eval dataset": "fixture-backed", "GEPA": "real",
    "Provider comparison": "skipped/config-limited", "Image understanding": "partial",
    "MLflow": "real", "Ragas/LLM judge": "skipped/config-limited",
    "Browser/user verification": "partial", "No-write API safety": "real",
    "No-secrets hygiene": "real",
}
ALLOWED_DELTA_PATHS = {
    "README.md", "AGENTS.md", "TRANSLATION_LOG.md", "Makefile",
    "assets/dev_G7_C_WORKSPACE_CONTRACT.json", "assets/dev_G7_BC_WORKSPACE_CONTRACT.json",
    "assets/dev_G7_A_WORKSPACE_CONTRACT.json", "backend/app/deps.py", "backend/app/agent/service.py",
    "docs/current_handoff.md", "docs/requirements_matrix.md", "docs/reviews/gate7_final_review.md",
    "scripts/assert_dev_G7_C_execution_context.sh", "scripts/verify_dev_G7_C_isolation.sh",
    "scripts/assert_dev_G7_BC_execution_context.sh", "scripts/verify_dev_G7_BC_isolation.sh",
    "scripts/check_gate7_final_truth.py",
}
ALLOWED_DELTA_PREFIXES = (
    "assets/dev_G7_B_WORKSPACE_CONTRACT.json", "backend/app/agent/log_mlflow.py",
    "backend/app/agent/optimized/", "backend/app/eval/gepa_", "backend/app/eval/optimize.py",
    "backend/app/ml/image.py", "backend/app/agent/adaptive_retrieval.py", "backend/app/agent/query_planning.py",
    "backend/app/tests/integration/test_gate7_", "backend/app/tests/unit/test_agent_",
    "backend/app/tests/unit/test_gate7b_delivery_review.py", "backend/app/tests/unit/test_gepa_optimize.py",
    "backend/app/tests/unit/test_image.py", "scripts/assert_dev_G7_", "scripts/verify_dev_G7_",
)
FORBIDDEN_TRACKED_PREFIXES = (
    ".env", "backend/.env", "frontend/.env", "backend/mlruns/", "mlruns/",
    "backend/qdrant_storage/", "qdrant_storage/", "reports/eval/", "reports/provider_comparison",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    cases = load_json(root / "eval/posts.yaml")
    final_review = read(root / "docs/reviews/gate7_final_review.md")
    handoff = read(root / "docs/current_handoff.md")
    readme = read(root / "README.md")
    agents = read(root / "AGENTS.md")
    matrix = read(root / "docs/requirements_matrix.md")
    translation_log = read(root / "TRANSLATION_LOG.md")

    check_git_scope(root, errors)
    check_eval_truth(cases, root, errors)
    check_gepa_truth(root, errors)
    check_runtime_truth(root, errors)
    check_final_review(final_review, errors)
    check_docs(readme, handoff, matrix, translation_log, agents, errors)
    check_generated_artifact_hygiene(root, errors)

    print(json.dumps({"errors": errors, "checked": "gate7_final_truth"}, indent=2))
    return 1 if errors else 0


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read(path))


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("git", *args), cwd=root, text=True, capture_output=True)


def need(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def check_git_scope(root: Path, errors: list[str]) -> None:
    need(git(root, "diff", "--quiet").returncode == 0, errors, "unstaged tracked changes present")
    need(git(root, "diff", "--cached", "--quiet").returncode == 0, errors, "staged changes present")
    ancestry = git(root, "merge-base", "--is-ancestor", GATE6_MAIN, "HEAD")
    need(ancestry.returncode == 0, errors, f"{GATE6_MAIN} is not an ancestor of HEAD")
    changed = set(git(root, "diff", "--name-only", f"{GATE6_MAIN}..HEAD").stdout.splitlines())
    disallowed = sorted(path for path in changed if not allowed_delta_path(path))
    need(not disallowed, errors, f"G7-C delta touches out-of-scope paths: {disallowed}")
    remote = git(root, "rev-parse", "--verify", f"origin/{BRANCH}")
    need(remote.returncode == 0, errors, f"origin/{BRANCH} is missing")
    if remote.returncode == 0:
        head = git(root, "rev-parse", "HEAD")
        need(remote.stdout == head.stdout, errors, f"origin/{BRANCH} is not at HEAD")


def check_eval_truth(cases: list[dict[str, Any]], root: Path, errors: list[str]) -> None:
    public = [case for case in cases if case.get("provenance") == "fixture_backed_public"]
    synthetic = [case for case in cases if case.get("provenance") == "synthetic_fixture"]
    need(len(cases) == EXPECTED_CASES, errors, f"expected {EXPECTED_CASES} eval cases")
    need(len(public) == EXPECTED_PUBLIC, errors, f"expected {EXPECTED_PUBLIC} public fixtures")
    need(len(synthetic) == EXPECTED_SYNTHETIC, errors, f"expected {EXPECTED_SYNTHETIC} synthetic fixtures")
    need(not any("example.com" in case["url"] for case in public), errors, "public fixture uses example.com")
    summary_path = root / "reports/eval/summary.json"
    if summary_path.exists():
        summary = load_json(summary_path)
        expected_values: dict[str, Any] = {
            "case_count": 19.0,
            "cached_case_count": 19.0,
            "public_bluesky_fixture_case_count": 10.0,
            "synthetic_fixture_case_count": 9.0,
            "api_network_calls_allowed": False,
            "model_judge_calls_allowed": False,
            "ragas_status": "skipped",
            "dspy_judge_status": "skipped",
            "mlflow_status": "not_run_by_make_eval",
        }
        for key, expected in expected_values.items():
            need(summary.get(key) == expected, errors, f"summary {key}={summary.get(key)!r}")


def check_gepa_truth(root: Path, errors: list[str]) -> None:
    payload = load_json(root / "backend/app/agent/optimized/program.json")
    need(payload.get("mode") == "real", errors, "optimized program is not real metadata")
    bridge = payload.get("dataset_bridge", {})
    need(isinstance(bridge, dict), errors, "dataset_bridge is not an object")
    need(bridge.get("case_count") == 19, errors, "GEPA bridge does not cover 19 cases")
    compile_info = payload.get("gepa_compile", {})
    need(isinstance(compile_info, dict), errors, "gepa_compile is not an object")
    need(compile_info.get("executed") is True, errors, "GEPA compile should be marked executed")
    need(compile_info.get("compiled_program_path") == "program_compiled", errors, "compiled program path drift")
    compiled = root / "backend/app/agent/optimized/program_compiled"
    need((compiled / "metadata.json").is_file(), errors, "compiled metadata missing")
    need((compiled / "program.pkl").is_file(), errors, "compiled program pickle missing")


def check_runtime_truth(root: Path, errors: list[str]) -> None:
    deps = read(root / "backend/app/deps.py")
    service = read(root / "backend/app/agent/service.py")
    gate5_marker = "gate5_service = _build_gate5_explainer"
    fallback_marker = "retriever or ThreadContextEvidenceRetriever()"
    need("RetrievalEvidenceRetriever" in deps, errors, "deps.py does not reference retrieval adapter")
    need(gate5_marker in deps, errors, "deps.py does not attempt Gate 5 explainer")
    need(fallback_marker in deps, errors, "deps.py missing thread-context fallback marker")
    if gate5_marker in deps and fallback_marker in deps:
        need(deps.index(gate5_marker) < deps.index(fallback_marker), errors, "thread fallback appears before Gate 5 path")
    need("class ThreadContextEvidenceRetriever" in service, errors, "thread-context fallback missing")
    need("should_run_adaptive_round" in service, errors, "adaptive retrieval hook missing")
    need("adaptive_retrieval_round_2:" in service, errors, "adaptive trace warning missing")
    need(
        "search_rag_not_connected_using_thread_context_evidence" in service,
        errors,
        "thread-context fallback warning missing",
    )


def check_final_review(final_review: str, errors: list[str]) -> None:
    normalized_review = normalize_ws(final_review)
    for item, classification in EXPECTED_TRUTH.items():
        row_prefix = f"| {item} | {classification} |"
        need(row_prefix in final_review, errors, f"truth table missing {item}={classification}")
    required_phrases = [
        "one-shot",
        "bounded adaptive retrieval is integrated",
        "forced live adaptive smoke",
        "real compiled saved DSPy program",
        "mode=real",
        "Live vision was not run",
        "no Anthropic/Gemini/Ollama live comparison",
        "not a hosted experiment workflow",
        "did not run provider-backed judges",
        "G7-C did not run new browser-use verification",
        "This is real where integrated, cached where reproducibility matters",
    ]
    for phrase in required_phrases:
        need(phrase in normalized_review, errors, f"final review missing phrase: {phrase}")


def check_docs(
    readme: str,
    handoff: str,
    matrix: str,
    translation_log: str,
    agents: str,
    errors: list[str],
) -> None:
    doc_requirements = {
        "README.md": [
            "one-shot Search/RAG",
            "capped adaptive retrieval is enabled",
            "real compiled saved DSPy program",
            "Live vision was not run",
            "not a live multi-provider benchmark",
            "docs/reviews/gate7_final_review.md",
        ],
        "docs/current_handoff.md": [
            "one-shot integrated route", "codex/g7bc-final-integration", "3a79056", "fc4dff4",
            "Capped adaptive retrieval is enabled", "real compiled metadata",
            "Live vision was not run", "no live Anthropic/Gemini/Ollama benchmark ran",
            "G7-C did not run a fresh browser-use pass",
        ],
        "docs/requirements_matrix.md": [
            "one-shot plus capped adaptive runtime status",
            "mode=real",
            "compiled saved DSPy program",
            "no fresh Gate 7 browser-use pass",
            "live vision",
            "no live provider comparison report was generated",
        ],
        "TRANSLATION_LOG.md": [
            "Gate 7 Search/RAG and adaptive retrieval truth", "Gate 7 G7-B/G7-C integration",
            "Gate 7 G7-A runtime merge",
            "Gate 7 B/C integration isolation", "Gate 7 image understanding truth",
            "Gate 7 provider comparison truth", "Gate 7 MLflow/Ragas/judge status",
            "Gate 7 pasted OpenAI key handling", "Gate 7 G7-B branch handoff",
        ],
        "AGENTS.md": [
            "Gate 7 final A/B/C integration", "make gate7-final-truth-audit",
            "scripts/verify_dev_G7_BC_isolation.sh", "capped adaptive retrieval is enabled",
            "real compiled saved DSPy program", "not a full UI vision",
        ],
    }
    documents = {
        "README.md": readme,
        "docs/current_handoff.md": handoff,
        "docs/requirements_matrix.md": matrix,
        "TRANSLATION_LOG.md": translation_log,
        "AGENTS.md": agents,
    }
    for file_name, phrases in doc_requirements.items():
        text = normalize_ws(documents[file_name])
        for phrase in phrases:
            need(phrase in text, errors, f"{file_name} missing: {phrase}")

    check_matrix_status(matrix, errors)
    check_no_overclaim_phrases(readme, handoff, matrix, translation_log, agents, errors)


def check_matrix_status(matrix: str, errors: list[str]) -> None:
    rows = requirement_rows(matrix)
    need(row_status(rows, "R032") == "reserved", errors, "R032 must remain reserved")
    need(row_status(rows, "R033") == "reserved", errors, "R033 must remain reserved")
    need(row_status(rows, "R026") == "implemented", errors, "R026 status drift")
    need("mode=real" in row_text(rows, "R026"), errors, "R026 does not record real GEPA")
    need("capped adaptive" in row_text(rows, "R013"), errors, "R013 missing adaptive evidence")
    need("no fresh Gate 7 browser-use pass" in row_text(rows, "R008"), errors, "R008 overclaims browser verification")
    need("no live provider comparison report was generated" in row_text(rows, "R039"), errors, "R039 overclaims provider report")


def check_no_overclaim_phrases(
    readme: str,
    handoff: str,
    matrix: str,
    translation_log: str,
    agents: str,
    errors: list[str],
) -> None:
    overclaim_terms = [
        "unbounded adaptive retrieval",
        "searches until confidence is high",
        "live vision ran",
        "live multi-provider benchmark ran",
        "provider-backed judges ran in G7-C",
    ]
    combined = "\n".join((readme, handoff, matrix, agents, final_truth_only(translation_log))).lower()
    for term in overclaim_terms:
        need(term not in combined, errors, f"overclaim phrase present: {term}")


def requirement_rows(matrix: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in matrix.splitlines():
        if not line.startswith("| R"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells:
            rows[cells[0]] = cells
    return rows


def allowed_delta_path(path: str) -> bool:
    return path in ALLOWED_DELTA_PATHS or any(path.startswith(prefix) for prefix in ALLOWED_DELTA_PREFIXES)


def row_status(rows: dict[str, list[str]], row_id: str) -> str | None:
    row = rows.get(row_id)
    return row[-1].strip().lower() if row else None


def row_text(rows: dict[str, list[str]], row_id: str) -> str:
    return " | ".join(rows.get(row_id, ()))


def final_truth_only(translation_log: str) -> str:
    return "\n".join(line for line in translation_log.splitlines() if "Gate 7" in line)


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def check_generated_artifact_hygiene(root: Path, errors: list[str]) -> None:
    tracked = git(root, "ls-files", *FORBIDDEN_TRACKED_PREFIXES).stdout.splitlines()
    need(not tracked, errors, f"forbidden generated/secret paths tracked: {tracked}")
    for target in (
        ".env", "backend/.env", "backend/mlruns/run", "mlruns/run",
        "backend/qdrant_storage/cache", "reports/eval/summary.json", "reports/provider_comparison.md",
    ):
        ignored = git(root, "check-ignore", "-q", target)
        need(ignored.returncode == 0, errors, f"not ignored: {target}")

if __name__ == "__main__":
    sys.exit(main())
