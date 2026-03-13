#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/Scripts/python.exe"
  elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
  else
    python3 -m venv "$SCRIPT_DIR/.venv"
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
  fi
fi

"$PYTHON_BIN" -m pip install -r "$SCRIPT_DIR/backend/requirements-dev.txt"
"$PYTHON_BIN" -m pytest \
  "$SCRIPT_DIR/backend/tests/test_runtime_controls.py" \
  "$SCRIPT_DIR/backend/tests/test_security_hardening.py" \
  "$SCRIPT_DIR/backend/tests/test_api_smoke.py" \
  -q
