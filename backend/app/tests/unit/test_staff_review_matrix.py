from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_script() -> Any:
    root = Path(__file__).resolve().parents[4]
    script_path = root / "scripts" / "check_staff_review_matrix.py"
    spec = importlib.util.spec_from_file_location("check_staff_review_matrix", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_staff_review_scope_excludes_tests_but_includes_runtime_files() -> None:
    script = _load_script()
    files = script.scoped_production_files()

    assert "backend/app/main.py" in files
    assert "frontend/src/App.tsx" in files
    assert "scripts/write_live_quality_review.py" in files
    assert "docker-compose.yml" in files
    assert "backend/app/tests/unit/test_config.py" not in files
    assert "frontend/src/test/runtime-validation.test.tsx" not in files


def test_staff_review_matrix_reports_missing_production_rows(tmp_path: Path) -> None:
    script = _load_script()
    matrix = tmp_path / "staff_line_review_matrix.md"
    matrix.write_text(
        "\n".join(
            [
                "| file | responsibility | issue found | fix planned | tests | status |",
                "| --- | --- | --- | --- | --- | --- |",
                "| `backend/app/main.py` | app | issue | fix | tests | reviewed |",
            ]
        ),
        encoding="utf-8",
    )

    errors = script.validate_matrix(matrix_path=matrix)

    assert any("missing production review rows" in error for error in errors)
    assert any("frontend/src/App.tsx" in error for error in errors)


def test_staff_review_matrix_rejects_forbidden_status(tmp_path: Path) -> None:
    script = _load_script()
    matrix = tmp_path / "staff_line_review_matrix.md"
    matrix.write_text(
        "\n".join(
            [
                "| file | responsibility | issue found | fix planned | tests | status |",
                "| --- | --- | --- | --- | --- | --- |",
                "| `backend/app/main.py` | app | issue | fix | tests | unreviewed |",
            ]
        ),
        encoding="utf-8",
    )

    rows, errors = script.parse_matrix(matrix)

    assert "backend/app/main.py" in rows
    assert "matrix contains forbidden status planned-only/unreviewed" in errors
