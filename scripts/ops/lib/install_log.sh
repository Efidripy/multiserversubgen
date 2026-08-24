#!/usr/bin/env bash

# Load the installer state log only after validating its ownership and mode.
# Installer logs are generated as shell assignments using printf '%q'; keeping
# the source operation behind this guard preserves that format without allowing
# an arbitrary path or untrusted file to execute as the caller.
secure_source_file() {
  local source_file="${1:?source file path is required}"
  local source_label="${2:-source file}"
  local owner mode

  [[ -f "$source_file" ]] || return 0
  [[ ! -L "$source_file" ]] || {
    printf 'refusing to source symlinked %s: %s\n' "$source_label" "$source_file" >&2
    return 1
  }

  command -v stat >/dev/null 2>&1 || {
    printf 'refusing to source %s: stat is required\n' "$source_label" >&2
    return 1
  }

  owner="$(stat -c '%u' -- "$source_file" 2>/dev/null)" || return 1
  mode="$(stat -c '%a' -- "$source_file" 2>/dev/null)" || return 1
  [[ "$owner" == "0" && "$mode" == "600" ]] || {
    printf 'refusing to source %s with owner/mode %s/%s: %s\n' "$source_label" "$owner" "$mode" "$source_file" >&2
    return 1
  }

  # shellcheck disable=SC1090
  source "$source_file"
}

install_log_source() {
  secure_source_file "${1:?log file path is required}" "installer log"
}
