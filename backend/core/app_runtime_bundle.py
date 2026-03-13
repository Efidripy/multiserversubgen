from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Dict

from client_manager import ClientManager
from inbound_manager import InboundManager
from server_monitor import ServerMonitor, ThreeXUIMonitor
from services.adguard_monitor import AdGuardMonitor
from services.adguard_runtime import AdGuardRuntime
from services.clients_runtime import ClientsRuntime
from services.collector import SnapshotCollector
from services.metrics_runtime import MetricsRuntime
from services.live_stats_runtime import LiveStatsRuntime
from services.node_service import NodeService
from services.request_runtime import RequestRuntime
from services.runtime_support import AuditQueueRuntime, RedisJsonCache
from shared.metrics_registry import MetricsRegistry, build_metrics_registry


@dataclass
class AppRuntimeBundle:
    inbound_mgr: InboundManager
    client_mgr: ClientManager
    server_monitor: ServerMonitor
    xui_monitor: ThreeXUIMonitor
    adguard_monitor: AdGuardMonitor
    node_service: NodeService
    logger: logging.Logger
    metrics: MetricsRegistry
    snapshot_collector: SnapshotCollector
    metrics_cache: Dict
    metrics_cache_lock: Lock
    audit_runtime: AuditQueueRuntime
    adguard_runtime: AdGuardRuntime
    request_runtime: RequestRuntime
    redis_json_cache: RedisJsonCache
    live_stats_runtime: LiveStatsRuntime
    clients_runtime: ClientsRuntime
    metrics_runtime: MetricsRuntime


