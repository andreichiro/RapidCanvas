"""Report writers for cached evaluation outputs."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def write_reports(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    output_dir: Path,
) -> dict[str, Path]:
    """Write JSONL, Markdown, confusion matrix, SVG graph, and summary JSON."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "jsonl": output_dir / "eval_results.jsonl",
        "markdown": output_dir / "eval_report.md",
        "confusion_matrix": output_dir / "confusion_matrix.csv",
        "graph": output_dir / "metric_bars.svg",
        "summary": output_dir / "summary.json",
    }
    _write_jsonl(paths["jsonl"], rows)
    _write_markdown(paths["markdown"], rows, summary)
    _write_confusion_matrix(paths["confusion_matrix"], rows)
    _write_svg(paths["graph"], summary)
    paths["summary"].write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_markdown(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Cached Eval Report",
        "",
        "This report is generated from committed fixtures and performs no network or model calls.",
        "",
        "## Summary Metrics",
        "",
        "| metric | value |",
        "|---|---:|",
    ]
    for key in sorted(summary):
        value = summary[key]
        rendered = (
            f"{value:.3f}"
            if isinstance(value, (int, float))
            else json.dumps(value, sort_keys=True)
        )
        lines.append(f"| {key} | {rendered} |")
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| case | category | fallback | recall | citations |",
            "|---|---|---|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {case_id} | {category} | {fallback_mode} | {recall:.3f} | {citations:.3f} |".format(
                case_id=row["case_id"],
                category=row["category"],
                fallback_mode=row["fallback_mode"],
                recall=float(row["expected_point_recall"]),
                citations=float(row["citation_coverage"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_confusion_matrix(path: Path, rows: list[dict[str, Any]]) -> None:
    expected_labels = {str(row["category"]) for row in rows}
    predicted_labels = {str(row["predicted_category"]) for row in rows}
    labels = sorted(expected_labels | predicted_labels)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        counts[(str(row["category"]), str(row["predicted_category"]))] += 1

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["expected\\predicted", *labels])
        for expected in labels:
            writer.writerow([expected, *[counts[(expected, predicted)] for predicted in labels]])


def _write_svg(path: Path, summary: dict[str, Any]) -> None:
    selected = {
        "point_recall": summary.get("expected_point_recall", 0.0),
        "citations": summary.get("citation_coverage", 0.0),
        "faithfulness": summary.get("ragas_faithfulness", 0.0),
        "injection": summary.get("prompt_injection_resistance", 0.0),
        "guardrails": summary.get("guardrail_trigger_accuracy", 0.0),
    }
    width = 680
    row_height = 42
    height = 70 + row_height * len(selected)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="32" font-family="Arial" font-size="18" '
        'font-weight="700">Cached Eval Metrics</text>',
    ]
    for index, (label, value) in enumerate(selected.items()):
        y = 62 + index * row_height
        bar_width = int(430 * max(0.0, min(value, 1.0)))
        lines.extend(
            [
                f'<text x="24" y="{y + 18}" font-family="Arial" font-size="13">{label}</text>',
                f'<rect x="180" y="{y}" width="430" height="24" fill="#eef2f7"/>',
                f'<rect x="180" y="{y}" width="{bar_width}" height="24" fill="#2563eb"/>',
                f'<text x="620" y="{y + 18}" font-family="Arial" font-size="13">{value:.2f}</text>',
            ]
        )
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fallback_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count fallback modes for tests and report callers."""

    return dict(Counter(str(row["fallback_mode"]) for row in rows))
