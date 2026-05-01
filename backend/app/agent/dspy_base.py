"""Import-safe DSPy base class helper."""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast


def dspy_module_base() -> type[Any]:
    """Return ``dspy.Module`` when installed, otherwise ``object``."""

    try:
        dspy = import_module("dspy")
    except ImportError:
        return object
    return cast(type[Any], dspy.Module)
