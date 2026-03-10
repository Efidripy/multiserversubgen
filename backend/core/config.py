"""Centralised application configuration.

All environment-variable reads should go through :class:`Settings`.
This makes it easy to override values in tests and to document the
full set of supported options.

Usage::

    from core.config import Settings, get_settings

    settings = get_settings()
    print(settings.db_path)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Set


def _bool(val: str) -> bool:
    return val.strip().lower() in ("1", "true", "yes", "on")


def _parse_user_set(raw: str) -> Set[str]:
    return {u.strip() for u in raw.split(",") if u.strip()}


@dataclass
class Settings:
    """Application-wide configuration loaded from environment variables."""

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    project_dir: str = field(
        default_factory=lambda: os.getenv("PROJECT_DIR", "/opt/sub-manager")
    )
    web_path: str = field(
        default_factory=lambda: os.getenv("WEB_PATH", "").strip("/")
    )

    @property
    def db_path(self) -> str:
        return os.path.join(self.project_dir, "admin.db")

    @property
    def root_path(self) -> str:
        return f"/{self.web_path}" if self.web_path else ""

    # ------------------------------------------------------------------
    # Network / TLS
    # ------------------------------------------------------------------
    verify_tls: bool = field(
        default_factory=lambda: _bool(os.getenv("VERIFY_TLS", "true"))
    )
    ca_bundle_path: str = field(
        default_factory=lambda: os.getenv("CA_BUNDLE_PATH", "").strip()
    )
    allow_origins: List[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv(
                "ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if o.strip()
        ]
    )
    app_port: int = field(
        default_factory=lambda: int(os.getenv("APP_PORT", "666"))
    )

    # ------------------------------------------------------------------
    # Caching / Redis
    # ------------------------------------------------------------------
    cache_ttl: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL", "30"))
    )
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "").strip()
    )
    traffic_stats_cache_ttl: int = field(
        default_factory=lambda: int(os.getenv("TRAFFIC_STATS_CACHE_TTL", "20"))
    )
    traffic_stats_stale_ttl: int = field(
        default_factory=lambda: int(os.getenv("TRAFFIC_STATS_STALE_TTL", "120"))
    )
    online_clients_cache_ttl: int = field(
        default_factory=lambda: int(os.getenv("ONLINE_CLIENTS_CACHE_TTL", "20"))
    )
    online_clients_stale_ttl: int = field(
        default_factory=lambda: int(os.getenv("ONLINE_CLIENTS_STALE_TTL", "60"))
    )
    clients_cache_ttl: int = field(
        default_factory=lambda: int(os.getenv("CLIENTS_CACHE_TTL", "20"))
    )
    clients_cache_stale_ttl: int = field(
        default_factory=lambda: int(os.getenv("CLIENTS_CACHE_STALE_TTL", "180"))
    )

    # ------------------------------------------------------------------
    # Subscription rate limiting
    # ------------------------------------------------------------------
    sub_rate_limit_count: int = field(
        default_factory=lambda: int(os.getenv("SUB_RATE_LIMIT_COUNT", "30"))
    )
    sub_rate_limit_window_sec: int = field(
        default_factory=lambda: int(os.getenv("SUB_RATE_LIMIT_WINDOW_SEC", "60"))
    )

    # ------------------------------------------------------------------
    # Collector / polling
    # ------------------------------------------------------------------
    collector_base_interval_sec: int = field(
        default_factory=lambda: int(os.getenv("COLLECTOR_BASE_INTERVAL_SEC", "5"))
    )
    collector_max_interval_sec: int = field(
        default_factory=lambda: int(os.getenv("COLLECTOR_MAX_INTERVAL_SEC", "86400"))
    )
    collector_max_parallel: int = field(
        default_factory=lambda: int(os.getenv("COLLECTOR_MAX_PARALLEL", "4"))
    )

    # ------------------------------------------------------------------
    # Node history
    # ------------------------------------------------------------------
    node_history_enabled: bool = field(
        default_factory=lambda: _bool(os.getenv("NODE_HISTORY_ENABLED", "true"))
    )
    node_history_min_interval_sec: int = field(
        default_factory=lambda: int(os.getenv("NODE_HISTORY_MIN_INTERVAL_SEC", "30"))
    )
    node_history_retention_days: int = field(
        default_factory=lambda: int(os.getenv("NODE_HISTORY_RETENTION_DAYS", "30"))
    )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    audit_queue_batch_size: int = field(
        default_factory=lambda: int(os.getenv("AUDIT_QUEUE_BATCH_SIZE", "200"))
    )

    # ------------------------------------------------------------------
    # RBAC
    # ------------------------------------------------------------------
    role_viewers: Set[str] = field(
        default_factory=lambda: _parse_user_set(os.getenv("ROLE_VIEWERS", ""))
    )
    role_operators: Set[str] = field(
        default_factory=lambda: _parse_user_set(os.getenv("ROLE_OPERATORS", ""))
    )

    # ------------------------------------------------------------------
    # MFA / TOTP
    # ------------------------------------------------------------------
    mfa_totp_enabled: bool = field(
        default_factory=lambda: _bool(os.getenv("MFA_TOTP_ENABLED", "false"))
    )
    mfa_totp_users_raw: str = field(
        default_factory=lambda: os.getenv("MFA_TOTP_USERS", "").strip()
    )
    mfa_totp_ws_strict: bool = field(
        default_factory=lambda: _bool(os.getenv("MFA_TOTP_WS_STRICT", "false"))
    )

    # ------------------------------------------------------------------
    # AdGuard
    # ------------------------------------------------------------------
    adguard_collect_interval_sec: int = field(
        default_factory=lambda: int(os.getenv("ADGUARD_COLLECT_INTERVAL_SEC", "60"))
    )

    # ------------------------------------------------------------------
    # Observability stack URLs
    # ------------------------------------------------------------------
    prometheus_url: str = field(
        default_factory=lambda: os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090").strip()
    )
    loki_url: str = field(
        default_factory=lambda: os.getenv("LOKI_URL", "http://127.0.0.1:3100").strip()
    )
    grafana_url: str = field(
        default_factory=lambda: os.getenv("GRAFANA_URL", "http://127.0.0.1:3000").strip()
    )
    prometheus_basic_auth: str = field(
        default_factory=lambda: os.getenv("PROMETHEUS_BASIC_AUTH", "").strip()
    )
    loki_basic_auth: str = field(
        default_factory=lambda: os.getenv("LOKI_BASIC_AUTH", "").strip()
    )
    grafana_basic_auth: str = field(
        default_factory=lambda: os.getenv("GRAFANA_BASIC_AUTH", "").strip()
    )

    # ------------------------------------------------------------------
    # Read-only mode
    # ------------------------------------------------------------------
    read_only_mode: bool = field(
        default_factory=lambda: _bool(os.getenv("READ_ONLY_MODE", "false"))
    )

    def requests_verify(self):
        """Return the value to pass as ``verify=`` to :mod:`requests`."""
        if not self.verify_tls:
            return False
        if self.ca_bundle_path:
            return self.ca_bundle_path
        return True


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the singleton :class:`Settings` instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset the singleton (useful in tests)."""
    global _settings
    _settings = None
