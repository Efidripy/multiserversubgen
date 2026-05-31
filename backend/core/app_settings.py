from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, Set


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _parse_bool(raw_value: str | None) -> bool | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip().strip("\"'")
    if not value:
        return None
    lowered = value.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    return None


def _env_optional_bool(name: str) -> bool | None:
    return _parse_bool(os.getenv(name))


def _detect_grafana_url(project_dir: str) -> str:
    env_value = os.getenv("GRAFANA_URL", "").strip()
    if env_value:
        return env_value

    default_url = "http://127.0.0.1:3000"
    ini_candidates = [
        os.getenv("GRAFANA_INI_PATH", "").strip(),
        "/etc/grafana/grafana.ini",
        os.path.join(project_dir, "grafana.ini"),
    ]

    for path in ini_candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            addr = "127.0.0.1"
            port = "3000"
            in_server = False
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line:
                        continue
                    if line.startswith("["):
                        in_server = line.lower() == "[server]"
                        continue
                    if not in_server or line.startswith(";") or line.startswith("#"):
                        continue

                    if line.lower().startswith("http_addr") and "=" in line:
                        candidate = line.split("=", 1)[1].strip()
                        if candidate and candidate not in ("0.0.0.0", "::"):
                            addr = candidate
                    elif line.lower().startswith("http_port") and "=" in line:
                        candidate = line.split("=", 1)[1].strip()
                        if candidate.isdigit():
                            port = candidate

            return f"http://{addr}:{port}"
        except OSError:
            continue

    return default_url


def _read_monitoring_enabled_from_install_logs(project_dir: str) -> bool | None:
    candidate_paths = [
        os.getenv("INSTALL_LOG_FILE", "").strip(),
        "/opt/.sub_manager_install.log",
        os.path.join(project_dir, ".sub_manager_install.log"),
    ]
    for path in candidate_paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    match = re.match(r"\s*MONITORING_ENABLED\s*=\s*(.+?)\s*$", line)
                    if not match:
                        continue
                    parsed = _parse_bool(match.group(1))
                    if parsed is not None:
                        return parsed
        except OSError:
            continue
    return None


def _env_csv_set(name: str) -> Set[str]:
    raw = os.getenv(name, "").strip()
    return {item.strip() for item in raw.split(",") if item.strip()}


@dataclass(frozen=True)
class AppSettings:
    project_dir: str
    web_path: str
    grafana_web_path: str
    monitoring_enabled: bool
    root_path: str
    cache_ttl: int
    allow_origins: list[str]
    verify_tls: bool
    ca_bundle_path: str
    read_only_mode: bool
    sub_rate_limit_count: int
    sub_rate_limit_window_sec: int
    traffic_stats_cache_ttl: int
    online_clients_cache_ttl: int
    traffic_stats_stale_ttl: int
    online_clients_stale_ttl: int
    clients_cache_ttl: int
    clients_cache_stale_ttl: int
    redis_url: str
    collector_base_interval_sec: int
    collector_max_interval_sec: int
    collector_max_parallel: int
    collector_warming_interval_1_sec: int
    collector_warming_interval_2_sec: int
    collector_warming_interval_3_sec: int
    collector_active_interval_sec: int
    collector_idle_interval_sec: int
    collector_ultra_idle_interval_sec: int
    collector_idle_after_sec: int
    collector_ultra_idle_after_sec: int
    node_history_enabled: bool
    node_history_min_interval_sec: int
    node_history_retention_days: int
    audit_queue_batch_size: int
    audit_idle_sleep_sec: float
    audit_active_sleep_sec: float
    role_viewers: Set[str]
    role_operators: Set[str]
    mfa_totp_enabled: bool
    mfa_totp_users: Dict[str, str]
    mfa_totp_ws_strict: bool
    adguard_collect_interval_sec: int
    prometheus_url: str
    loki_url: str
    grafana_url: str
    prometheus_basic_auth: str
    loki_basic_auth: str
    grafana_basic_auth: str


