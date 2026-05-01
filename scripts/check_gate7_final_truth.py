#!/usr/bin/env python3
"""Read-only Gate 7 final-truth audit.

This is intentionally narrower than `make deep-review`: it checks that the final
submission documents do not overclaim live/adaptive/optimized/bonus behavior and
that G7-C only changed allowed truth-layer files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


GATE6_MAIN = "4728cc3"
EXPECTED_CASES = 19
EXPECTED_PUBLIC = 10
EXPECTED_SYNTHETIC = 9
EXPECTED_TRUTH = {
    "Search/RAG runtime": "real",
    "Adaptive retrieval": "reserved",
    "Eval dataset": "fixture-backed",
    "GEPA": "dry-run",
    "Provider comparison": "skipped/config-limited",
    "Image understanding": "partial",
    "MLflow": "real",
    "Ragas/LLM judge": "skipped/config-limited",
    "Browser/user verification": "partial",
    "No-write API safety": "real",
    "No-secrets hygiene": "real",
}
ALLOWED_DELTA_PATHS = {
    "README.md",
    "TRANSLATION_LOG.md",
    "Makefile",
    "assets/dev_G7_C_WORKSPACE_CONTRACT.json",
    "docs/current_handoff.md",
    "docs/requirements_matrix.md",
    "docs/reviews/gate7_final_review.md",
    "scripts/assert_dev_G7_C_execution_context.sh",
    "scripts/check_gate7_final_truth.py",
    "scripts/verify_dev_G7_C_isolation.sh",
}
FORBIDDEN_TRACKED_PREFIXES = (
    ".env",
    "backend/.env",
    "frontend/.env",
    "backend/mlruns/",
    "mlruns/",
    "backend/qdrant_storage/",
    "qdrant_storage/",
    "reports/eval/",
    "reports/provider_comparison",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    cases = load_json(root / "eval/posts.yaml")
    final_review = read(root / "docs/reviews/gate7_final_review.md")
    handoff = read(root / "docs/current_handoff.md")
    readme = read(root / "README.md")
    matrix = read(root / "docs/requirements_matrix.md")
    translation_log = read(root / "TRANSLATION_LOG.md")

    check_git_scope(root, errors)
    check_eval_truth(cases, root, errors)
    check_gepa_truth(root, errors)
    check_final_review(final_review, errors)
    check_docs(readme, handoff, matrix, translation_log, errors)
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
    ancestry = git(root, "merge-base", "--is-ancestor", GATE6_MAIN, "HEAD")
    need(ancestry.returncode == 0, errors, f"{GATE6_MAIN} is not an ancestor of HEAD")
    changed = set(git(root, "diff", "--name-only", f"{GATE6_MAIN}..HEAD").stdout.splitlines())
    disallowed = sorted(changed - ALLOWED_DELTA_PATHS)
    need(not disallowed, errors, f"G7-C delta touches out-of-scope paths: {disallowed}")


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
    need(payload.get("mode") == "dry_run", errors, "optimized program is not dry-run metadata")
    compile_info = payload.get("gepa_compile", {})
    need(isinstance(compile_info, dict), errors, "gepa_compile is not an object")
    need(compile_info.get("executed") is False, errors, "GEPA compile should not be marked executed")
    need("compiled_program_path" not in compile_info, errors, "dry-run metadata points to compiled program")


def check_final_review(final_review: str, errors: list[str]) -> None:
    normalized_review = normalize_ws(final_review)
    for item, classification in EXPECTED_TRUTH.items():
        row_prefix = f"| {item} | {classification} |"
        need(row_prefix in final_review, errors, f"truth table missing {item}={classification}")
    required_phrases = [
        "one-shot",
        "adaptive retrieval is not implemented",
        "dry-run metadata",
        "No real compiled DSPy program",
        "Live vision was not run",
        "no Anthropic/Gemini/Ollama live comparison",
        "not a hosted experiment workflow",
        "did not run provider-backed judges",
        "G7-C did not run new browser-use verification",
        "This review does not count uncommitted G7-A or G7-B clone changes",
        "This is real where integrated, cached where reproducibility matters",
    ]
    for phrase in required_phrases:
        need(phrase in normalized_review, errors, f"final review missing phrase: {phrase}")


def check_docs(
    readme: str,
    handoff: str,
    matrix: str,
    translation_log: str,
    errors: list[str],
) -> None:
    doc_requirements = {
        "README.md": [
            "one-shot Search/RAG",
            "adaptive retrieval is reserved",
            "dry-run metadata",
            "not live vision",
            "not a live multi-provider benchmark",
            "docs/reviews/gate7_final_review.md",
        ],
        "docs/current_handoff.md": [
            "one-shot integrated route",
            "Adaptive retrieval is reserved",
            "dry-run metadata",
            "Live vision was not run",
            "no live Anthropic/Gemini/Ollama benchmark ran",
        ],
        "docs/requirements_matrix.md": [
            "one-shot, non-adaptive runtime status",
            "dry-run GEPA metadata",
            "no real compiled program is included by default",
            "live vision",
            "no `reports/provider_comparison.md` live multi-provider benchmark",
        ],
        "TRANSLATION_LOG.md": [
            "Gate 7 Search/RAG and adaptive retrieval truth",
            "Gate 7 GEPA dataset bridge and real compile status",
            "Gate 7 image understanding truth",
            "Gate 7 provider comparison truth",
            "Gate 7 MLflow/Ragas/judge status",
            "Gate 7 pasted OpenAI key handling",
        ],
    }
    documents = {
        "README.md": readme,
        "docs/current_handoff.md": handoff,
        "docs/requirements_matrix.md": matrix,
        "TRANSLATION_LOG.md": translation_log,
    }
    for file_name, phrases in doc_requirements.items():
        text = documents[file_name]
        for phrase in phrases:
            need(phrase in text, errors, f"{file_name} missing: {phrase}")

    check_matrix_status(matrix, errors)
    check_no_overclaim_phrases(readme, handoff, matrix, translation_log, errors)


def check_matrix_status(matrix: str, errors: list[str]) -> None:
    rows = requirement_rows(matrix)
    need(row_status(rows, "R032") == "reserved", errors, "R032 must remain reserved")
    need(row_status(rows, "R033") == "reserved", errors, "R033 must remain reserved")
    need(row_status(rows, "R026") == "implemented", errors, "R026 status drift")


def check_no_overclaim_phrases(
    readme: str,
    handoff: str,
    matrix: str,
    translation_log: str,
    errors: list[str],
) -> None:
    overclaim_terms = [
        "adaptive retrieval is implemented",
        "live vision ran",
        "live multi-provider benchmark ran",
        "real compiled optimized program was produced",
        "provider-backed judges ran in G7-C",
    ]
    combined = "\n".join((readme, handoff, matrix, final_truth_only(translation_log))).lower()
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


def row_status(rows: dict[str, list[str]], row_id: str) -> str | None:
    row = rows.get(row_id)
    return row[-1].strip().lower() if row else None


def final_truth_only(translation_log: str) -> str:
    return "\n".join(line for line in translation_log.splitlines() if "Gate 7" in line)


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def check_generated_artifact_hygiene(root: Path, errors: list[str]) -> None:
    tracked = git(root, "ls-files", *FORBIDDEN_TRACKED_PREFIXES).stdout.splitlines()
    need(not tracked, errors, f"forbidden generated/secret paths tracked: {tracked}")
    for target in (
        ".env",
        "backend/.env",
        "backend/mlruns/run",
        "mlruns/run",
        "backend/qdrant_storage/cache",
        "reports/eval/summary.json",
        "reports/provider_comparison.md",
    ):
        ignored = git(root, "check-ignore", "-q", target)
        need(ignored.returncode == 0, errors, f"not ignored: {target}")


if __name__ == "__main__":
    sys.exit(main())
