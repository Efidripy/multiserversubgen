from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict


@dataclass
class RuntimeState:
    emails_cache: Dict
    links_cache: Dict
    subscription_rate_state: Dict = field(default_factory=lambda: defaultdict(deque))
    subscription_rate_lock: Lock = field(default_factory=Lock)
    cache_refresh_lock: Lock = field(default_factory=Lock)
    traffic_stats_cache: Dict[str, tuple] = field(default_factory=dict)
    online_clients_cache: Dict = field(default_factory=lambda: {"ts": 0.0, "data": []})
    clients_cache: Dict = field(default_factory=lambda: {"ts": 0.0, "data": []})
    cache_refresh_state: Dict = field(
        default_factory=lambda: {
            "traffic": set(),
            "online_clients": False,
            "clients": False,
        }
    )
    auth_cache_lock: Lock = field(default_factory=Lock)
    auth_cache: Dict = field(default_factory=dict)
    redis_client = None
    adguard_latest: Dict = field(default_factory=lambda: {"ts": 0.0, "sources": [], "summary": {}})
    adguard_latest_lock: Lock = field(default_factory=Lock)
    history_write_state: Dict = field(
        default_factory=lambda: {"last_by_node": {}, "last_cleanup_ts": 0.0}
    )
    history_write_lock: Lock = field(default_factory=Lock)
    node_metric_labels_state: Dict[str, str] = field(default_factory=dict)
    node_metric_labels_lock: Lock = field(default_factory=Lock)


def build_runtime_state(*, subscription_links_service) -> RuntimeState:
    return RuntimeState(
        emails_cache=subscription_links_service.emails_cache,
        links_cache=subscription_links_service.links_cache,
    )
