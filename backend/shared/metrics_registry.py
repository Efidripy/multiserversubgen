from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, Gauge, Histogram


@dataclass
class MetricsRegistry:
    http_request_count: Counter
    http_request_latency: Histogram
    node_availability: Gauge
    node_xray_running: Gauge
    node_cpu_percent: Gauge
    node_online_clients: Gauge
    node_traffic_total_bytes: Gauge
    node_poll_duration_ms: Gauge
    adguard_source_available: Gauge
    adguard_dns_queries_total: Gauge
    adguard_dns_blocked_total: Gauge
    adguard_dns_block_rate: Gauge
    adguard_dns_latency_ms: Gauge
    adguard_dns_cache_hit_ratio: Gauge
    adguard_dns_upstream_errors: Gauge
    collector_poll_cycle_duration_seconds: Histogram
    collector_poll_cycles_total: Counter
    collector_poll_cycle_due_nodes: Histogram
    sqlite_batch_rows: Histogram
    audit_memory_queue_depth: Gauge
    audit_events_dropped_total: Counter


def build_metrics_registry() -> MetricsRegistry:
    return MetricsRegistry(
        http_request_count=Counter(
            "sub_manager_http_requests_total",
            "HTTP requests total",
            ["method", "path", "status"],
        ),
        http_request_latency=Histogram(
            "sub_manager_http_request_duration_seconds",
            "HTTP request latency",
            ["method", "path"],
        ),
        node_availability=Gauge(
            "sub_manager_node_available",
            "Node availability (1 available, 0 unavailable)",
            ["node_name", "node_id"],
        ),
        node_xray_running=Gauge(
            "sub_manager_node_xray_running",
            "core service running state on node (1 running, 0 stopped)",
            ["node_name", "node_id"],
        ),
        node_cpu_percent=Gauge(
            "sub_manager_node_cpu_percent",
            "Node CPU usage percent",
            ["node_name", "node_id"],
        ),
        node_online_clients=Gauge(
            "sub_manager_node_online_clients",
            "Online clients count per node",
            ["node_name", "node_id"],
        ),
        node_traffic_total_bytes=Gauge(
            "sub_manager_node_traffic_total_bytes",
            "Total traffic bytes per node snapshot",
            ["node_name", "node_id"],
        ),
        node_poll_duration_ms=Gauge(
            "sub_manager_node_poll_duration_ms",
            "Collector poll duration per node in milliseconds",
            ["node_name", "node_id"],
        ),
        adguard_source_available=Gauge(
            "sub_manager_adguard_source_available",
            "AdGuard source availability (1 available, 0 unavailable)",
            ["source_name", "source_id"],
        ),
        adguard_dns_queries_total=Gauge(
            "sub_manager_adguard_dns_queries_total",
            "AdGuard total DNS queries",
            ["source_name", "source_id"],
        ),
        adguard_dns_blocked_total=Gauge(
            "sub_manager_adguard_dns_blocked_total",
            "AdGuard blocked DNS queries",
            ["source_name", "source_id"],
        ),
        adguard_dns_block_rate=Gauge(
            "sub_manager_adguard_dns_block_rate_percent",
            "AdGuard blocked rate in percent",
            ["source_name", "source_id"],
        ),
        adguard_dns_latency_ms=Gauge(
            "sub_manager_adguard_dns_latency_ms",
            "AdGuard average DNS latency in milliseconds",
            ["source_name", "source_id"],
        ),
        adguard_dns_cache_hit_ratio=Gauge(
            "sub_manager_adguard_dns_cache_hit_ratio_percent",
            "AdGuard cache hit ratio in percent",
            ["source_name", "source_id"],
        ),
        adguard_dns_upstream_errors=Gauge(
            "sub_manager_adguard_dns_upstream_errors_total",
            "AdGuard upstream DNS errors",
            ["source_name", "source_id"],
        ),
        collector_poll_cycle_duration_seconds=Histogram(
            "sub_manager_collector_poll_cycle_duration_seconds",
            "Completed collector poll cycle duration for cycles with due nodes",
        ),
        collector_poll_cycles_total=Counter(
            "sub_manager_collector_poll_cycles_total",
            "Completed collector poll cycles with due nodes by mode and trigger",
            ["mode", "trigger"],
        ),
        collector_poll_cycle_due_nodes=Histogram(
            "sub_manager_collector_poll_cycle_due_nodes",
            "Due nodes per completed collector poll cycle by mode and trigger",
            ["mode", "trigger"],
        ),
        sqlite_batch_rows=Histogram(
            "sub_manager_sqlite_batch_rows",
            "Rows committed by semantic SQLite batch operations",
            ["operation"],
        ),
        audit_memory_queue_depth=Gauge(
            "sub_manager_audit_memory_queue_depth",
            "Approximate process-local audit memory queue depth",
        ),
        audit_events_dropped_total=Counter(
            "sub_manager_audit_events_dropped_total",
            "Audit events dropped from the bounded process-local queue",
            ["reason"],
        ),
    )
