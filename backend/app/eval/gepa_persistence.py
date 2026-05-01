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
