#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
scripts/assert_lane_execution_context.sh assets/dev_C_gate4_WORKSPACE_CONTRACT.json
