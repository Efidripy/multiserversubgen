#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    if [[ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
      PYTHON_BIN="$SCRIPT_DIR/.venv/Scripts/python.exe"
    else
      if [[ ! -x "$SCRIPT_DIR/.venv-wsl/bin/python" ]]; then
      python3 -m venv "$SCRIPT_DIR/.venv-wsl"
      fi
      PYTHON_BIN="$SCRIPT_DIR/.venv-wsl/bin/python"
    fi
  elif [[ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/Scripts/python.exe"
  elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
  else
    python3 -m venv "$SCRIPT_DIR/.venv"
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
  fi
fi

REQ_FILE="$SCRIPT_DIR/backend/requirements-dev.txt"
TEST_FILES=(
  "$SCRIPT_DIR/backend/tests/test_runtime_controls.py"
  "$SCRIPT_DIR/backend/tests/test_security_hardening.py"
  "$SCRIPT_DIR/backend/tests/test_api_smoke.py"
)

if [[ "$PYTHON_BIN" == *.exe && -n "$(command -v wslpath 2>/dev/null)" ]]; then
  REQ_FILE="$(wslpath -w "$REQ_FILE")"
  for i in "${!TEST_FILES[@]}"; do
    TEST_FILES[$i]="$(wslpath -w "${TEST_FILES[i]}")"
  done
fi

"$PYTHON_BIN" -m pip install -r "$REQ_FILE"
"$PYTHON_BIN" -m pytest \
  "${TEST_FILES[@]}" \
  -q
