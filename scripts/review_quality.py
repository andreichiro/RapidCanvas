"""Review-quality checks for maintainability and handoff readiness.

The goal is not to replace human review. It catches the easy-to-miss scaffold
regressions that make a project harder to understand, explain, or extend.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "node_modules",
    "mlruns",
}
LOCKFILES = {
    "uv.lock",
    "package-lock.json",
}
MAX_SOURCE_LINES = 320
MAX_DOC_LINES = 320
MAX_FUNCTION_LINES = 60
MAX_BRANCHES_PER_FUNCTION = 8


@dataclass(frozen=True)
class Issue:
    path: Path
    message: str

    def render(self) -> str:
        return f"{self.path.relative_to(ROOT)}: {self.message}"


def is_ignored(path: Path) -> bool:
    return any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def tracked_like_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or is_ignored(path):
            continue
        files.append(path)
    return sorted(files)


def check_required_handoff_files() -> list[Issue]:
    required = [
        ".env.example",
        ".gitignore",
        "AGENTS.md",
        "Makefile",
        "README.md",
        "TRANSLATION_LOG.md",
        "docs/current_handoff.md",
        "docs/deep_review_workflow.md",
        "docs/requirements_matrix.md",
        ".github/workflows/deep-review.yml",
    ]
    return [
        Issue(ROOT / path, "required handoff/review file is missing")
        for path in required
        if not (ROOT / path).exists()
    ]


def check_docs_explain_review_gate() -> list[Issue]:
    issues: list[Issue] = []
    expected_mentions = {
        "README.md": ["make deep-review", "make requirements-review", "Deep Review Workflow", "Gate 1"],
        "AGENTS.md": ["make deep-review", "make requirements-review", "Review Expectations", "Current Gate"],
        "docs/deep_review_workflow.md": [
            "make deep-review",
            "make requirements-review",
            "Manual Review Checklist",
            "Acceptance Rule",
        ],
        "docs/current_handoff.md": ["Gate 2", "R045", "make deep-review", "no-fake-product-behavior"],
        "docs/requirements_matrix.md": ["R001", "R044", "implemented", "planned"],
    }
    for file_name, snippets in expected_mentions.items():
        text = read(file_name)
        for snippet in snippets:
            if snippet not in text:
                issues.append(Issue(ROOT / file_name, f"missing review/handoff snippet: {snippet}"))
    return issues


def check_translation_log_current() -> list[Issue]:
    text = read("TRANSLATION_LOG.md")
    required = [
        "T0 repo safety",
        "deep review workflow",
        "Requirement matrix",
        "andreichiro/RapidCanvas",
    ]
    return [
        Issue(ROOT / "TRANSLATION_LOG.md", f"missing decision log entry: {snippet}")
        for snippet in required
        if snippet not in text
    ]


def check_make_targets() -> list[Issue]:
    text = read("Makefile")
    required_targets = [
        "deep-review:",
        "maintainability-review:",
        "user-smoke:",
        "api-smoke:",
        "frontend-smoke:",
        "check-secrets:",
        "requirements-review:",
    ]
    issues = [
        Issue(ROOT / "Makefile", f"missing required target {target}")
        for target in required_targets
        if target not in text
    ]
    expected_chain = (
        "deep-review: lint test check-secrets config-check frontend-audit frontend-build "
        "extras-dry-run requirements-review clean-generated maintainability-review user-smoke"
    )
    if expected_chain not in text:
        issues.append(Issue(ROOT / "Makefile", "deep-review does not include the full quality/user-smoke chain"))
    return issues


def check_reserved_commands_are_honest() -> list[Issue]:
    text = read("Makefile")
    expected = {
        "eval": "T9 is not implemented yet",
        "optimize": "T10 is not implemented yet",
        "mlflow-log": "T11 is not implemented yet",
    }
    issues: list[Issue] = []
    for target, phrase in expected.items():
        target_block = re.search(rf"^{re.escape(target)}:\n(?:\t.*\n)+", text, flags=re.MULTILINE)
        if not target_block or phrase not in target_block.group(0):
            issues.append(Issue(ROOT / "Makefile", f"{target} must clearly say it is reserved"))
    return issues


def check_file_sizes() -> list[Issue]:
    issues: list[Issue] = []
    for path in tracked_like_files():
        if path.name in LOCKFILES:
            continue
        suffix = path.suffix.lower()
        if suffix not in {".py", ".ts", ".tsx", ".css", ".md", ".toml", ".json", ".yml"}:
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        limit = MAX_DOC_LINES if suffix == ".md" else MAX_SOURCE_LINES
        if line_count > limit:
            issues.append(Issue(path, f"file has {line_count} lines; expected <= {limit} for scaffold readability"))
    return issues


def count_branches(node: ast.AST) -> int:
    branch_nodes = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.ExceptHandler,
        ast.BoolOp,
        ast.IfExp,
        ast.Match,
    )
    return sum(isinstance(child, branch_nodes) for child in ast.walk(node))


def check_python_function_complexity() -> list[Issue]:
    issues: list[Issue] = []
    for path in tracked_like_files():
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.end_lineno is not None:
                length = node.end_lineno - node.lineno + 1
                if length > MAX_FUNCTION_LINES:
                    issues.append(Issue(path, f"{node.name} has {length} lines; expected <= {MAX_FUNCTION_LINES}"))
            branches = count_branches(node)
            if branches > MAX_BRANCHES_PER_FUNCTION:
                issues.append(
                    Issue(path, f"{node.name} has {branches} branch points; expected <= {MAX_BRANCHES_PER_FUNCTION}")
                )
    return issues


def check_no_placeholder_implementation_markers() -> list[Issue]:
    marker_tokens = ["TO" + "DO", "FIX" + "ME", "X" * 3, "Not" + "ImplementedError"]
    marker_pattern = re.compile(
        rf"\b({'|'.join(re.escape(token) for token in marker_tokens)}|pass\s*(#.*)?$)\b",
        re.MULTILINE,
    )
    issues: list[Issue] = []
    for path in tracked_like_files():
        if path.name in LOCKFILES:
            continue
        if path.suffix.lower() not in {".py", ".ts", ".tsx", ".md", ".toml", ".json", ".yml", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        for match in marker_pattern.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            issues.append(Issue(path, f"placeholder marker near line {line_no}: {match.group(0)}"))
    return issues


def check_frontend_user_text_matches_plan() -> list[Issue]:
    text = read("frontend/src/App.tsx")
    required = [
        "Bluesky Contextual Post Explainer",
        "T0 scaffold",
        "URL input",
        "provider selector",
        "citations",
        "trust display",
        "trace panel",
    ]
    return [
        Issue(ROOT / "frontend/src/App.tsx", f"user-visible scaffold text missing: {snippet}")
        for snippet in required
        if snippet not in text
    ]


def check_generated_artifacts_absent() -> list[Issue]:
    generated_names = {"dist", "mlruns", "qdrant_storage"}
    generated_suffixes = {".tsbuildinfo"}
    issues: list[Issue] = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or "node_modules" in path.parts or ".venv" in path.parts:
            continue
        if path.name in generated_names:
            issues.append(Issue(path, "generated artifact directory should not be present after review cleanup"))
        if path.suffix in generated_suffixes:
            issues.append(Issue(path, "generated TypeScript build info should not be present"))
    return issues


def main() -> int:
    checks = [
        check_required_handoff_files,
        check_docs_explain_review_gate,
        check_translation_log_current,
        check_make_targets,
        check_reserved_commands_are_honest,
        check_file_sizes,
        check_python_function_complexity,
        check_no_placeholder_implementation_markers,
        check_frontend_user_text_matches_plan,
        check_generated_artifacts_absent,
    ]
    issues = [issue for check in checks for issue in check()]
    if issues:
        print("Maintainability review failed:")
        for issue in issues:
            print(f"- {issue.render()}")
        return 1
    print("Maintainability review passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
