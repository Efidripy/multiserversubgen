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
STANDARD_ENTRY="$(mssg_resolve_installer_entrypoint "$SCRIPT_DIR" install)" || exit 1
ADVANCED_ENTRY="$(dirname "$STANDARD_ENTRY")/launcher.sh"

run_standard_entry() {
	exec "${BASH:-bash}" "$STANDARD_ENTRY" "$@"
}

run_advanced_entry() {
	exec "${BASH:-bash}" "$ADVANCED_ENTRY" "$@"
}

ENTRY_MODE="${INSTALLER_ENTRY_MODE:-}"

if [ "${1:-}" = "--standard" ]; then
	ENTRY_MODE="standard"
	shift
elif [ "${1:-}" = "--advanced" ]; then
	ENTRY_MODE="advanced"
	shift
fi

# Keep existing behavior for automation/non-interactive execution paths.
if [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ] || [ ! -t 0 ]; then
	run_standard_entry "$@"
fi

if [ -z "$ENTRY_MODE" ]; then
	printf "\nSelect install mode:\n"
	printf "  1) Standard Install\n"
	printf "  2) Advanced Install\n"
	printf "\nChoose [1-2] (default 1): "

	IFS= read -r mode_choice
	case "$mode_choice" in
		2) ENTRY_MODE="advanced" ;;
		*) ENTRY_MODE="standard" ;;
	esac
fi

case "$ENTRY_MODE" in
	advanced) run_advanced_entry "$@" ;;
	*) run_standard_entry "$@" ;;
esac
