"""Persistence helpers for saved GEPA DSPy programs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def save_compiled_program(compiled: Any, output_path: Path) -> Path:
    """Save a compiled DSPy program next to its metadata file."""

    save = getattr(compiled, "save", None)
    if not callable(save):
        raise RuntimeError("Compiled GEPA program cannot be saved by DSPy.")
    compiled_path = output_path.parent / f"{output_path.stem}_compiled"
    if compiled_path.exists():
        if compiled_path.is_dir():
            shutil.rmtree(compiled_path)
        else:
            compiled_path.unlink()
    compiled_path.parent.mkdir(parents=True, exist_ok=True)
    save(str(compiled_path), save_program=True)
    if not compiled_path.exists():
        raise RuntimeError("DSPy did not create the compiled GEPA program path.")
    return compiled_path


def load_existing_real_program(output_path: Path) -> dict[str, Any] | None:
    """Return existing real GEPA metadata when its compiled path is still present."""

    payload = _read_json_object(output_path)
    if payload is None or payload.get("mode") != "real":
        return None
    compiled_path = _compiled_path_from_payload(payload, output_path)
    if compiled_path is None or not _compiled_program_artifacts_present(compiled_path):
        return None
    return payload


def optimized_program_artifact_status(
    payload: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Return explicit saved-program artifact status for review and MLflow logs."""

    mode = str(payload.get("mode", "unknown"))
    compiled_path = _compiled_path_from_payload(payload, output_path)
    metadata_present = bool(compiled_path and (compiled_path / "metadata.json").is_file())
    program_pickle_present = bool(compiled_path and (compiled_path / "program.pkl").is_file())
    compiled_artifact_present = metadata_present and program_pickle_present
    if mode == "real" and compiled_artifact_present:
        kind = "real_compiled_dspy_artifact"
        load_status = "loadable"
    elif mode == "dry_run":
        kind = "dry_run_metadata"
        load_status = "metadata_only"
    elif mode == "real":
        kind = "incomplete_real_artifact"
        load_status = "not_loadable"
    else:
        kind = "unknown_metadata"
        load_status = "not_loadable"
    return {
        "kind": kind,
        "mode": mode,
        "compiled_artifact_present": compiled_artifact_present,
        "compiled_program_path": compiled_path.name if compiled_path else None,
        "metadata_json_present": metadata_present,
        "program_pickle_present": program_pickle_present,
        "load_status": load_status,
        "description": _artifact_status_description(kind),
    }


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _compiled_path_from_payload(payload: dict[str, Any], output_path: Path) -> Path | None:
    compile_payload = payload.get("gepa_compile", {})
    if not isinstance(compile_payload, dict) or compile_payload.get("executed") is not True:
        return None
    raw_compiled_path = compile_payload.get("compiled_program_path")
    if not isinstance(raw_compiled_path, str) or not raw_compiled_path:
        return None
    compiled_path = Path(raw_compiled_path)
    if compiled_path.is_absolute() or ".." in compiled_path.parts:
        return None
    return output_path.parent / compiled_path


def _compiled_program_artifacts_present(compiled_path: Path) -> bool:
    if not compiled_path.is_dir():
        return False
    return (compiled_path / "metadata.json").is_file() and (compiled_path / "program.pkl").is_file()


def _artifact_status_description(kind: str) -> str:
    if kind == "real_compiled_dspy_artifact":
        return (
            "Real GEPA compile saved a DSPy program directory with metadata.json "
            "and program.pkl."
        )
    if kind == "dry_run_metadata":
        return (
            "Dry-run optimization saved deterministic metadata only; no compiled "
            "DSPy artifact exists."
        )
    if kind == "incomplete_real_artifact":
        return "Metadata claims a real compile, but required DSPy artifact files are missing."
    return "Saved optimized-program metadata has an unrecognized mode or artifact shape."
