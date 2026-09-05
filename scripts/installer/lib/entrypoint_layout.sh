#!/usr/bin/env bash

# Resolves the public install/update wrapper target before the privileged
# installer loads any runtime state. The full source-layout validation lives in
# source_layout.sh and runs again inside the selected entrypoint.

mssg_resolve_installer_entrypoint() {
    local source_root="$1"
    local entrypoint_name="$2"
    local candidate

    for candidate in \
        "$source_root/scripts/installer/${entrypoint_name}.sh" \
        "$source_root/installer/${entrypoint_name}.sh"; do
        if [ -f "$candidate" ] && [ ! -L "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    printf 'Unsupported installer entrypoint layout near %s. Refusing to continue.\n' "$source_root" >&2
    return 1
}
