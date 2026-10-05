#!/bin/bash

# Component ownership is deliberately separate from install_log.  The log
# describes one Sub-Manager installation; this file answers the narrower,
# safety-critical question of whether it is allowed to mutate a host-wide
# dependency.

MSSG_OWNERSHIP_SCHEMA="multiserversubgen.component-ownership.v1"

mssg_ownership_state_dir() {
    printf '%s' "${MSSG_OWNERSHIP_DIR:-/var/lib/${PROJECT_NAME:-sub-manager}}"
}

mssg_ownership_file() {
    printf '%s/component-ownership.json' "$(mssg_ownership_state_dir)"
}

mssg_ownership_validate_component() {
    [[ "${1:-}" =~ ^(grafana|prometheus|loki|promtail|x-ui|nginx|adguard)$ ]]
}

mssg_ownership_read() {
    local component="$1"
    local file
    file="$(mssg_ownership_file)"
    mssg_ownership_validate_component "$component" || return 2
    [ -f "$file" ] || return 1

    python3 - "$file" "$component" <<'PY'
import json
import sys

path, component = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    record = document.get("components", {}).get(component)
    if not isinstance(record, dict):
        raise KeyError(component)
    ownership = record.get("ownership")
    if ownership not in {"mssg-managed", "external", "adopted", "unknown"}:
        raise ValueError("invalid ownership")
except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
    raise SystemExit(1)
print(ownership)
PY
}

mssg_ownership_recorded_version() {
    local component="$1"
    local file
    file="$(mssg_ownership_file)"
    mssg_ownership_validate_component "$component" || return 2
    [ -f "$file" ] || return 1
    python3 - "$file" "$component" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        version = json.load(handle)["components"][sys.argv[2]]["installed_version"]
    if not isinstance(version, str):
        raise ValueError()
except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
    raise SystemExit(1)
print(version)
PY
}

mssg_ownership_write() {
    local component="$1"
    local ownership="$2"
    local install_method="$3"
    local state_dir file
    state_dir="$(mssg_ownership_state_dir)"
    file="$(mssg_ownership_file)"
    mssg_ownership_validate_component "$component" || return 2
    [[ "$ownership" =~ ^(mssg-managed|external|adopted|unknown)$ ]] || return 2
    [[ "$install_method" =~ ^(apt|upstream-binary|external|unknown)$ ]] || return 2

    install -d -m 0750 "$state_dir" || return 1
    local temp_file
    temp_file="$(mktemp "${state_dir}/.component-ownership.XXXXXX")" || return 1
    python3 - "$file" "$temp_file" "$component" "$ownership" "$install_method" "$MSSG_OWNERSHIP_SCHEMA" "$(mssg_ownership_component_version "$component")" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

path, temp_path, component, ownership, install_method, schema, version = sys.argv[1:]
document = {"schema": schema, "components": {}}
try:
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    if isinstance(loaded, dict) and isinstance(loaded.get("components"), dict):
        document = loaded
        document["schema"] = schema
except FileNotFoundError:
    pass
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    raise SystemExit("ownership registry is malformed; refusing to overwrite it")

managed_paths = {
    "grafana": [
        "/etc/grafana/provisioning/datasources/sub-manager-prometheus.yml",
        "/etc/grafana/provisioning/dashboards/sub-manager-dashboard.yml",
        "/etc/systemd/system/grafana-server.service.d/40-sub-manager.conf",
        "/var/lib/grafana/dashboards/sub-manager",
    ],
    "prometheus": ["/etc/prometheus/rules/sub-manager-rules.yml"],
}.get(component, [])
hashes = {}
for managed_path in managed_paths:
    if os.path.isfile(managed_path) and not os.path.islink(managed_path):
        import hashlib
        with open(managed_path, "rb") as handle:
            hashes[managed_path] = hashlib.sha256(handle.read()).hexdigest()

document.setdefault("components", {})[component] = {
    "ownership": ownership,
    "install_method": install_method,
    "installed_version": version or "unknown",
    "source_fingerprint": f"{install_method}:{version or 'unknown'}",
    "managed_paths": managed_paths if ownership in {"mssg-managed", "adopted"} else [],
    "config_hashes": hashes,
    "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
}
with open(temp_path, "w", encoding="utf-8") as handle:
    json.dump(document, handle, indent=2, sort_keys=True)
    handle.write("\n")
os.chmod(temp_path, 0o600)
PY
    local status=$?
    if [ "$status" -ne 0 ]; then
        rm -f "$temp_file"
        return "$status"
    fi
    mv -f "$temp_file" "$file"
    chmod 0600 "$file"
}