def build_app_runtime_bundle(
    *,
    db_path: str,
    decrypt: Callable,
    encrypt: Callable,
    verify_tls: bool,
    collector_base_interval_sec: int,
    collector_max_interval_sec: int,
    collector_max_parallel: int,
    audit_queue_batch_size: int,
    audit_idle_sleep_sec: float,
    audit_active_sleep_sec: float,
    auth_cache: Dict,
    auth_cache_lock: Lock,
    auth_cache_ttl_sec: int,
    auth_cache_negative_ttl_sec: int,
    mfa_totp_enabled: bool,
    mfa_totp_users: Dict,
    role_required_for_request: Callable,
    subscription_rate_state: Dict,
    subscription_rate_lock: Lock,
    sub_rate_limit_count: int,
    sub_rate_limit_window_sec: int,
    pam_client,
    redis_module,
    redis_url: str | None,
    traffic_stats_cache: Dict,
    online_clients_cache: Dict,
    clients_cache: Dict,
    cache_refresh_state: Dict,
    cache_refresh_lock: Lock,
    traffic_stats_cache_ttl: int,
    traffic_stats_stale_ttl: int,
    online_clients_cache_ttl: int,
    online_clients_stale_ttl: int,
    clients_cache_ttl: int,
    clients_cache_stale_ttl: int,
    node_history_enabled: bool,
    node_history_min_interval_sec: int,
    node_history_retention_days: int,
    node_metric_labels_state: Dict,
    node_metric_labels_lock: Lock,
    history_write_state: Dict,
    history_write_lock: Lock,
    adguard_collect_interval_sec: int,
    adguard_latest: Dict,
    adguard_latest_lock: Lock,
    ws_manager,
    on_snapshot: Callable,
) -> AppRuntimeBundle:
    inbound_mgr = InboundManager(decrypt_func=decrypt, encrypt_func=encrypt)
    client_mgr = ClientManager(decrypt_func=decrypt, encrypt_func=encrypt)
    server_monitor = ServerMonitor(decrypt_func=decrypt)
    xui_monitor = ThreeXUIMonitor(decrypt_func=decrypt)
    adguard_monitor = AdGuardMonitor(decrypt_func=decrypt, default_verify=verify_tls)
    node_service = NodeService(db_path)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("sub_manager")
    metrics = build_metrics_registry()

    snapshot_collector = SnapshotCollector(
        fetch_nodes=node_service.list_nodes,
        xui_monitor=xui_monitor,
        ws_manager=ws_manager,
        on_snapshot=on_snapshot,
        base_interval_sec=collector_base_interval_sec,
        max_interval_sec=collector_max_interval_sec,
        max_parallel_polls=collector_max_parallel,
    )
    ws_manager.set_activity_callback(snapshot_collector.on_websocket_activity)

    metrics_cache: Dict = {"payload": None, "ts": 0.0}
    metrics_cache_lock = Lock()

    audit_runtime = AuditQueueRuntime(
        db_path=db_path,
        batch_size=audit_queue_batch_size,
        idle_sleep_sec=audit_idle_sleep_sec,
        active_sleep_sec=audit_active_sleep_sec,
        logger=logger,
    )

    adguard_runtime = AdGuardRuntime(
        db_path=db_path,
        requests_verify=verify_tls,
        collect_interval_sec=adguard_collect_interval_sec,
        latest_state=adguard_latest,
        latest_lock=adguard_latest_lock,
        adguard_monitor=adguard_monitor,
        source_available_metric=metrics.adguard_source_available,
        dns_queries_total_metric=metrics.adguard_dns_queries_total,
        dns_blocked_total_metric=metrics.adguard_dns_blocked_total,
        dns_block_rate_metric=metrics.adguard_dns_block_rate,
        dns_latency_ms_metric=metrics.adguard_dns_latency_ms,
        dns_cache_hit_ratio_metric=metrics.adguard_dns_cache_hit_ratio,
        dns_upstream_errors_metric=metrics.adguard_dns_upstream_errors,
        logger=logger,
    )

    request_runtime = RequestRuntime(
        pam_client=pam_client,
        auth_cache=auth_cache,
        auth_cache_lock=auth_cache_lock,
        auth_cache_ttl_sec=auth_cache_ttl_sec,
        auth_cache_negative_ttl_sec=auth_cache_negative_ttl_sec,
        mfa_totp_enabled=mfa_totp_enabled,
        mfa_totp_users=mfa_totp_users,
        role_required_for_request=role_required_for_request,
        subscription_rate_state=subscription_rate_state,
        subscription_rate_lock=subscription_rate_lock,
        sub_rate_limit_count=sub_rate_limit_count,
        sub_rate_limit_window_sec=sub_rate_limit_window_sec,
        logger=logger,
    )

    redis_json_cache = RedisJsonCache(
        redis_module=redis_module,
        redis_url=redis_url,
        logger=logger,
    )

    live_stats_runtime = LiveStatsRuntime(
        client_mgr=client_mgr,
        traffic_stats_cache=traffic_stats_cache,
        online_clients_cache=online_clients_cache,
        cache_refresh_state=cache_refresh_state,
        state_lock=cache_refresh_lock,
        redis_get_json=redis_json_cache.get_json,
        redis_set_json=redis_json_cache.set_json,
        redis_delete=redis_json_cache.delete,
        traffic_stats_cache_ttl=traffic_stats_cache_ttl,
        traffic_stats_stale_ttl=traffic_stats_stale_ttl,
        online_clients_cache_ttl=online_clients_cache_ttl,
        online_clients_stale_ttl=online_clients_stale_ttl,
        logger=logger,
    )

    clients_runtime = ClientsRuntime(
        client_mgr=client_mgr,
        clients_cache=clients_cache,
        clients_cache_ttl=clients_cache_ttl,
        clients_cache_stale_ttl=clients_cache_stale_ttl,
        start_cache_refresh=live_stats_runtime.start_cache_refresh,
    )

    metrics_runtime = MetricsRuntime(
        db_path=db_path,
        node_history_enabled=node_history_enabled,
        node_history_min_interval_sec=node_history_min_interval_sec,
        node_history_retention_days=node_history_retention_days,
        node_metric_labels_state=node_metric_labels_state,
        node_metric_labels_lock=node_metric_labels_lock,
        history_write_state=history_write_state,
        history_write_lock=history_write_lock,
        snapshot_collector=snapshot_collector,
        redis_get_client=redis_json_cache.get_client,
        redis_url=redis_url,
        node_availability_metric=metrics.node_availability,
        node_xray_running_metric=metrics.node_xray_running,
        node_cpu_percent_metric=metrics.node_cpu_percent,
        node_online_clients_metric=metrics.node_online_clients,
        node_traffic_total_bytes_metric=metrics.node_traffic_total_bytes,
        node_poll_duration_ms_metric=metrics.node_poll_duration_ms,
    )
    metrics_runtime.set_metrics_cache_lock(metrics_cache_lock)

    return AppRuntimeBundle(
        inbound_mgr=inbound_mgr,
        client_mgr=client_mgr,
        server_monitor=server_monitor,
        xui_monitor=xui_monitor,
        adguard_monitor=adguard_monitor,
        node_service=node_service,
        logger=logger,
        metrics=metrics,
        snapshot_collector=snapshot_collector,
        metrics_cache=metrics_cache,
        metrics_cache_lock=metrics_cache_lock,
        audit_runtime=audit_runtime,
        adguard_runtime=adguard_runtime,
        request_runtime=request_runtime,
        redis_json_cache=redis_json_cache,
        live_stats_runtime=live_stats_runtime,
        clients_runtime=clients_runtime,
        metrics_runtime=metrics_runtime,
    )
