"""Program loading and optional DSPy configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from app.agent.program import BlueskyExplainer
from app.agent.runner import DspySignatureRunner, HeuristicSignatureRunner
from app.agent.signatures import dspy_is_available
from app.config import Settings, get_settings

OPTIMIZED_PROGRAM_PATH = Path(__file__).parent / "optimized" / "program.json"


@dataclass(frozen=True)
class ProgramLoadResult:
    """Loaded program and diagnostics for API/eval integration."""

    program: BlueskyExplainer
    optimized_path: Path | None
    warnings: list[str]


def load_program(
    settings: Settings | None = None,
    *,
    optimized_path: Path = OPTIMIZED_PROGRAM_PATH,
    prefer_dspy: bool = True,
) -> ProgramLoadResult:
    """Load optimized config when present and select a DSPy-capable runner."""

    active_settings = settings or get_settings()
    warnings: list[str] = []
    optimized_config = _load_optimized_config(optimized_path, warnings)

    runner: DspySignatureRunner | HeuristicSignatureRunner
    if prefer_dspy and active_settings.openai_api_key is not None and dspy_is_available():
        warnings.extend(configure_dspy(active_settings))
        runner = DspySignatureRunner()
    else:
        runner = HeuristicSignatureRunner()
        warnings.append("dspy_runner_unavailable_using_deterministic_dev")

    program = BlueskyExplainer(runner=runner, optimized_config=optimized_config)
    return ProgramLoadResult(
        program=program,
        optimized_path=optimized_path if optimized_config else None,
        warnings=warnings,
    )


def configure_dspy(settings: Settings) -> list[str]:
    """Configure DSPy with the selected model when the dependency is installed."""

    if not dspy_is_available():
        return ["dspy_not_installed"]

    dspy = import_module("dspy")
    warnings: list[str] = []
    try:
        dspy.configure(lm=dspy.LM(settings.dspy_model), async_max_workers=4)
    except Exception as exc:  # pragma: no cover - depends on optional provider config.
        warnings.append(f"dspy_config_failed:{exc.__class__.__name__}")
    return warnings


def asyncify_program(program: BlueskyExplainer) -> Any:
    """Return DSPy's async wrapper when available; otherwise the program itself."""

    if not dspy_is_available():
        return program
    dspy = import_module("dspy")
    return dspy.asyncify(program)


def _load_optimized_config(path: Path, warnings: list[str]) -> dict[str, Any]:
    if not path.exists():
        warnings.append("optimized_program_not_found")
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        warnings.append("optimized_program_invalid_json")
        return {}
    if not isinstance(payload, dict):
        warnings.append("optimized_program_invalid_shape")
        return {}
    return payload
