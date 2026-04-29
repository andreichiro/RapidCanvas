#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <contract-json>" >&2
  exit 2
fi

CONTRACT="$1"

python - "$CONTRACT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

contract_path = Path(sys.argv[1]).resolve()
contract = json.loads(contract_path.read_text())
required_branch = contract["required_branch"]


def run_git(path: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", path, *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def shared_paths() -> list[str]:
    paths: list[str] = []
    for entry in contract.get("shared_read_only_roots", []):
        if isinstance(entry, dict):
            paths.append(entry["path"])
        else:
            paths.append(entry)
    return paths


errors: list[str] = []

for entry in contract["execution_roots"]:
    path = Path(entry["path"])
    if not path.exists():
        errors.append(f"execution root does not exist: {path}")
        continue

    git_dir = path / ".git"
    if not git_dir.is_dir():
        errors.append(f"execution root is not a standalone clone with real .git directory: {path}")

    branch = run_git(str(path), "branch", "--show-current")
    if branch != required_branch:
        errors.append(f"execution root {path} is on {branch!r}, expected {required_branch!r}")

for path_text in shared_paths():
    path = Path(path_text)
    if not path.exists():
        continue

    branch = run_git(str(path), "branch", "--show-current")
    if branch == required_branch:
        errors.append(f"shared read-only root is on live lane branch: {path}")

    try:
        worktrees = run_git(str(path), "worktree", "list", "--porcelain")
    except subprocess.CalledProcessError as exc:
        errors.append(f"failed to inspect worktrees for shared root {path}: {exc.stderr.strip()}")
        continue

    if f"branch refs/heads/{required_branch}" in worktrees:
        errors.append(f"shared root reports linked worktree ownership of {required_branch}: {path}")

if errors:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    sys.exit(1)

print(f"lane isolation verified: {contract['lane']} on {required_branch}")
PY
