"""Validate the staff line review matrix covers the production surface."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs" / "reviews" / "staff_line_review_matrix.md"
FORBIDDEN_STATUS_RE = re.compile(r"\b(planned-only|unreviewed)\b", re.IGNORECASE)
REQUIRED_COLUMNS = ("file", "responsibility", "issue found", "fix planned", "tests", "status")
REQUIRED_EXPLICIT_FILES = {
    "backend/app/ml/retrieval_service.py",
    "backend/app/ml/vector_store.py",
    "backend/app/ml/rag_runtime.py",
    "backend/app/clients/bsky.py",
    "backend/app/clients/search.py",
    "backend/app/clients/fetcher.py",
    "backend/app/ml/image.py",
    "backend/app/eval/provider_comparison.py",
    "scripts/write_live_quality_review.py",
    "backend/app/agent/finalize.py",
    "backend/app/agent/program.py",
    "backend/app/deps.py",
    "frontend/src/App.tsx",
    "frontend/src/api/client.ts",
    "docker-compose.yml",
    ".github/workflows/deep-review.yml",
}


@dataclass(frozen=True)
class MatrixRow:
    line_number: int
    file_path: str
    cells: list[str]
    errors: list[str]


def scoped_production_files(root: Path = ROOT) -> set[str]:
    """Return production files that must have staff-review rows."""

    files: set[str] = set()
    _add_tree(files, root, "backend/app", exclude=_backend_excluded)
    _add_tree(files, root, "frontend/src", exclude=_frontend_excluded)
    _add_tree(files, root, "scripts")
    _add_tree(files, root, "eval")
    _add_tree(files, root, "docs", suffixes={".md"})
    _add_tree(files, root, ".github/workflows", suffixes={".yml", ".yaml"})
    for path in (
        "AGENTS.md",
        "Makefile",
        "README.md",
        "TRANSLATION_LOG.md",
        "backend/Dockerfile",
        "docker-compose.yml",
        "frontend/Dockerfile",
    ):
        if (root / path).exists():
            files.add(path)
    return files


def parse_matrix(path: Path = MATRIX_PATH) -> tuple[dict[str, list[str]], list[str]]:
    """Parse matrix rows into file -> cells and return structural errors."""

    rows: dict[str, list[str]] = {}
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if FORBIDDEN_STATUS_RE.search(text):
        errors.append("matrix contains forbidden status planned-only/unreviewed")
    for line_number, line in enumerate(text.splitlines(), start=1):
        row = _parse_matrix_row(line_number, line)
        if row is None:
            continue
        errors.extend(row.errors)
        if not row.file_path:
            continue
        if row.file_path in rows:
            errors.append(f"line {row.line_number}: duplicate row for {row.file_path}")
        rows[row.file_path] = row.cells
    return rows, errors


def validate_matrix(
    *,
    root: Path = ROOT,
    matrix_path: Path = MATRIX_PATH,
) -> list[str]:
    """Return validation errors for staff review coverage."""

    rows, errors = parse_matrix(matrix_path)
    covered = set(rows)
    expected = scoped_production_files(root)
    missing = sorted(expected - covered)
    missing_explicit = sorted(REQUIRED_EXPLICIT_FILES - covered)
    if missing:
        errors.append("missing production review rows: " + ", ".join(missing))
    if missing_explicit:
        errors.append("missing required explicit review rows: " + ", ".join(missing_explicit))
    return errors


def _add_tree(
    files: set[str],
    root: Path,
    relative: str,
    *,
    suffixes: set[str] | None = None,
    exclude: Callable[[str], bool] | None = None,
) -> None:
    base = root / relative
    if not base.exists():
        return
    for path in base.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if _path_in_scope(path, rel, suffixes=suffixes, exclude=exclude):
            files.add(rel)


def _parse_matrix_row(line_number: int, line: str) -> MatrixRow | None:
    if not line.startswith("| "):
        return None
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    first_cell = cells[0] if cells else ""
    if first_cell == "file":
        return _parse_matrix_header(line_number, cells)
    if first_cell == "---":
        return None
    if not first_cell.startswith("`"):
        return None
    if len(cells) != len(REQUIRED_COLUMNS):
        error = f"line {line_number}: expected {len(REQUIRED_COLUMNS)} columns"
        return MatrixRow(line_number, "", [], [error])
    file_path = first_cell.strip("`")
    errors = _matrix_cell_errors(line_number, file_path, cells)
    return MatrixRow(line_number, file_path, cells, errors)


def _parse_matrix_header(line_number: int, cells: list[str]) -> MatrixRow | None:
    if tuple(cells) == REQUIRED_COLUMNS:
        return None
    return MatrixRow(line_number, "", [], [f"line {line_number}: unexpected matrix header"])


def _matrix_cell_errors(line_number: int, file_path: str, cells: list[str]) -> list[str]:
    errors: list[str] = []
    if not file_path:
        errors.append(f"line {line_number}: empty file cell")
    if any(not cell for cell in cells[1:]):
        errors.append(f"line {line_number}: empty review cell for {file_path}")
    return errors


def _path_in_scope(
    path: Path,
    relative: str,
    *,
    suffixes: set[str] | None,
    exclude: Callable[[str], bool] | None,
) -> bool:
    if not path.is_file():
        return False
    if "__pycache__" in relative or path.name == ".gitkeep":
        return False
    if suffixes is not None and path.suffix not in suffixes:
        return False
    if exclude is None:
        return True
    return not exclude(relative)


def _backend_excluded(relative: str) -> bool:
    return "/tests/" in relative or relative.endswith(".pyc")


def _frontend_excluded(relative: str) -> bool:
    return (
        "/test/" in relative
        or relative.endswith(".test.ts")
        or relative.endswith(".test.tsx")
        or relative.endswith("/setupTests.ts")
    )


def main() -> int:
    errors = validate_matrix()
    if errors:
        print("Staff review matrix validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Staff review matrix validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
