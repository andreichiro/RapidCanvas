#!/usr/bin/env bash
set -euo pipefail

contract_path="${1:?usage: scripts/assert_lane_execution_context.sh <contract-json>}"

python - "$contract_path" <<'PY'
import json
import os
import sys
from pathlib import Path


def same_path(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


contract = json.loads(Path(sys.argv[1]).read_text())
cwd = os.getcwd()
execution_roots = [root["path"] for root in contract["execution_roots"]]
shared_roots = [root["path"] for root in contract.get("shared_read_only_roots", [])]

if any(same_path(cwd, root) for root in execution_roots):
    print(f"execution context check passed for {contract['lane']}: {cwd}")
    raise SystemExit(0)

if any(same_path(cwd, root) for root in shared_roots):
    print(
        f"execution context check failed: {cwd} is a shared read-only root for {contract['lane']}",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(
    f"execution context check failed: {cwd} is not an approved execution root for {contract['lane']}",
    file=sys.stderr,
)
raise SystemExit(1)
PY
