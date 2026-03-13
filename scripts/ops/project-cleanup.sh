#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLEANUP_MODE="${CLEANUP_MODE:-safe}"
PRUNE_MCP_CACHE="${PRUNE_MCP_CACHE:-false}"

cd "$REPO_ROOT"

log() {
    printf '%s\n' "$*"
}

remove_if_exists() {
    local path="$1"
    if [ -e "$path" ]; then
        if rm -rf "$path" 2>/dev/null; then
            log "removed: $path"
        else
            log "skipped (busy/permission): $path"
        fi
    fi
}

cleanup_safe() {
    local targets=(
        ".tmp"
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

    find "$REPO_ROOT" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
    find "$REPO_ROOT" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
}

cleanup_deep() {
    cleanup_safe
    remove_if_exists ".vscode"

    if [ "$PRUNE_MCP_CACHE" = "true" ]; then
        remove_if_exists "tools/mcp/node_modules"
    fi
}

log "project cleanup mode: $CLEANUP_MODE"
log "repo root: $REPO_ROOT"
log "preserved local-only paths:"
log "  - .local_project_docs/"
log "  - .local_snapshots/"
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
