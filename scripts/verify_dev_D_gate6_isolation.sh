#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/scripts/verify_lane_isolation.sh" "$ROOT/assets/dev_D_gate6_WORKSPACE_CONTRACT.json"
