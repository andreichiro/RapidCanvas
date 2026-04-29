#!/usr/bin/env bash
set -euo pipefail

contract_path="${1:?usage: scripts/assert_lane_execution_context.sh <contract-json>}"

python - "$contract_path" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


contract = json.loads(Path(sys.argv[1]).read_text())
cwd = Path(os.getcwd()).resolve()
execution_roots = [Path(root["path"]).resolve() for root in contract["execution_roots"]]
shared_roots = [Path(root["path"]).resolve() for root in contract["shared_read_only_roots"]]


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


if any(is_within(cwd, root) for root in execution_roots):
    print(f"lane execution context ok: {cwd}")
    raise SystemExit(0)

if any(is_within(cwd, root) for root in shared_roots):
    raise SystemExit(f"lane execution context failed: {cwd} is inside shared read-only root")

allowed = ", ".join(str(root) for root in execution_roots)
raise SystemExit(f"lane execution context failed: {cwd} is not an approved execution root; allowed: {allowed}")
PY
