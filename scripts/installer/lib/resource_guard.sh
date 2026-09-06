#!/bin/bash

resource_guard_free_mb() {
    local path="${1:-/}"
    df -Pm "$path" 2>/dev/null | awk 'NR==2 {print $4}'
}

resource_guard_mem_mb() {
    awk '/MemTotal:/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null
}

resource_guard_cpu_count() {
    nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1
}

resource_guard_detect_profile() {
    RESOURCE_CPU_COUNT="${RESOURCE_CPU_COUNT:-$(resource_guard_cpu_count)}"
    RESOURCE_MEM_MB="${RESOURCE_MEM_MB:-$(resource_guard_mem_mb)}"
    RESOURCE_ROOT_FREE_MB="${RESOURCE_ROOT_FREE_MB:-$(resource_guard_free_mb /)}"
    RESOURCE_LOW_MEM_THRESHOLD_MB="${RESOURCE_LOW_MEM_THRESHOLD_MB:-1536}"
    RESOURCE_VERY_LOW_MEM_THRESHOLD_MB="${RESOURCE_VERY_LOW_MEM_THRESHOLD_MB:-1024}"
    RESOURCE_LOW_RESOURCE_MODE="${RESOURCE_LOW_RESOURCE_MODE:-false}"
    RESOURCE_VERY_LOW_RESOURCE_MODE="${RESOURCE_VERY_LOW_RESOURCE_MODE:-false}"

    if [ "${RESOURCE_MEM_MB:-0}" -le "${RESOURCE_LOW_MEM_THRESHOLD_MB}" ] || [ "${RESOURCE_CPU_COUNT:-1}" -le 2 ]; then
        RESOURCE_LOW_RESOURCE_MODE="true"
    fi
    if [ "${RESOURCE_MEM_MB:-0}" -le "${RESOURCE_VERY_LOW_MEM_THRESHOLD_MB}" ] || [ "${RESOURCE_CPU_COUNT:-1}" -le 1 ]; then
        RESOURCE_VERY_LOW_RESOURCE_MODE="true"
    fi

    export RESOURCE_CPU_COUNT RESOURCE_MEM_MB RESOURCE_ROOT_FREE_MB
    export RESOURCE_LOW_MEM_THRESHOLD_MB RESOURCE_VERY_LOW_MEM_THRESHOLD_MB
    export RESOURCE_LOW_RESOURCE_MODE RESOURCE_VERY_LOW_RESOURCE_MODE
}

resource_guard_print_summary() {
    local scope="${1:-host}"
    resource_guard_detect_profile
    echo "Resource profile (${scope}): cpu=${RESOURCE_CPU_COUNT} mem_mb=${RESOURCE_MEM_MB} free_root_mb=${RESOURCE_ROOT_FREE_MB} low_resource=${RESOURCE_LOW_RESOURCE_MODE} very_low_resource=${RESOURCE_VERY_LOW_RESOURCE_MODE}"
}

resource_guard_project_root() {
    local source_path="${BASH_SOURCE[0]}"
    local source_dir="${source_path%/*}"
    local project_root

    if [ "$source_dir" = "$source_path" ]; then
        source_dir="."
    fi
    project_root="$(cd "$source_dir/../../.." 2>/dev/null && pwd -P)" || return 1

    if [ ! -d "$project_root/backend" ] || [ ! -d "$project_root/frontend" ]; then
        return 1
    fi
    printf '%s\n' "$project_root"
}

resource_guard_try_safe_cleanup() {
    local path="${1:-/}"
    local before_free after_free
    local project_root

    resource_guard_detect_profile
    before_free="$(resource_guard_free_mb "$path")"
    echo "Low-resource host: trying safe disk cleanup on ${path} before aborting."

    apt-get clean >/dev/null 2>&1 || true
    rm -rf -- /root/.npm /root/.npm-cache /root/.cache/pip 2>/dev/null || true
    project_root="$(resource_guard_project_root 2>/dev/null || true)"
    if [ -n "$project_root" ]; then
        rm -rf -- "$project_root/frontend/node_modules" "$project_root/frontend/.vite" "$project_root/frontend/dist" 2>/dev/null || true
    fi

    after_free="$(resource_guard_free_mb "$path")"
    echo "Disk cleanup result: ${before_free:-unknown}MB -> ${after_free:-unknown}MB free on ${path}."
}

