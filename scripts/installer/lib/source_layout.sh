#!/usr/bin/env bash

# Resolves the reviewed source layouts accepted by the privileged installer.
#
# Canonical source is a Git checkout with backend/, frontend/ and scripts/.
# Flat release bundles intentionally place backend and frontend files at the
# bundle root, while keeping installer/, ops/ and deploy/ as top-level dirs.
# Any other shape is rejected before installer state or runtime files change.

mssg_source_layout_has_files() {
    local root="$1"
    shift
    local relative_path
    for relative_path in "$@"; do
        [ -f "$root/$relative_path" ] || return 1
    done
}

mssg_resolve_source_layout() {
    local installer_dir="$1"
    local canonical_root
    local flat_root

    canonical_root="$(cd "${installer_dir}/../.." && pwd -P)" || return 1
    if mssg_source_layout_has_files "$canonical_root" \
        "backend/main.py" \
        "backend/requirements.txt" \
        "frontend/package.json" \
        "scripts/ops/lib/install_log.sh" \
        "scripts/deploy/build-and-publish-frontend.sh" \
        "scripts/deploy/verify-frontend-release.sh" \
        "scripts/installer/lib/entrypoint_layout.sh" \
        "monitoring/prometheus/rules.yml" \
        "monitoring/loki/loki-config.yml" \
        "monitoring/promtail/promtail-config.yml" \
        "monitoring/grafana/sub-manager-dashboard.json" \
        "monitoring/grafana/adguard-overview-dashboard.json" \
        "systemd/sub-manager.service"; then
        MSSG_SOURCE_LAYOUT="canonical"
        MSSG_SOURCE_ROOT="$canonical_root"
        MSSG_BACKEND_DIR="$canonical_root/backend"
        MSSG_FRONTEND_DIR="$canonical_root/frontend"
        MSSG_OPS_DIR="$canonical_root/scripts/ops"
        MSSG_DEPLOY_DIR="$canonical_root/scripts/deploy"
        MSSG_PROMETHEUS_RULES="$canonical_root/monitoring/prometheus/rules.yml"
        MSSG_LOKI_CONFIG="$canonical_root/monitoring/loki/loki-config.yml"
        MSSG_PROMTAIL_CONFIG="$canonical_root/monitoring/promtail/promtail-config.yml"
        MSSG_GRAFANA_DASHBOARD="$canonical_root/monitoring/grafana/sub-manager-dashboard.json"
        MSSG_GRAFANA_ADGUARD_DASHBOARD="$canonical_root/monitoring/grafana/adguard-overview-dashboard.json"
        MSSG_SYSTEMD_TEMPLATE="$canonical_root/systemd/sub-manager.service"
        MSSG_VERIFY_FRONTEND_RELEASE_SCRIPT="$canonical_root/scripts/deploy/verify-frontend-release.sh"
        MSSG_INSTALLER_DIR="$canonical_root/scripts/installer"
        return 0
    fi

    flat_root="$(cd "${installer_dir}/.." && pwd -P)" || return 1
    if mssg_source_layout_has_files "$flat_root" \
        "main.py" \
        "requirements.txt" \
        "package.json" \
        "ops/lib/install_log.sh" \
        "deploy/build-and-publish-frontend.sh" \
        "deploy/verify-frontend-release.sh" \
        "installer/lib/entrypoint_layout.sh" \
        "prometheus/rules.yml" \
        "loki/loki-config.yml" \
        "promtail/promtail-config.yml" \
        "grafana/sub-manager-dashboard.json" \
        "grafana/adguard-overview-dashboard.json" \
        "sub-manager.service"; then
        MSSG_SOURCE_LAYOUT="flat-release"
        MSSG_SOURCE_ROOT="$flat_root"
        MSSG_BACKEND_DIR="$flat_root"
        MSSG_FRONTEND_DIR="$flat_root"
        MSSG_OPS_DIR="$flat_root/ops"
        MSSG_DEPLOY_DIR="$flat_root/deploy"
        MSSG_PROMETHEUS_RULES="$flat_root/prometheus/rules.yml"
        MSSG_LOKI_CONFIG="$flat_root/loki/loki-config.yml"
        MSSG_PROMTAIL_CONFIG="$flat_root/promtail/promtail-config.yml"
        MSSG_GRAFANA_DASHBOARD="$flat_root/grafana/sub-manager-dashboard.json"
        MSSG_GRAFANA_ADGUARD_DASHBOARD="$flat_root/grafana/adguard-overview-dashboard.json"
        MSSG_SYSTEMD_TEMPLATE="$flat_root/sub-manager.service"
        MSSG_VERIFY_FRONTEND_RELEASE_SCRIPT="$flat_root/deploy/verify-frontend-release.sh"
        MSSG_INSTALLER_DIR="$flat_root/installer"
        return 0
    fi

    printf 'Unsupported installer source layout near %s. Refusing to continue before changing runtime state.\n' "$installer_dir" >&2
    return 1
}
