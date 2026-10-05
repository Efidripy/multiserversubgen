#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/component_ownership.sh"

usage() {
    cat <<'EOF'
Usage:
  component-ownership.sh report
  component-ownership.sh adopt grafana|prometheus [grafana|prometheus ...]
  component-ownership.sh release grafana|prometheus [grafana|prometheus ...]

`report` is read-only. `adopt` and `release` change only the local ownership
registry; they do not update packages, services, or configuration. A later
explicit monitoring reconciliation is still required after adoption.
EOF
}

command="${1:-report}"
shift || true
case "$command" in
    report)
        [ "$#" -eq 0 ] || { usage >&2; exit 2; }
        mssg_ownership_report
        ;;
    adopt)
        [ "$#" -gt 0 ] || { usage >&2; exit 2; }
        [ "$EUID" -eq 0 ] || { echo "Run adoption as root." >&2; exit 1; }
        for component in "$@"; do
            mssg_ownership_validate_component "$component" || { echo "Unsupported component: $component" >&2; exit 2; }
            case "$component" in grafana|prometheus) ;; *) echo "Only Grafana and Prometheus can be adopted by this command." >&2; exit 2 ;; esac
            mssg_ownership_component_present "$component" || { echo "$component is not present; nothing to adopt." >&2; exit 1; }
        done
        read -r -p "Type ADOPT_MSSG_MONITORING to transfer ownership: " acknowledgement
        [ "$acknowledgement" = "ADOPT_MSSG_MONITORING" ] || { echo "Adoption acknowledgement did not match; no change made." >&2; exit 1; }
        for component in "$@"; do
            mssg_ownership_write "$component" adopted external
        done
        echo "Ownership registry updated. No packages, services, or configuration were changed."
        ;;
    release)
        [ "$#" -gt 0 ] || { usage >&2; exit 2; }
        [ "$EUID" -eq 0 ] || { echo "Run release as root." >&2; exit 1; }
        for component in "$@"; do
            mssg_ownership_validate_component "$component" || { echo "Unsupported component: $component" >&2; exit 2; }
            case "$component" in grafana|prometheus) ;; *) echo "Only Grafana and Prometheus can be released by this command." >&2; exit 2 ;; esac
            mssg_ownership_component_present "$component" || { echo "$component is not present; nothing to release." >&2; exit 1; }
        done
        read -r -p "Type RELEASE_MSSG_MONITORING to stop MSSG management: " acknowledgement
        [ "$acknowledgement" = "RELEASE_MSSG_MONITORING" ] || { echo "Release acknowledgement did not match; no change made." >&2; exit 1; }
        for component in "$@"; do
            mssg_ownership_write "$component" external external
        done
        echo "Ownership registry updated. No packages, services, or configuration were changed."
        ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
esac
