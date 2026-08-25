#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENTRYPOINT_LAYOUT_LIB=""
for candidate in \
    "$SCRIPT_DIR/scripts/installer/lib/entrypoint_layout.sh" \
    "$SCRIPT_DIR/installer/lib/entrypoint_layout.sh"; do
    if [ -f "$candidate" ] && [ ! -L "$candidate" ]; then
        ENTRYPOINT_LAYOUT_LIB="$candidate"
        break
    fi
done
if [ -z "$ENTRYPOINT_LAYOUT_LIB" ]; then
    printf 'Unsupported installer entrypoint layout near %s. Refusing to continue.\n' "$SCRIPT_DIR" >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$ENTRYPOINT_LAYOUT_LIB"
UPDATE_ENTRY="$(mssg_resolve_installer_entrypoint "$SCRIPT_DIR" update)" || exit 1
exec bash "$UPDATE_ENTRY" "$@"
