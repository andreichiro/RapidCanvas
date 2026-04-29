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

contract = json.loads(Path(sys.argv[1]).resolve().read_text())


def top_level(path: str) -> str:
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return str(Path(result.stdout.strip()).resolve())


cwd_top = top_level(".")
execution_roots = {str(Path(entry["path"]).resolve()) for entry in contract["execution_roots"]}
shared_roots = set()
for entry in contract.get("shared_read_only_roots", []):
    path = entry["path"] if isinstance(entry, dict) else entry
    shared_roots.add(str(Path(path).resolve()))

if cwd_top in execution_roots:
    print(f"execution context verified: {cwd_top}")
    sys.exit(0)

if cwd_top in shared_roots:
    print(f"FAIL: current root is shared read-only, not an execution root: {cwd_top}", file=sys.stderr)
    sys.exit(1)

print(f"FAIL: current root is not approved for this lane: {cwd_top}", file=sys.stderr)
print("approved execution roots:", file=sys.stderr)
for root in sorted(execution_roots):
    print(f"  {root}", file=sys.stderr)
sys.exit(1)
PY
