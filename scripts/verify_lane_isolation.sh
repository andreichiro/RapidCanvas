#!/usr/bin/env bash
set -euo pipefail

contract_path="${1:?usage: scripts/verify_lane_isolation.sh <contract-json>}"

python - "$contract_path" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


contract = json.loads(Path(sys.argv[1]).read_text())
required_branch = contract["required_branch"]


def git(path: str, *args: str) -> str:
    return subprocess.check_output(["git", "-C", path, *args], text=True).strip()


def fail(message: str) -> None:
    raise SystemExit(f"lane isolation failed: {message}")


for root in contract["execution_roots"]:
    path = Path(root["path"])
    if not path.exists():
        fail(f"execution root missing: {path}")
    if not (path / ".git").is_dir():
        fail(f"execution root is not a standalone clone: {path}")
    branch = git(str(path), "branch", "--show-current")
    if branch != required_branch:
        fail(f"{path} is on {branch!r}, expected {required_branch!r}")
    worktree_root = git(str(path), "rev-parse", "--show-toplevel")
    if Path(worktree_root).resolve() != path.resolve():
        fail(f"{path} resolves to unexpected git root {worktree_root}")

for root in contract["shared_read_only_roots"]:
    path = Path(root["path"])
    if not path.exists():
        continue
    if not (path / ".git").exists():
        continue
    branch = git(str(path), "branch", "--show-current")
    if branch == required_branch:
        fail(f"shared root is checked out on required branch: {path}")
    worktrees = git(str(path), "worktree", "list", "--porcelain")
    if required_branch in worktrees:
        fail(f"shared root reports worktree ownership of {required_branch}: {path}")

print(f"lane isolation ok: {contract['lane']} on {required_branch}")
PY
