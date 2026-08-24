#!/bin/bash
set -euo pipefail

SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." 2>/dev/null && pwd -P)" || {
    printf '%s\n' "cleanup refused: cannot resolve repository root" >&2
    exit 1
}
CLEANUP_MODE="${CLEANUP_MODE:-safe}"
PRUNE_MCP_CACHE="${PRUNE_MCP_CACHE:-false}"
CLEANUP_DRY_RUN="${CLEANUP_DRY_RUN:-false}"

cd "$REPO_ROOT"

if ! command -v git >/dev/null 2>&1; then
    printf '%s\n' "cleanup refused: git is required to verify repository root" >&2
    exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$GIT_ROOT" ] || [ "$GIT_ROOT" != "$REPO_ROOT" ]; then
    printf '%s\n' "cleanup refused: resolved path is not the project Git root" >&2
    exit 1
fi

log() {
    printf '%s\n' "$*"
}

remove_if_exists() {
    local path="$1"
    if [ -e "$path" ]; then
        if [ "$CLEANUP_DRY_RUN" = "true" ]; then
            log "would remove: $path"
            return 0
        fi
        if rm -rf "$path" 2>/dev/null; then
            log "removed: $path"
        else
            log "skipped (busy/permission): $path"
        fi
    fi
}

cleanup_python_caches() {
    if [ "$CLEANUP_DRY_RUN" = "true" ]; then
        find "$REPO_ROOT" -type d -name "__pycache__" -prune -print 2>/dev/null |
            while IFS= read -r path; do log "would remove: $path"; done
        find "$REPO_ROOT" -type f \( -name "*.pyc" -o -name "*.pyo" \) -print 2>/dev/null |
            while IFS= read -r path; do log "would remove: $path"; done
        return 0
    fi
    find "$REPO_ROOT" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
    find "$REPO_ROOT" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
}

cleanup_safe() {
    local targets=(
        ".pytest_cache"
        ".ruff_cache"
        ".npm-cache"
        "frontend/dist"
        "backend/build"
        "installer-sync-first-clean.tgz"
        "installer-sync-live.tgz"
        "xui-core-patch.tgz"
    )

    local target
    for target in "${targets[@]}"; do
        remove_if_exists "$target"
    done

    cleanup_python_caches
}

cleanup_deep() {
    cleanup_safe

    if [ "$PRUNE_MCP_CACHE" = "true" ]; then
        remove_if_exists "tools/mcp/node_modules"
    fi
}

log "project cleanup mode: $CLEANUP_MODE"
log "dry run: $CLEANUP_DRY_RUN"
log "repo root: $REPO_ROOT"
log "preserved local-only paths:"
log "  - .local_project_docs/"
log "  - .local_snapshots/"
log "  - .tmp/"
log "  - .vscode/"
log "  - scripts/installer/templates/.local-randomfakehtml/"
log "  - scripts/installer/templates/.local-randomfakehtml-sample/"
log "  - tools/mcp/ runtime (unless PRUNE_MCP_CACHE=true)"

case "$CLEANUP_MODE" in
    safe)
        cleanup_safe
        ;;
    deep)
        cleanup_deep
        ;;
    *)
        echo "Unknown CLEANUP_MODE: $CLEANUP_MODE" >&2
        exit 1
        ;;
esac

log "cleanup complete"
