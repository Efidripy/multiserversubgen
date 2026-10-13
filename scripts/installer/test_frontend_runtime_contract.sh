#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/bin:/bin:${PATH:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
INSTALLER="$REPO_ROOT/scripts/installer/install.sh"
ORIGINAL_PATH="$PATH"
WORK_DIR="$(mktemp -d)"
FAKE_BIN="$WORK_DIR/bin"
RUNTIME_HELPER="$WORK_DIR/frontend-runtime.sh"
export NODESOURCE_KEYRING="$WORK_DIR/apt/keyrings/multiserversubgen-nodesource.gpg"
export NODESOURCE_SOURCE_FILE="$WORK_DIR/apt/sources.list.d/multiserversubgen-nodesource.sources"
export NODESOURCE_PREFERENCES_FILE="$WORK_DIR/apt/preferences.d/multiserversubgen-nodesource-nodejs"

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$FAKE_BIN"
sed -n '/^# frontend-runtime-contract:start$/,/^# frontend-runtime-contract:end$/p' "$INSTALLER" \
    | sed '1d;$d' > "$RUNTIME_HELPER"
# shellcheck source=/dev/null
source "$RUNTIME_HELPER"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_equals() {
    local expected="$1"
    local actual="$2"
    local description="$3"
    [ "$actual" = "$expected" ] || fail "$description: expected '$expected', got '$actual'"
}

clear_fake_runtime() {
    rm -f "$FAKE_BIN/node" "$FAKE_BIN/npm" "$WORK_DIR/apt-calls"
    rm -rf "$WORK_DIR/apt"
    PATH="$FAKE_BIN:$ORIGINAL_PATH"
    hash -r
}

write_fake_runtime() {
    local node_version="$1"
    local npm_version="$2"

    cat > "$FAKE_BIN/node" <<EOF
#!/usr/bin/env bash
printf '%s\n' '$node_version'
EOF
    chmod +x "$FAKE_BIN/node"
    if [ -n "$npm_version" ]; then
        cat > "$FAKE_BIN/npm" <<EOF
#!/usr/bin/env bash
printf '%s\n' '$npm_version'
EOF
        chmod +x "$FAKE_BIN/npm"
    fi
    hash -r
}

write_unavailable_fake_npm() {
    cat > "$FAKE_BIN/npm" <<'EOF'
#!/usr/bin/env bash
exit 127
EOF
    chmod +x "$FAKE_BIN/npm"
    hash -r
}

write_unavailable_fake_node() {
    cat > "$FAKE_BIN/node" <<'EOF'
#!/usr/bin/env bash
exit 127
EOF
    chmod +x "$FAKE_BIN/node"
    hash -r
}

prepare_nodesource_bootstrap_mocks() {
    dpkg() {
        [ "$1" = "--print-architecture" ] || return 1
        printf '%s\n' "amd64"
    }
    curl() {
        local destination=""
        local previous=""
        local argument
        for argument in "$@"; do
            if [ "$previous" = "-o" ]; then
                destination="$argument"
                break
            fi
            previous="$argument"
        done
        [ -n "$destination" ] || return 1
        printf '%s\n' "test-key" > "$destination"
    }
    gpg() {
        local argument output="" previous=""
        for argument in "$@"; do
            if [ "$previous" = "--output" ]; then
                output="$argument"
                break
            fi
            previous="$argument"
        done
        if [[ " $* " == *" --show-keys "* ]]; then
            printf '%s\n' "fpr:::::::::${NODESOURCE_KEY_FINGERPRINT}:"
            return 0
        fi
        [ -n "$output" ] || return 1
        printf '%s\n' "test-keyring" > "$output"
    }
    apt_install_missing() {
        printf 'prerequisites:%s\n' "$*" >> "$WORK_DIR/apt-calls"
    }
    apt_update() {
        printf '%s\n' "apt-update" >> "$WORK_DIR/apt-calls"
    }
    apt-cache() {
        [ "$1" = "policy" ] && [ "$2" = "nodejs" ] || return 1
        printf '%s\n' " https://deb.nodesource.com/node_22.x nodistro/main amd64 Packages"
    }
    apt_install() {
        printf 'install:%s\n' "$*" >> "$WORK_DIR/apt-calls"
        [ "$*" = "nodejs" ] || return 1
        write_fake_runtime "v22.17.0" "10.9.2"
    }
}

test_supported_bundled_runtime_never_calls_apt() {
    clear_fake_runtime
    write_fake_runtime "v22.17.0" "10.9.2"
    apt_install_missing() { printf '%s\n' "$*" >> "$WORK_DIR/apt-calls"; return 1; }

    ensure_supported_frontend_runtime || fail "supported bundled Node/npm runtime must pass"
    [ ! -e "$WORK_DIR/apt-calls" ] || fail "supported bundled runtime must not invoke APT"
}

