#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
scripts/verify_lane_isolation.sh assets/dev_G7_B_WORKSPACE_CONTRACT.json
