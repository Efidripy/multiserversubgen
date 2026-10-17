#!/bin/bash

# Reconcile the MSSG-owned Loki configuration without ever replacing the live
# file before the exact installed Loki binary accepts the candidate.

mssg_reconcile_loki_config() {
    local source_config="$1"
    local config_dir="${2:-/etc/loki}"
    local loki_bin="${LOKI_BIN:-}"
    local candidate backup_dir backup_name

    [ -r "$source_config" ] || {
        echo "Loki configuration template is unreadable: $source_config" >&2
        return 1
    }
    if [ -z "$loki_bin" ]; then
        loki_bin="$(command -v loki 2>/dev/null || true)"
    fi
    [ -n "$loki_bin" ] && [ -x "$loki_bin" ] || {
        echo "Loki binary is unavailable; refusing to replace its configuration." >&2
        return 1
    }

    if [ ! -d "$config_dir" ]; then
        install -d -m 0755 "$config_dir" || return 1
    fi
    candidate="$(mktemp "$config_dir/.sub-manager-loki-config.XXXXXX")" || return 1
    if ! install -m 0644 "$source_config" "$candidate"; then
        rm -f "$candidate"
        return 1
    fi
    if ! "$loki_bin" -config.file="$candidate" -verify-config >/dev/null; then
        rm -f "$candidate"
        echo "Loki rejected the candidate configuration; live configuration was preserved." >&2
        return 1
    fi

    backup_dir="${MSSG_LOKI_CONFIG_BACKUP_DIR:-/var/backups/sub-manager_loki}"
    if [ ! -d "$backup_dir" ]; then
        install -d -m 0700 "$backup_dir" || { rm -f "$candidate"; return 1; }
    fi
    if [ -f "$config_dir/local-config.yaml" ]; then
        backup_name="local-config.$(date -u +%Y%m%dT%H%M%SZ).yaml"
        cp -p "$config_dir/local-config.yaml" "$backup_dir/$backup_name" || {
            rm -f "$candidate"
            return 1
        }
    fi

    # The service reads local-config.yaml.  Rename keeps it atomic for a
    # concurrent reader; config.yml remains the compatibility copy.
    mv -f "$candidate" "$config_dir/local-config.yaml" || { rm -f "$candidate"; return 1; }
    install -m 0644 "$config_dir/local-config.yaml" "$config_dir/config.yml" || return 1
}