test_missing_node_bootstraps_signed_nodesource_node22() {
    clear_fake_runtime
    write_unavailable_fake_node
    prepare_nodesource_bootstrap_mocks

    ensure_supported_frontend_runtime || fail "nodejs bootstrap with bundled npm must pass"
    assert_equals $'prerequisites:ca-certificates curl gnupg\napt-update\ninstall:nodejs' \
        "$(cat "$WORK_DIR/apt-calls")" "NodeSource bootstrap sequence"
    grep -Fq "URIs: https://deb.nodesource.com/node_22.x" "$NODESOURCE_SOURCE_FILE" \
        || fail "NodeSource Node 22 source must be written"
    grep -Fq "Signed-By: ${NODESOURCE_KEYRING}" "$NODESOURCE_SOURCE_FILE" \
        || fail "NodeSource source must use its dedicated keyring"
    grep -Fxq "Package: nodejs" "$NODESOURCE_PREFERENCES_FILE" \
        || fail "NodeSource preference must be limited to nodejs"
    grep -Fq "Pin: origin deb.nodesource.com" "$NODESOURCE_PREFERENCES_FILE" \
        || fail "NodeSource preference must pin the repository origin"
}

test_incompatible_runtime_upgrades_through_nodesource_without_standalone_npm() {
    clear_fake_runtime
    write_fake_runtime "v18.20.0" "9.9.4"
    prepare_nodesource_bootstrap_mocks

    ensure_supported_frontend_runtime || fail "unsupported runtime must upgrade to NodeSource Node 22"
    grep -Fxq "install:nodejs" "$WORK_DIR/apt-calls" || fail "upgrade must install only nodejs"
    if grep -Eq '(^|[[:space:]])npm($|[[:space:]])' "$WORK_DIR/apt-calls"; then
        fail "upgrade must never request standalone APT npm"
    fi
}

test_missing_bundled_npm_bootstraps_nodejs_without_npm_package() {
    clear_fake_runtime
    write_fake_runtime "v22.17.0" ""
    write_unavailable_fake_npm
    prepare_nodesource_bootstrap_mocks

    ensure_supported_frontend_runtime || fail "missing bundled npm must be repaired by NodeSource nodejs"
    grep -Fxq "install:nodejs" "$WORK_DIR/apt-calls" || fail "npm repair must install nodejs"
    if grep -Eq '(^|[[:space:]])npm($|[[:space:]])' "$WORK_DIR/apt-calls"; then
        fail "npm repair must never request standalone APT npm"
    fi
}

test_untrusted_nodesource_key_never_activates_repository() {
    clear_fake_runtime
    write_unavailable_fake_node
    prepare_nodesource_bootstrap_mocks
    gpg() {
        local argument output="" previous=""
        for argument in "$@"; do
            if [ "$previous" = "--output" ]; then
                output="$argument"
                break
            fi
            previous="$argument"
        done
        if [[ " $* " == *" --show-keys "* ]]; then
            printf '%s\n' "fpr:::::::::DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF:"
            return 0
        fi
        [ -n "$output" ] || return 1
        printf '%s\n' "untrusted-keyring" > "$output"
    }

    if ensure_supported_frontend_runtime >"$WORK_DIR/untrusted-key.out" 2>&1; then
        fail "untrusted NodeSource key must fail"
    fi
    [ ! -e "$NODESOURCE_SOURCE_FILE" ] || fail "untrusted key must not activate a repository"
    [ ! -e "$WORK_DIR/apt-calls" ] || ! grep -Fq "install:nodejs" "$WORK_DIR/apt-calls" \
        || fail "untrusted key must not install nodejs"
    grep -Fq "fingerprint" "$WORK_DIR/untrusted-key.out" || fail "untrusted-key failure must explain fingerprint rejection"
}

test_apt_update_failure_restores_previous_nodesource_configuration() {
    clear_fake_runtime
    write_unavailable_fake_node
    mkdir -p "$(dirname "$NODESOURCE_KEYRING")" "$(dirname "$NODESOURCE_SOURCE_FILE")" "$(dirname "$NODESOURCE_PREFERENCES_FILE")"
    printf '%s\n' "old-keyring" > "$NODESOURCE_KEYRING"
    printf '%s\n' "old-source" > "$NODESOURCE_SOURCE_FILE"
    printf '%s\n' "old-preferences" > "$NODESOURCE_PREFERENCES_FILE"
    prepare_nodesource_bootstrap_mocks
    apt_update() {
        printf '%s\n' "apt-update" >> "$WORK_DIR/apt-calls"
        return 1
    }

    if ensure_supported_frontend_runtime >"$WORK_DIR/update-failure.out" 2>&1; then
        fail "NodeSource apt update failure must fail"
    fi
    assert_equals "old-keyring" "$(cat "$NODESOURCE_KEYRING")" "restored keyring"
    assert_equals "old-source" "$(cat "$NODESOURCE_SOURCE_FILE")" "restored source"
    assert_equals "old-preferences" "$(cat "$NODESOURCE_PREFERENCES_FILE")" "restored preference"
    [ ! -e "$WORK_DIR/apt-calls" ] || ! grep -Fq "install:nodejs" "$WORK_DIR/apt-calls" \
        || fail "failed apt update must not install nodejs"
}

test_supported_bundled_runtime_never_calls_apt
test_missing_node_bootstraps_signed_nodesource_node22
test_incompatible_runtime_upgrades_through_nodesource_without_standalone_npm
test_missing_bundled_npm_bootstraps_nodejs_without_npm_package
test_untrusted_nodesource_key_never_activates_repository
test_apt_update_failure_restores_previous_nodesource_configuration

echo "frontend runtime installer contract: passed"
