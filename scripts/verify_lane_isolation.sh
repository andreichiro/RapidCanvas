#!/usr/bin/env bash
set -euo pipefail

contract_path="${1:?usage: scripts/verify_lane_isolation.sh <contract-json>}"

python - "$contract_path" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path


def run(args: list[str], cwd: str) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def fail(message: str) -> None:
    print(f"isolation check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


contract = json.loads(Path(sys.argv[1]).read_text())
required_branch = contract["required_branch"]

for root in contract["execution_roots"]:
    path = root["path"]
    if not os.path.isdir(path):
        fail(f"execution root missing: {path}")
    git_dir = run(["git", "rev-parse", "--git-dir"], cwd=path)
    if git_dir != ".git":
        fail(f"execution root is not a standalone clone: {path} has git dir {git_dir!r}")
    branch = run(["git", "branch", "--show-current"], cwd=path)
    if branch != required_branch:
        fail(f"execution root {path} is on {branch!r}, expected {required_branch!r}")

for root in contract.get("shared_read_only_roots", []):
    path = root["path"]
    if not os.path.isdir(path):
        continue
    git_dir = run(["git", "rev-parse", "--git-dir"], cwd=path)
    if git_dir != ".git":
        fail(f"shared root is not a standalone clone: {path} has git dir {git_dir!r}")
    branch = run(["git", "branch", "--show-current"], cwd=path)
    if branch == required_branch:
        fail(f"shared root {path} is checked out on live lane branch {required_branch!r}")
    worktree_output = run(["git", "worktree", "list", "--porcelain"], cwd=path)
    current_worktree = None
    for line in worktree_output.splitlines():
        if line.startswith("worktree "):
            current_worktree = line.removeprefix("worktree ")
        elif line == f"branch refs/heads/{required_branch}":
            fail(f"shared root reports lane branch owned by worktree {current_worktree}")

print(f"isolation check passed for {contract['lane']} on {required_branch}")
PY