mssg_ownership_component_present() {
    local component="$1"
    local service_name="$component"
    [ "$component" = "grafana" ] && service_name="grafana-server"
    case "$component" in
        grafana|prometheus|loki|promtail)
            dpkg -s "$component" >/dev/null 2>&1 \
                || command -v "$component" >/dev/null 2>&1 \
                || { [ "$component" = "grafana" ] && command -v grafana-server >/dev/null 2>&1; } \
                || { command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^${service_name}\.service"; }
            ;;
        x-ui)
            command -v x-ui >/dev/null 2>&1 \
                || (command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^x-ui\.service')
            ;;
        nginx)
            command -v nginx >/dev/null 2>&1
            ;;
        adguard)
            command -v AdGuardHome >/dev/null 2>&1 || [ -d /opt/AdGuardHome ]
            ;;
        *) return 2 ;;
    esac
}

mssg_ownership_component_version() {
    local component="$1"
    if dpkg -s "$component" >/dev/null 2>&1; then
        dpkg-query -W -f='${Version}' "$component" 2>/dev/null || printf 'unknown'
        return 0
    fi
    case "$component" in
        grafana) grafana-server -v 2>/dev/null | head -n 1 || printf 'unknown' ;;
        *) "$component" --version 2>/dev/null | head -n 1 || printf 'unknown' ;;
    esac
}

# Legacy installations have no registry.  A component already present on such
# a host is external until an operator explicitly adopts it.  This is the
# important fail-closed migration rule.
mssg_ownership_discover_component() {
    local component="$1"
    local ownership=""
    ownership="$(mssg_ownership_read "$component" 2>/dev/null || true)"
    [ -n "$ownership" ] && return 0

    if mssg_ownership_component_present "$component"; then
        mssg_ownership_write "$component" external external
        echo "Ownership: $component is pre-existing/external; MSSG will not modify it." >&2
    fi
}

mssg_ownership_discover_monitoring() {
    mssg_ownership_discover_component prometheus || return 1
    mssg_ownership_discover_component grafana || return 1
}

mssg_ownership_is_managed() {
    local ownership=""
    ownership="$(mssg_ownership_read "$1" 2>/dev/null || true)"
    [[ "$ownership" == "mssg-managed" || "$ownership" == "adopted" ]]
}

mssg_ownership_version_matches_registry() {
    local component="$1"
    local recorded actual
    recorded="$(mssg_ownership_recorded_version "$component" 2>/dev/null || true)"
    actual="$(mssg_ownership_component_version "$component")"
    # Older registries did not capture a version. They remain conservative at
    # the component boundary but are not made unusable solely for migration.
    [ -z "$recorded" ] || [ "$recorded" = "unknown" ] || [ "$actual" = "unknown" ] || [ "$recorded" = "$actual" ]
}

# Returns 0 only when it is safe for the caller to provision/reconcile the
# complete monitoring stack.  External and unknown components are not a
# partial-success case: Prometheus/Grafana config is coupled, so skip both.
mssg_ownership_allow_monitoring_mutation() {
    local component ownership=""
    mssg_ownership_discover_monitoring || return 1
    for component in prometheus grafana; do
        ownership="$(mssg_ownership_read "$component" 2>/dev/null || true)"
        case "$ownership" in
            "") ;;
            mssg-managed|adopted)
                if ! mssg_ownership_component_present "$component"; then
                    echo "Ownership registry marks $component as $ownership, but it is missing. Refusing automatic repair." >&2
                    return 1
                fi
                if ! mssg_ownership_version_matches_registry "$component"; then
                    echo "$component version differs from the ownership registry. Treating it as externally maintained; no mutation is allowed." >&2
                    return 1
                fi
                ;;
            external|unknown)
                echo "Monitoring is not modified: $component ownership is $ownership. Run the explicit adoption workflow first." >&2
                return 1
                ;;
            *)
                echo "Monitoring is not modified: invalid ownership state for $component." >&2
                return 1
                ;;
        esac
    done
    return 0
}

mssg_ownership_claim_managed() {
    local component="$1"
    mssg_ownership_write "$component" mssg-managed apt
}

mssg_ownership_report() {
    local component ownership presence
    printf '%-12s %-14s %s\n' "component" "ownership" "present"
    for component in grafana prometheus loki promtail x-ui nginx adguard; do
        ownership="$(mssg_ownership_read "$component" 2>/dev/null || printf 'untracked')"
        if mssg_ownership_component_present "$component"; then
            presence="yes"
        else
            presence="no"
        fi
        printf '%-12s %-14s %s\n' "$component" "$ownership" "$presence"
    done
}