resource_guard_require_free_mb() {
    local min_free_mb="$1"
    local reason="$2"
    local path="${3:-/}"
    local free_mb

    free_mb="$(resource_guard_free_mb "$path")"
    if [ -z "$free_mb" ]; then
        echo "Warning: unable to detect free disk space for ${path}; continuing."
        return 0
    fi

    if [ "$free_mb" -lt "$min_free_mb" ]; then
        resource_guard_detect_profile
        resource_guard_try_safe_cleanup "$path"
        free_mb="$(resource_guard_free_mb "$path")"
    fi

    if [ "$free_mb" -lt "$min_free_mb" ]; then
        echo "ERROR: not enough free disk space ${reason}."
        echo "  path: ${path}"
        echo "  required_mb: ${min_free_mb}"
        echo "  available_mb: ${free_mb}"
        echo "  free some space and retry."
        return 1
    fi

    echo "Disk check OK ${reason}: ${free_mb}MB free on ${path}."
}

resource_guard_apply_runtime_defaults() {
    resource_guard_detect_profile
    if [ "${RESOURCE_LOW_RESOURCE_MODE}" != "true" ]; then
        return 0
    fi

    if [ -z "${TRAFFIC_MAX_WORKERS:-}" ] || [ "${TRAFFIC_MAX_WORKERS}" = "6" ] || [ "${TRAFFIC_MAX_WORKERS}" = "2" ]; then
        TRAFFIC_MAX_WORKERS="1"
    fi
    if [ -z "${COLLECTOR_MAX_PARALLEL:-}" ] || [ "${COLLECTOR_MAX_PARALLEL}" = "4" ]; then
        COLLECTOR_MAX_PARALLEL="1"
    fi
    if [ -z "${COLLECTOR_BASE_INTERVAL_SEC:-}" ] || [ "${COLLECTOR_BASE_INTERVAL_SEC}" = "5" ] || [ "${COLLECTOR_BASE_INTERVAL_SEC}" = "10" ] || [ "${COLLECTOR_BASE_INTERVAL_SEC}" = "15" ]; then
        COLLECTOR_BASE_INTERVAL_SEC="20"
    fi
    if [ -z "${COLLECTOR_MAX_INTERVAL_SEC:-}" ] || [ "${COLLECTOR_MAX_INTERVAL_SEC}" = "60" ] || [ "${COLLECTOR_MAX_INTERVAL_SEC}" = "90" ] || [ "${COLLECTOR_MAX_INTERVAL_SEC}" = "86400" ]; then
        COLLECTOR_MAX_INTERVAL_SEC="120"
    fi
    if [ -z "${AUDIT_QUEUE_BATCH_SIZE:-}" ] || [ "${AUDIT_QUEUE_BATCH_SIZE}" = "200" ]; then
        AUDIT_QUEUE_BATCH_SIZE="50"
    fi

    if [ "${RESOURCE_VERY_LOW_RESOURCE_MODE}" = "true" ]; then
        TRAFFIC_MAX_WORKERS="1"
        COLLECTOR_MAX_PARALLEL="1"
        COLLECTOR_BASE_INTERVAL_SEC="30"
        COLLECTOR_MAX_INTERVAL_SEC="180"
        AUDIT_QUEUE_BATCH_SIZE="30"
    fi
}

resource_guard_cpu_limit_percent() {
    resource_guard_detect_profile
    if [ "${RESOURCE_VERY_LOW_RESOURCE_MODE}" = "true" ]; then
        printf "%s" "${RESOURCE_CPU_LIMIT_VERY_LOW_PERCENT:-45}"
        return 0
    fi
    if [ "${RESOURCE_LOW_RESOURCE_MODE}" = "true" ]; then
        printf "%s" "${RESOURCE_CPU_LIMIT_LOW_PERCENT:-60}"
        return 0
    fi
    printf "0"
}

