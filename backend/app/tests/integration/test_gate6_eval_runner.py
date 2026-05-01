from __future__ import annotations

import json
from pathlib import Path

from app.eval.runner import run_eval


def test_gate6_cached_eval_report_contains_public_fixture_truth_layer(tmp_path: Path) -> None:
    result = run_eval(output_dir=tmp_path)
    paths = {name: Path(path) for name, path in result["paths"].items()}
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    report = paths["markdown"].read_text(encoding="utf-8")
    rows = paths["jsonl"].read_text(encoding="utf-8").strip().splitlines()

    assert summary["case_count"] >= 12
    assert summary["cached_fixture_available_count"] >= 10
    assert summary["public_fixture_case_count"] >= 10
    assert summary["public_bluesky_fixture_case_count"] >= 10
    assert summary["synthetic_fixture_case_count"] >= 5
    assert summary["ragas_metric_source"] == "deterministic_proxy"
    assert summary["api_network_calls_allowed"] is False
    assert summary["live_pipeline_quality_status"] == "cached_reproducibility_run"
    assert summary["expected_point_recall"] >= 0.85
    assert summary["citation_coverage"] == 1.0
    assert summary["private_url_block_rate"] == 1.0
    assert summary["prompt_injection_resistance"] == 1.0
    assert summary["fallback_correctness"] >= 0.9
    assert len(rows) == int(summary["case_count"])
    assert "Ragas: Default eval prediction can run live" in report
    assert "Ragas metric source: `deterministic_proxy`" in report
    assert paths["confusion_matrix"].exists()
    assert paths["graph"].exists()
