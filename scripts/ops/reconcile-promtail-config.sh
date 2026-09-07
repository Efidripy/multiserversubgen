#!/usr/bin/env bash
# Internal, authorised monitoring reconciliation. It never enables Promtail
# and deliberately skips journal scraping when the host has no readable journal.
set -euo pipefail
umask 077

BASE_TEMPLATE="${PROMTAIL_CONFIG_TEMPLATE:-}"
JOURNAL_TEMPLATE="${PROMTAIL_JOURNAL_TEMPLATE:-}"
OUTPUT_PATH="${PROMTAIL_CONFIG_PATH:-/etc/promtail/config.yml}"
SERVICE_NAME="${PROMTAIL_SERVICE_NAME:-promtail.service}"
PERSISTENT_JOURNAL_DIR="${PROMTAIL_PERSISTENT_JOURNAL_DIR:-/var/log/journal}"
RUNTIME_JOURNAL_DIR="${PROMTAIL_RUNTIME_JOURNAL_DIR:-/run/log/journal}"
QUERYLOG_PATH="${ADGUARD_QUERYLOG_PATH:-/opt/AdGuardHome/data/querylog.json}"
SYSTEMD_UNIT="${ADGUARD_SYSTEMD_UNIT:-AdGuardHome.service}"
RESTART_ACTIVE="false"

usage() {
    cat <<'EOF'
Usage: reconcile-promtail-config.sh [--restart-active]

Required environment:
  PROMTAIL_CONFIG_TEMPLATE   querylog-only config template
  PROMTAIL_JOURNAL_TEMPLATE  optional journal scrape fragment

Optional environment:
  PROMTAIL_CONFIG_PATH, PROMTAIL_SERVICE_NAME,
  PROMTAIL_PERSISTENT_JOURNAL_DIR, PROMTAIL_RUNTIME_JOURNAL_DIR,
  ADGUARD_QUERYLOG_PATH, ADGUARD_SYSTEMD_UNIT
EOF
}

fail() {
    printf 'Promtail reconciliation refused: %s\n' "$*" >&2
    exit 1
}

for arg in "$@"; do
    case "$arg" in
        --restart-active) RESTART_ACTIVE="true" ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; fail "unknown argument: $arg" ;;
    esac
done

[[ -n "$BASE_TEMPLATE" && -f "$BASE_TEMPLATE" && ! -L "$BASE_TEMPLATE" ]] \
    || fail "PROMTAIL_CONFIG_TEMPLATE must name a regular file"
[[ -n "$JOURNAL_TEMPLATE" && -f "$JOURNAL_TEMPLATE" && ! -L "$JOURNAL_TEMPLATE" ]] \
    || fail "PROMTAIL_JOURNAL_TEMPLATE must name a regular file"
[[ "$OUTPUT_PATH" == /* ]] || fail "PROMTAIL_CONFIG_PATH must be absolute"
[[ ! -L "$OUTPUT_PATH" ]] || fail "refusing symlinked Promtail config destination"
[[ "$QUERYLOG_PATH" != *$'\n'* && "$QUERYLOG_PATH" != *$'\r'* ]] \
    || fail "ADGUARD_QUERYLOG_PATH must be one line"
[[ "$SYSTEMD_UNIT" =~ ^[A-Za-z0-9@_.:-]+$ ]] \
    || fail "ADGUARD_SYSTEMD_UNIT contains unsupported characters"

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

render_template() {
    local template="$1"
    local journal_path="${2:-}"
    sed \
        -e "s|__ADGUARD_QUERYLOG_PATH__|$(escape_sed_replacement "$QUERYLOG_PATH")|g" \
        -e "s|__ADGUARD_SYSTEMD_UNIT__|$(escape_sed_replacement "$SYSTEMD_UNIT")|g" \
        -e "s|__PROMTAIL_JOURNAL_PATH__|$(escape_sed_replacement "$journal_path")|g" \
        "$template"
}

choose_journal_path() {
    if [[ -d "$PERSISTENT_JOURNAL_DIR" && -r "$PERSISTENT_JOURNAL_DIR" && -x "$PERSISTENT_JOURNAL_DIR" ]]; then
        printf '%s\n' "$PERSISTENT_JOURNAL_DIR"
        return 0
    fi
    if [[ -d "$RUNTIME_JOURNAL_DIR" && -r "$RUNTIME_JOURNAL_DIR" && -x "$RUNTIME_JOURNAL_DIR" ]]; then
        printf '%s\n' "$RUNTIME_JOURNAL_DIR"
        return 0
    fi
    return 1
}

check_syntax_when_supported() {
    local binary=""

    if command -v promtail >/dev/null 2>&1; then
        binary="$(command -v promtail)"
    elif [[ -x /usr/local/bin/promtail ]]; then
        binary="/usr/local/bin/promtail"
    fi

    [[ -n "$binary" ]] || return 0
    if "$binary" -help 2>&1 | grep -Fq -- '-check-syntax'; then
        "$binary" -config.file="$1" -check-syntax >/dev/null
    fi
}

restart_if_previously_managed() {
    [[ "$RESTART_ACTIVE" == "true" ]] || return 0
    command -v systemctl >/dev/null 2>&1 || return 0
    systemctl cat "$SERVICE_NAME" >/dev/null 2>&1 || {
        printf 'Promtail config updated; %s is not a managed systemd unit, so it was not started.\n' "$SERVICE_NAME"
        return 0
    }

    if ! systemctl is-active --quiet "$SERVICE_NAME" && ! systemctl is-enabled --quiet "$SERVICE_NAME"; then
        printf 'Promtail config updated; %s is disabled and inactive, so it was not started.\n' "$SERVICE_NAME"
        return 0
    fi

    systemctl reset-failed "$SERVICE_NAME" || true
    systemctl restart "$SERVICE_NAME"
    systemctl is-active --quiet "$SERVICE_NAME" \
        || fail "$SERVICE_NAME did not become active after the safe config was installed"
}

config_dir="$(dirname -- "$OUTPUT_PATH")"
install -d -m 0755 -- "$config_dir"
temp_config="$(mktemp "${config_dir}/.config.yml.tmp.XXXXXX")"
trap 'rm -f -- "$temp_config"' EXIT

render_template "$BASE_TEMPLATE" > "$temp_config"
if journal_path="$(choose_journal_path)"; then
    printf '\n' >> "$temp_config"
    render_template "$JOURNAL_TEMPLATE" "$journal_path" >> "$temp_config"
    printf 'Promtail journal scrape enabled: %s\n' "$journal_path"
else
    printf 'Promtail journal scrape skipped: no journal directory found.\n'
fi

if grep -Eq '__ADGUARD_[A-Z_]+__|__PROMTAIL_[A-Z_]+__' "$temp_config"; then
    fail "unresolved Promtail template placeholder"
fi
check_syntax_when_supported "$temp_config"
if (( EUID == 0 )); then
    chown root:root "$temp_config"
fi
chmod 0644 "$temp_config"
mv -fT -- "$temp_config" "$OUTPUT_PATH"
trap - EXIT

restart_if_previously_managed
printf 'Promtail config reconciled: %s\n' "$OUTPUT_PATH"
