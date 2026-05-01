"""Program loading and optional DSPy configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from app.agent.dspy_runner import DspySignatureRunner
from app.agent.program import BlueskyExplainer
from app.agent.providers import export_provider_key, resolve_provider
from app.agent.runner import HeuristicSignatureRunner
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
    allow_dspy_without_key: bool = False,
    provider_name: str = "openai",
) -> ProgramLoadResult:
    """Load optimized config when present and select a DSPy-capable runner."""

    active_settings = settings or get_settings()
    warnings: list[str] = []
    optimized_config = _load_optimized_config(optimized_path, warnings)
    provider = resolve_provider(active_settings, provider_name)

    runner: DspySignatureRunner | HeuristicSignatureRunner
    can_use_dspy = provider.selected.configured or allow_dspy_without_key
    if prefer_dspy and can_use_dspy and dspy_is_available():
        warnings.extend(
            configure_dspy(
                active_settings,
                provider_name=provider_name,
                allow_without_key=allow_dspy_without_key,
            )
        )
        optimized_dspy = _load_compiled_dspy_program(optimized_config, optimized_path, warnings)
        runner = DspySignatureRunner(optimized_explain_program=optimized_dspy)
    else:
        runner = HeuristicSignatureRunner()
        warnings.extend(provider.warnings)
        warnings.append("dspy_runner_unavailable_using_deterministic_dev")

    program = BlueskyExplainer(
        runner=runner,
        optimized_config=optimized_config,
        provider_metadata=_provider_metadata(provider),
    )
    return ProgramLoadResult(
        program=program,
        optimized_path=optimized_path if optimized_config else None,
        warnings=warnings,
    )


def _provider_metadata(provider: Any) -> dict[str, Any]:
    warnings = list(getattr(provider, "warnings", ()))
    selected = provider.selected
    return {
        "requested_provider": provider.requested,
        "selected_provider": selected.name,
        "provider_model": selected.model,
        "provider_configured": selected.configured,
        "provider_fallback_reason": "; ".join(warnings) if warnings else selected.skipped_reason,
    }


def configure_dspy(
    settings: Settings,
    *,
    provider_name: str = "openai",
    allow_without_key: bool = False,
) -> list[str]:
    """Configure DSPy with the selected model when the dependency is installed."""

    if not dspy_is_available():
        return ["dspy_not_installed"]

    dspy = import_module("dspy")
    warnings: list[str] = []
    provider = resolve_provider(settings, provider_name)
    warnings.extend(provider.warnings)
    if not provider.selected.configured and not allow_without_key:
        warnings.append(f"dspy_provider_unavailable:{provider.selected.name}")
        return warnings
    try:
        export_provider_key(provider.selected)
        dspy.configure(lm=dspy.LM(provider.selected.model), async_max_workers=4)
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


def _load_compiled_dspy_program(
    config: dict[str, Any],
    metadata_path: Path,
    warnings: list[str],
) -> Any | None:
    compile_config = config.get("gepa_compile", {})
    if not isinstance(compile_config, dict):
        return None
    raw_path = compile_config.get("compiled_program_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    compiled_path = Path(raw_path)
    if not compiled_path.is_absolute():
        compiled_path = metadata_path.parent / compiled_path
    if not compiled_path.exists():
        warnings.append("optimized_dspy_program_missing")
        return None
    try:
        dspy = import_module("dspy")
        program = dspy.load(str(compiled_path), allow_pickle=True)
    except Exception as exc:  # pragma: no cover - depends on saved DSPy runtime shape.
        warnings.append(f"optimized_dspy_program_load_failed:{exc.__class__.__name__}")
        return None
    warnings.append("optimized_dspy_program_loaded")
    return program