def load_app_settings(*, parse_mfa_users: Callable[[str], Dict[str, str]]) -> AppSettings:
    project_dir = os.getenv("PROJECT_DIR", "/opt/sub-manager")
    web_path = os.getenv("WEB_PATH", "").strip("/")
    monitoring_enabled = _env_optional_bool("MONITORING_ENABLED")
    if monitoring_enabled is None:
        monitoring_enabled = _read_monitoring_enabled_from_install_logs(project_dir)
    if monitoring_enabled is None:
        monitoring_enabled = True
    allow_origins_raw = os.getenv(
        "ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    return AppSettings(
        project_dir=project_dir,
        web_path=web_path,
        grafana_web_path=os.getenv("GRAFANA_WEB_PATH", "grafana").strip("/"),
        monitoring_enabled=monitoring_enabled,
        root_path=f"/{web_path}" if web_path else "",
        cache_ttl=int(os.getenv("CACHE_TTL", "30")),
        allow_origins=[origin.strip() for origin in allow_origins_raw.split(",") if origin.strip()],
        verify_tls=_env_bool("VERIFY_TLS", "false"),
        ca_bundle_path=os.getenv("CA_BUNDLE_PATH", "").strip(),
        read_only_mode=_env_bool("READ_ONLY_MODE", "false"),
        sub_rate_limit_count=int(os.getenv("SUB_RATE_LIMIT_COUNT", "30")),
        sub_rate_limit_window_sec=int(os.getenv("SUB_RATE_LIMIT_WINDOW_SEC", "60")),
        traffic_stats_cache_ttl=int(os.getenv("TRAFFIC_STATS_CACHE_TTL", "20")),
        online_clients_cache_ttl=int(os.getenv("ONLINE_CLIENTS_CACHE_TTL", "20")),
        traffic_stats_stale_ttl=int(os.getenv("TRAFFIC_STATS_STALE_TTL", "120")),
        online_clients_stale_ttl=int(os.getenv("ONLINE_CLIENTS_STALE_TTL", "60")),
        clients_cache_ttl=int(os.getenv("CLIENTS_CACHE_TTL", "20")),
        clients_cache_stale_ttl=int(os.getenv("CLIENTS_CACHE_STALE_TTL", "180")),
        redis_url=os.getenv("REDIS_URL", "").strip(),
        collector_base_interval_sec=int(os.getenv("COLLECTOR_BASE_INTERVAL_SEC", "5")),
        collector_max_interval_sec=int(os.getenv("COLLECTOR_MAX_INTERVAL_SEC", "86400")),
        collector_max_parallel=int(os.getenv("COLLECTOR_MAX_PARALLEL", "4")),
        collector_warming_interval_1_sec=int(os.getenv("COLLECTOR_WARMING_INTERVAL_1_SEC", "30")),
        collector_warming_interval_2_sec=int(os.getenv("COLLECTOR_WARMING_INTERVAL_2_SEC", "60")),
        collector_warming_interval_3_sec=int(os.getenv("COLLECTOR_WARMING_INTERVAL_3_SEC", "120")),
        collector_active_interval_sec=int(os.getenv("COLLECTOR_ACTIVE_INTERVAL_SEC", "120")),
        collector_idle_interval_sec=int(os.getenv("COLLECTOR_IDLE_INTERVAL_SEC", "3600")),
        collector_ultra_idle_interval_sec=int(os.getenv("COLLECTOR_ULTRA_IDLE_INTERVAL_SEC", "86400")),
        collector_idle_after_sec=int(os.getenv("COLLECTOR_IDLE_AFTER_SEC", "900")),
        collector_ultra_idle_after_sec=int(os.getenv("COLLECTOR_ULTRA_IDLE_AFTER_SEC", "86400")),
        node_history_enabled=_env_bool("NODE_HISTORY_ENABLED", "true"),
        node_history_min_interval_sec=int(os.getenv("NODE_HISTORY_MIN_INTERVAL_SEC", "30")),
        node_history_retention_days=int(os.getenv("NODE_HISTORY_RETENTION_DAYS", "30")),
        audit_queue_batch_size=int(os.getenv("AUDIT_QUEUE_BATCH_SIZE", "200")),
        audit_idle_sleep_sec=float(os.getenv("AUDIT_IDLE_SLEEP_SEC", "2.0")),
        audit_active_sleep_sec=float(os.getenv("AUDIT_ACTIVE_SLEEP_SEC", "0.2")),
        role_viewers=_env_csv_set("ROLE_VIEWERS"),
        role_operators=_env_csv_set("ROLE_OPERATORS"),
        mfa_totp_enabled=_env_bool("MFA_TOTP_ENABLED", "false"),
        mfa_totp_users=parse_mfa_users(os.getenv("MFA_TOTP_USERS", "").strip()),
        mfa_totp_ws_strict=_env_bool("MFA_TOTP_WS_STRICT", "false"),
        adguard_collect_interval_sec=int(os.getenv("ADGUARD_COLLECT_INTERVAL_SEC", "60")),
        prometheus_url=os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090").strip(),
        loki_url=os.getenv("LOKI_URL", "http://127.0.0.1:3100").strip(),
        grafana_url=_detect_grafana_url(project_dir),
        prometheus_basic_auth=os.getenv("PROMETHEUS_BASIC_AUTH", "").strip(),
        loki_basic_auth=os.getenv("LOKI_BASIC_AUTH", "").strip(),
        grafana_basic_auth=os.getenv("GRAFANA_BASIC_AUTH", "").strip(),
    )
