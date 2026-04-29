#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
scripts/verify_lane_isolation.sh assets/dev_E_gate4_WORKSPACE_CONTRACT.json
