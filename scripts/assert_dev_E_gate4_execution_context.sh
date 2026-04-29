#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
scripts/assert_lane_execution_context.sh assets/dev_E_gate4_WORKSPACE_CONTRACT.json
