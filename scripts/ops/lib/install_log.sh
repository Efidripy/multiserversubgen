#!/usr/bin/env bash

# Load the installer state log only after validating its ownership and mode.
# Installer logs are generated as shell assignments using printf '%q'; keeping
# the source operation behind this guard preserves that format without allowing
# an arbitrary path or untrusted file to execute as the caller.
install_log_source() {
  local log_file="${1:?log file path is required}"
  local owner mode

  [[ -f "$log_file" ]] || return 0
  [[ ! -L "$log_file" ]] || {
    printf 'refusing to source symlinked installer log: %s\n' "$log_file" >&2
    return 1
  }

  command -v stat >/dev/null 2>&1 || {
    printf 'refusing to source installer log: stat is required\n' >&2
    return 1
  }

  owner="$(stat -c '%u' -- "$log_file" 2>/dev/null)" || return 1
  mode="$(stat -c '%a' -- "$log_file" 2>/dev/null)" || return 1
  [[ "$owner" == "0" && "$mode" == "600" ]] || {
    printf 'refusing to source installer log with owner/mode %s/%s: %s\n' "$owner" "$mode" "$log_file" >&2
    return 1
  }

  # shellcheck disable=SC1090
  source "$log_file"
}
