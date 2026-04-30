#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"${repo_root}/scripts/verify_lane_isolation.sh" "${repo_root}/assets/dev_B_gate4_WORKSPACE_CONTRACT.json"
