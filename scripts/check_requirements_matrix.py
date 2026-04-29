"""Validate the Gate 1 requirement matrix.

The matrix is intentionally strict so later gates cannot silently drop a
requirement, test mapping, eval artifact, or documentation mapping.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs" / "requirements_matrix.md"

EXPECTED_HEADERS = [
    "ID",
    "Requirement",
    "Source",
    "Implementation files",
    "Tests / gates",
    "Eval artifact",
    "Docs",
    "Status",
]

REQUIRED_IDS = {f"R{index:03d}" for index in range(1, 45)}
VALID_STATUSES = {"implemented", "planned", "reserved"}
EMPTY_MARKERS = {"", "-", "n/a", "na", "none", "missing"}
FORBIDDEN_CELL_MARKERS = {"unmapped"}


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [cell.strip() for cell in cells]


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    chars = set(stripped.replace("|", "").replace(" ", ""))
    return bool(chars) and chars <= {"-", ":"}


def _read_table() -> tuple[list[str], list[list[str]]]:
    if not MATRIX_PATH.exists():
        raise SystemExit(f"Requirement matrix not found: {MATRIX_PATH}")

    lines = MATRIX_PATH.read_text(encoding="utf-8").splitlines()
    table_lines = [line for line in lines if line.strip().startswith("|")]
    if len(table_lines) < 3:
        raise SystemExit("Requirement matrix table is absent or too small.")

    headers = _split_row(table_lines[0])
    rows = [_split_row(line) for line in table_lines[2:] if not _is_separator(line)]
    return headers, rows


def _validate_headers(headers: list[str]) -> None:
    if headers != EXPECTED_HEADERS:
        raise SystemExit(
            "Requirement matrix headers changed. Expected "
            f"{EXPECTED_HEADERS}, got {headers}."
        )


def _validate_row_shape(rows: list[list[str]]) -> None:
    for row_number, row in enumerate(rows, start=1):
        if len(row) != len(EXPECTED_HEADERS):
            raise SystemExit(
                f"Requirement matrix row {row_number} has {len(row)} cells; "
                f"expected {len(EXPECTED_HEADERS)}."
            )


def _validate_required_ids(rows: list[list[str]]) -> None:
    seen_ids = [row[0] for row in rows]
    seen_set = set(seen_ids)
    duplicate_ids = sorted({row_id for row_id in seen_ids if seen_ids.count(row_id) > 1})
    if duplicate_ids:
        raise SystemExit(f"Duplicate requirement IDs: {', '.join(duplicate_ids)}")

    absent = sorted(REQUIRED_IDS - seen_set)
    unexpected = sorted(seen_set - REQUIRED_IDS)
    if absent or unexpected:
        details = []
        if absent:
            details.append(f"absent IDs: {', '.join(absent)}")
        if unexpected:
            details.append(f"unexpected IDs: {', '.join(unexpected)}")
        raise SystemExit("; ".join(details))


def _validate_cell_content(rows: list[list[str]]) -> None:
    for row in rows:
        row_id = row[0]
        for header, cell in zip(EXPECTED_HEADERS, row, strict=True):
            normalized = cell.strip().lower()
            if normalized in EMPTY_MARKERS:
                raise SystemExit(f"{row_id} has an empty mapping in column {header}.")
            for marker in FORBIDDEN_CELL_MARKERS:
                if marker in normalized:
                    raise SystemExit(
                        f"{row_id} contains forbidden marker {marker!r} "
                        f"in column {header}."
                    )


def _validate_statuses(rows: list[list[str]]) -> None:
    for row in rows:
        row_id = row[0]
        status = row[-1].strip().lower()
        if status not in VALID_STATUSES:
            raise SystemExit(
                f"{row_id} has invalid status {status!r}; "
                f"expected one of {sorted(VALID_STATUSES)}."
            )


def main() -> None:
    headers, rows = _read_table()
    _validate_headers(headers)
    _validate_row_shape(rows)
    _validate_required_ids(rows)
    _validate_cell_content(rows)
    _validate_statuses(rows)
    print(f"Requirements matrix review passed with {len(rows)} mapped rows.")


if __name__ == "__main__":
    main()
