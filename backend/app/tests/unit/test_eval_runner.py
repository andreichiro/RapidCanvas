from __future__ import annotations

from pathlib import Path

from app.eval.runner import run_cached_eval


def test_cached_eval_runner_writes_reports(tmp_path: Path) -> None:
    result = run_cached_eval(output_dir=tmp_path)
    paths = {name: Path(path) for name, path in result["paths"].items()}

    assert result["summary"]["case_count"] >= 12
    assert paths["jsonl"].exists()
    assert paths["markdown"].exists()
    assert paths["confusion_matrix"].exists()
    assert paths["graph"].exists()
    assert "prompt_injection_resistance" in paths["markdown"].read_text(encoding="utf-8")

