#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-audit}"

RECOMMENDED_DISABLE=(
  ModemManager
  multipathd
  packagekit
  udisks2
  upower
  avahi-daemon
  bluetooth
  whoopsie
)

KEEP_ENABLED=(
  ssh
  nginx
  fail2ban
  open-vm-tools
  sub-manager
  x-ui
)

print_audit() {
  echo "== Hardening audit =="
  echo "Keep enabled:"
  for s in "${KEEP_ENABLED[@]}"; do
    if systemctl list-unit-files --type=service | grep -q "^${s}\.service"; then
      echo "  - ${s}: $(systemctl is-enabled "${s}" 2>/dev/null || echo unknown)"
    fi
  done
  echo "Candidates to disable:"
  for s in "${RECOMMENDED_DISABLE[@]}"; do
    if systemctl list-unit-files --type=service | grep -q "^${s}\.service"; then
      echo "  - ${s}: $(systemctl is-enabled "${s}" 2>/dev/null || echo unknown)"
    fi
  done
}

apply_profile() {
  for s in "${RECOMMENDED_DISABLE[@]}"; do
    if systemctl list-unit-files --type=service | grep -q "^${s}\.service"; then
      systemctl disable --now "$s" >/dev/null 2>&1 || true
      echo "disabled: $s"
    fi
  done
  if systemctl list-unit-files --type=service | grep -q '^snapd\.service'; then
    systemctl disable --now snapd snapd.socket snapd.seeded.service >/dev/null 2>&1 || true
    echo "disabled: snapd stack"
  fi
}

case "$MODE" in
  audit) print_audit ;;
  apply) apply_profile; print_audit ;;
  *)
    echo "Usage: $0 [audit|apply]"
    exit 1
    ;;
esac
