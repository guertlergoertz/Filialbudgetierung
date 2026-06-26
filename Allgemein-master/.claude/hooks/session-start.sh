#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

pip install --quiet -r "$CLAUDE_PROJECT_DIR/revenue_planner/requirements.txt"
pip install --quiet pytest
