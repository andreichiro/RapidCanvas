#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"${repo_root}/scripts/assert_lane_execution_context.sh" "${repo_root}/assets/dev_B_gate4_WORKSPACE_CONTRACT.json"