resource_guard_run_heavy() {
    local cpu_limit
    cpu_limit="$(resource_guard_cpu_limit_percent)"

    if [ "${cpu_limit:-0}" -gt 0 ] && command -v cpulimit >/dev/null 2>&1; then
        "$@" &
        local cmd_pid=$!

        cpulimit -f -q -l "$cpu_limit" -p "$cmd_pid" >/dev/null 2>&1 || true

        wait "$cmd_pid"
        return $?
    fi

    if [ "${cpu_limit:-0}" -gt 0 ] && command -v nice >/dev/null 2>&1; then
        nice -n 15 "$@"
        return $?
    fi

    "$@"
}

resource_guard_export_build_env() {
    local max_jobs

    resource_guard_detect_profile

    export PIP_DISABLE_PIP_VERSION_CHECK=1
    export PIP_NO_CACHE_DIR=1
    export PIP_NO_COMPILE=1
    export PIP_PROGRESS_BAR=off
    export PIP_ROOT_USER_ACTION=ignore
    export npm_config_audit=false
    export npm_config_fund=false
    export npm_config_update_notifier=false
    export npm_config_loglevel=warn
    export CI=true

    max_jobs="${RESOURCE_CPU_COUNT:-1}"
    if [ "$max_jobs" -gt 4 ]; then
        max_jobs=4
    fi
    if [ "$max_jobs" -lt 1 ]; then
        max_jobs=1
    fi

    if [ "${RESOURCE_LOW_RESOURCE_MODE}" = "true" ]; then
        max_jobs=1
        if [[ " ${NODE_OPTIONS:-} " != *" --max-old-space-size="* ]]; then
            export NODE_OPTIONS="${NODE_OPTIONS:+${NODE_OPTIONS} }--max-old-space-size=384"
        fi
        export MAKEFLAGS=-j1
        export UV_THREADPOOL_SIZE=1
    fi
    if [ "${RESOURCE_VERY_LOW_RESOURCE_MODE}" = "true" ]; then
        if [[ " ${NODE_OPTIONS:-} " != *" --max-old-space-size="* ]]; then
            export NODE_OPTIONS="${NODE_OPTIONS:+${NODE_OPTIONS} }--max-old-space-size=512"
        else
            export NODE_OPTIONS="$(printf "%s" "${NODE_OPTIONS}" | sed 's/--max-old-space-size=[0-9][0-9]*/--max-old-space-size=512/g')"
        fi
    fi

    export npm_config_jobs="$max_jobs"
}

resource_guard_should_skip_optional_logs() {
    resource_guard_detect_profile
    [ "${RESOURCE_VERY_LOW_RESOURCE_MODE}" = "true" ]
}

resource_guard_restart_services_sequentially() {
    local service
    local service_timeout

    _rg_systemctl_with_timeout() {
        local timeout_sec="$1"
        shift
        if command -v timeout >/dev/null 2>&1; then
            timeout "$timeout_sec" "$@"
            return $?
        fi
        "$@"
    }

    resource_guard_detect_profile
    systemctl daemon-reload >/dev/null 2>&1 || true
    service_timeout="${RESOURCE_SYSTEMCTL_TIMEOUT_SEC:-60}"

    for service in "$@"; do
        [ -n "$service" ] || continue
        echo "Service step: ${service} (timeout ${service_timeout}s)"
        systemctl enable "$service" >/dev/null 2>&1 || true
        if systemctl is-active --quiet "$service"; then
            if ! _rg_systemctl_with_timeout "$service_timeout" systemctl restart "$service" >/dev/null 2>&1; then
                echo "⚠️ restart timeout/failure for ${service}; trying start."
                _rg_systemctl_with_timeout "$service_timeout" systemctl start "$service" >/dev/null 2>&1 || true
            fi
        else
            if ! _rg_systemctl_with_timeout "$service_timeout" systemctl start "$service" >/dev/null 2>&1; then
                echo "⚠️ start timeout/failure for ${service}."
            fi
        fi
        if systemctl is-active --quiet "$service"; then
            echo "✓ ${service} is active"
        else
            echo "⚠️ ${service} is not active after restart attempt"
        fi
        if [ "${RESOURCE_LOW_RESOURCE_MODE}" = "true" ]; then
            sleep "${RESOURCE_SERVICE_SETTLE_SEC:-3}"
        fi
    done
}
