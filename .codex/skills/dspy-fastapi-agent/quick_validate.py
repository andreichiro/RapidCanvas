"""Skill-local validation entry point."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parent
sys.argv = [str(REPO_ROOT / "scripts" / "quick_validate.py"), str(SKILL_DIR)]
runpy.run_path(str(REPO_ROOT / "scripts" / "quick_validate.py"), run_name="__main__")
