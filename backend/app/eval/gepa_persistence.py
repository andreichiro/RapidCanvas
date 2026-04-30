"""Persistence helpers for saved GEPA DSPy programs."""

from __future__ import annotations

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
