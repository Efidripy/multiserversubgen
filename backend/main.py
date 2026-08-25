import pam
import os
import asyncio
from functools import partial
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import urllib3
try:
    import redis
except Exception:
    redis = None

from core.lifespan import build_lifespan
from core.app_settings import load_app_settings
from core.main_facades import (
    build_auth_request_facade,
    build_cache_facade,
    build_metrics_facade,
    build_subscription_links_facade,
)
from core.request_middleware import build_request_controls_and_audit_middleware
from modules.auth.service import AuthService, WEB_SESSION_COOKIE_NAME, WEB_SESSION_TTL_SEC, parse_mfa_users
from services.db_bootstrap import (
    init_db as bootstrap_db,
    sync_node_history_names_with_nodes as sync_node_history_names_with_nodes_db,
)
from services.node_access import get_node_or_404
from core.app_runtime_bundle import build_app_runtime_bundle
from core.router_registration import register_app_routers
from services.runtime_state import build_runtime_state
from shared.http_config import get_requests_verify_value

import sys
sys.path.insert(0, str(Path(__file__).parent))
from crypto import encrypt, decrypt
from xui_session import login_panel, xui_request
from websocket_manager import manager as ws_manager, handle_websocket_message
import services.subscription_links as subscription_links_service

from shared.logging import configure_logging
configure_logging()

SETTINGS = load_app_settings(parse_mfa_users=parse_mfa_users)
PROJECT_DIR = SETTINGS.project_dir
WEB_PATH = SETTINGS.web_path
GRAFANA_WEB_PATH = SETTINGS.grafana_web_path
MONITORING_ENABLED = SETTINGS.monitoring_enabled
root_path = SETTINGS.root_path
CACHE_TTL = SETTINGS.cache_ttl
ALLOW_ORIGINS = SETTINGS.allow_origins
VERIFY_TLS = SETTINGS.verify_tls
CA_BUNDLE_PATH = SETTINGS.ca_bundle_path
READ_ONLY_MODE = SETTINGS.read_only_mode
SUB_RATE_LIMIT_COUNT = SETTINGS.sub_rate_limit_count
SUB_RATE_LIMIT_WINDOW_SEC = SETTINGS.sub_rate_limit_window_sec
TRAFFIC_STATS_CACHE_TTL = SETTINGS.traffic_stats_cache_ttl
TRAFFIC_STATS_STALE_TTL = SETTINGS.traffic_stats_stale_ttl
CLIENTS_CACHE_TTL = SETTINGS.clients_cache_ttl
CLIENTS_CACHE_STALE_TTL = SETTINGS.clients_cache_stale_ttl
REDIS_URL = SETTINGS.redis_url
REDIS_SOCKET_CONNECT_TIMEOUT_SEC = SETTINGS.redis_socket_connect_timeout_sec
REDIS_SOCKET_TIMEOUT_SEC = SETTINGS.redis_socket_timeout_sec
REDIS_FAILURE_COOLDOWN_SEC = SETTINGS.redis_failure_cooldown_sec
COLLECTOR_BASE_INTERVAL_SEC = SETTINGS.collector_base_interval_sec
COLLECTOR_MAX_INTERVAL_SEC = SETTINGS.collector_max_interval_sec
COLLECTOR_MAX_PARALLEL = SETTINGS.collector_max_parallel
COLLECTOR_WARMING_INTERVAL_1_SEC = SETTINGS.collector_warming_interval_1_sec
COLLECTOR_WARMING_INTERVAL_2_SEC = SETTINGS.collector_warming_interval_2_sec
COLLECTOR_WARMING_INTERVAL_3_SEC = SETTINGS.collector_warming_interval_3_sec
COLLECTOR_ACTIVE_INTERVAL_SEC = SETTINGS.collector_active_interval_sec
COLLECTOR_IDLE_INTERVAL_SEC = SETTINGS.collector_idle_interval_sec
COLLECTOR_ULTRA_IDLE_INTERVAL_SEC = SETTINGS.collector_ultra_idle_interval_sec
COLLECTOR_IDLE_AFTER_SEC = SETTINGS.collector_idle_after_sec
COLLECTOR_ULTRA_IDLE_AFTER_SEC = SETTINGS.collector_ultra_idle_after_sec
NODE_HISTORY_ENABLED = SETTINGS.node_history_enabled
NODE_HISTORY_MIN_INTERVAL_SEC = SETTINGS.node_history_min_interval_sec
NODE_HISTORY_RETENTION_DAYS = SETTINGS.node_history_retention_days
AUDIT_QUEUE_BATCH_SIZE = SETTINGS.audit_queue_batch_size
AUDIT_MEMORY_QUEUE_MAX = SETTINGS.audit_memory_queue_max_size
AUDIT_IDLE_SLEEP_SEC = SETTINGS.audit_idle_sleep_sec
AUDIT_ACTIVE_SLEEP_SEC = SETTINGS.audit_active_sleep_sec
ROLE_VIEWERS = SETTINGS.role_viewers
ROLE_OPERATORS = SETTINGS.role_operators
ROLE_ADMINS = SETTINGS.role_admins
MFA_TOTP_ENABLED = SETTINGS.mfa_totp_enabled
MFA_TOTP_USERS = SETTINGS.mfa_totp_users
MFA_TOTP_WS_STRICT = SETTINGS.mfa_totp_ws_strict
WS_AUTH_SECRET = SETTINGS.ws_auth_secret
SUBSCRIPTION_SIGNING_SECRET = SETTINGS.subscription_signing_secret
ADGUARD_COLLECT_INTERVAL_SEC = SETTINGS.adguard_collect_interval_sec
PROMETHEUS_URL = SETTINGS.prometheus_url
LOKI_URL = SETTINGS.loki_url
GRAFANA_URL = SETTINGS.grafana_url
PROMETHEUS_BASIC_AUTH = SETTINGS.prometheus_basic_auth
LOKI_BASIC_AUTH = SETTINGS.loki_basic_auth
GRAFANA_BASIC_AUTH = SETTINGS.grafana_basic_auth

REQUESTS_VERIFY = get_requests_verify_value(verify_tls=VERIFY_TLS, ca_bundle_path=CA_BUNDLE_PATH)
if REQUESTS_VERIFY is False:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

auth_service = AuthService(
    role_viewers=ROLE_VIEWERS,
    role_operators=ROLE_OPERATORS,
    role_admins=ROLE_ADMINS,
    ws_auth_secret=WS_AUTH_SECRET,
    mfa_totp_enabled=MFA_TOTP_ENABLED,
    mfa_totp_users=MFA_TOTP_USERS,
)

app = FastAPI(title="Multi-Server Sub Manager", version="3.0", root_path=root_path)

# Gzip compression for responses larger than 1 KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
DB_PATH = os.path.join(PROJECT_DIR, "admin.db")


class _PamFallback:
    def authenticate(self, username, password):
        return False


try:
    p = pam.pam()
except Exception:
    p = _PamFallback()

runtime_state = build_runtime_state(subscription_links_service=subscription_links_service)
emails_cache = runtime_state.emails_cache
links_cache = runtime_state.links_cache
subscription_rate_state = runtime_state.subscription_rate_state
subscription_rate_lock = runtime_state.subscription_rate_lock
cache_refresh_lock = runtime_state.cache_refresh_lock
traffic_stats_cache = runtime_state.traffic_stats_cache
clients_cache = runtime_state.clients_cache
cache_refresh_state = runtime_state.cache_refresh_state
auth_cache_lock = runtime_state.auth_cache_lock
auth_cache = runtime_state.auth_cache
AUTH_CACHE_TTL_SEC = 30
AUTH_CACHE_NEGATIVE_TTL_SEC = 5
_redis_client = runtime_state.redis_client
adguard_latest = runtime_state.adguard_latest
adguard_latest_lock = runtime_state.adguard_latest_lock
history_write_state = runtime_state.history_write_state
history_write_lock = runtime_state.history_write_lock
node_metric_labels_state = runtime_state.node_metric_labels_state
node_metric_labels_lock = runtime_state.node_metric_labels_lock

metrics_runtime = None
live_stats_runtime = None


def _on_snapshot(snapshot: dict) -> None:
    _record_node_snapshot(snapshot)
    _persist_node_version(snapshot)
    if live_stats_runtime is None:
        return
    try:
        # The collector already owns this data.  Never start a second fleet
        # walk merely to seed Statistics period baselines.
        live_stats_runtime.seed_period_snapshots_from_collector()
    except Exception as exc:
        logger.warning("Traffic snapshot auto-seed failed: %s", exc)


bundle = build_app_runtime_bundle(
    db_path=DB_PATH,
    decrypt=decrypt,
    encrypt=encrypt,
    verify_tls=REQUESTS_VERIFY,
    collector_base_interval_sec=COLLECTOR_BASE_INTERVAL_SEC,
    collector_max_interval_sec=COLLECTOR_MAX_INTERVAL_SEC,
    collector_max_parallel=COLLECTOR_MAX_PARALLEL,
    collector_warming_interval_1_sec=COLLECTOR_WARMING_INTERVAL_1_SEC,
    collector_warming_interval_2_sec=COLLECTOR_WARMING_INTERVAL_2_SEC,
    collector_warming_interval_3_sec=COLLECTOR_WARMING_INTERVAL_3_SEC,
    collector_active_interval_sec=COLLECTOR_ACTIVE_INTERVAL_SEC,
    collector_idle_interval_sec=COLLECTOR_IDLE_INTERVAL_SEC,
    collector_ultra_idle_interval_sec=COLLECTOR_ULTRA_IDLE_INTERVAL_SEC,
    collector_idle_after_sec=COLLECTOR_IDLE_AFTER_SEC,
    collector_ultra_idle_after_sec=COLLECTOR_ULTRA_IDLE_AFTER_SEC,
    audit_queue_batch_size=AUDIT_QUEUE_BATCH_SIZE,
    audit_memory_queue_max_size=AUDIT_MEMORY_QUEUE_MAX,
    audit_idle_sleep_sec=AUDIT_IDLE_SLEEP_SEC,
    audit_active_sleep_sec=AUDIT_ACTIVE_SLEEP_SEC,
    auth_cache=auth_cache,
    auth_cache_lock=auth_cache_lock,
    auth_cache_ttl_sec=AUTH_CACHE_TTL_SEC,
    auth_cache_negative_ttl_sec=AUTH_CACHE_NEGATIVE_TTL_SEC,
    mfa_totp_enabled=MFA_TOTP_ENABLED,
    mfa_totp_users=MFA_TOTP_USERS,
    role_required_for_request=auth_service.required_role_for_request,
    subscription_rate_state=subscription_rate_state,
    subscription_rate_lock=subscription_rate_lock,
    sub_rate_limit_count=SUB_RATE_LIMIT_COUNT,
    sub_rate_limit_window_sec=SUB_RATE_LIMIT_WINDOW_SEC,
    pam_client=p,
    redis_module=redis,
    redis_url=REDIS_URL,
    redis_socket_connect_timeout_sec=REDIS_SOCKET_CONNECT_TIMEOUT_SEC,
    redis_socket_timeout_sec=REDIS_SOCKET_TIMEOUT_SEC,
    redis_failure_cooldown_sec=REDIS_FAILURE_COOLDOWN_SEC,
    traffic_stats_cache=traffic_stats_cache,
    clients_cache=clients_cache,
    inbounds_cache=runtime_state.inbounds_cache,
    cache_refresh_state=cache_refresh_state,
    cache_refresh_lock=cache_refresh_lock,
    traffic_stats_cache_ttl=TRAFFIC_STATS_CACHE_TTL,
    traffic_stats_stale_ttl=TRAFFIC_STATS_STALE_TTL,
    clients_cache_ttl=CLIENTS_CACHE_TTL,
    clients_cache_stale_ttl=CLIENTS_CACHE_STALE_TTL,
    node_history_enabled=NODE_HISTORY_ENABLED,
    node_history_min_interval_sec=NODE_HISTORY_MIN_INTERVAL_SEC,
    node_history_retention_days=NODE_HISTORY_RETENTION_DAYS,
    node_metric_labels_state=node_metric_labels_state,
    node_metric_labels_lock=node_metric_labels_lock,
    history_write_state=history_write_state,
    history_write_lock=history_write_lock,
    adguard_collect_interval_sec=ADGUARD_COLLECT_INTERVAL_SEC,
    adguard_latest=adguard_latest,
    adguard_latest_lock=adguard_latest_lock,
    ws_manager=ws_manager,
    on_snapshot=_on_snapshot,
)
inbound_mgr = bundle.inbound_mgr
client_mgr = bundle.client_mgr
server_monitor = bundle.server_monitor
xui_monitor = bundle.xui_monitor
adguard_monitor = bundle.adguard_monitor
node_service = bundle.node_service
logger = bundle.logger
metrics = bundle.metrics
snapshot_collector = bundle.snapshot_collector
_metrics_cache = bundle.metrics_cache
_metrics_cache_lock = bundle.metrics_cache_lock
audit_runtime = bundle.audit_runtime
adguard_runtime = bundle.adguard_runtime
request_runtime = bundle.request_runtime
redis_json_cache = bundle.redis_json_cache
live_stats_runtime = bundle.live_stats_runtime
clients_runtime = bundle.clients_runtime
inbounds_runtime = bundle.inbounds_runtime
metrics_runtime = bundle.metrics_runtime

HTTP_REQUEST_COUNT = metrics.http_request_count
HTTP_REQUEST_LATENCY = metrics.http_request_latency

(
    _remove_node_metric_labels,
    _record_node_snapshot,
    render_metrics_response,
    deps_health_status,
    sync_node_history_names_with_nodes,
) = build_metrics_facade(
    get_metrics_runtime=lambda: metrics_runtime,
    sync_node_history_names_with_nodes_db=sync_node_history_names_with_nodes_db,
    db_path=DB_PATH,
    logger=logger,
)

bootstrap_db(DB_PATH)


def _persist_node_version(snapshot: dict) -> None:
    node_id = snapshot.get("node_id")
    api_version = snapshot.get("api_version") or ""
    panel_version = snapshot.get("panel_version") or ""
    if not node_id or not api_version or not snapshot.get("available"):
        return
    node = node_service.get_node(node_id)
    if node and (node.get("api_version") != api_version or node.get("panel_version") != panel_version):
        node_service.update_node(node_id, {"api_version": api_version, "panel_version": panel_version})
        logger.info("Node %s version updated: api=%s panel=%s", node.get("name"), api_version, panel_version)


collect_adguard_once = adguard_runtime.collect_once
adguard_collector_loop = adguard_runtime.collector_loop

(
    _facade_get_user_role,
    _facade_has_min_role,
    check_basic_auth_header,
    verify_totp_code,
    extract_basic_auth_username,
    _get_client_ip,
    _check_subscription_rate_limit,
    _is_public_endpoint,
    _required_role_for_request,
    check_auth,
) = build_auth_request_facade(
    auth_service=auth_service,
    request_runtime=request_runtime,
    get_mfa_enabled=lambda: MFA_TOTP_ENABLED,
    get_mfa_users=lambda: MFA_TOTP_USERS,
    get_sub_rate_limit_count=lambda: SUB_RATE_LIMIT_COUNT,
    get_sub_rate_limit_window_sec=lambda: SUB_RATE_LIMIT_WINDOW_SEC,
)


def _sync_auth_service_roles() -> None:
    auth_service.role_viewers = ROLE_VIEWERS
    auth_service.role_operators = ROLE_OPERATORS
    auth_service.role_admins = ROLE_ADMINS


def get_user_role(username: str) -> str:
    _sync_auth_service_roles()
    return _facade_get_user_role(username)


def has_min_role(user_role: str, min_role: str) -> bool:
    return _facade_has_min_role(user_role, min_role)


def check_web_session(request: Request):
    return auth_service.verify_web_session(request.cookies.get(WEB_SESSION_COOKIE_NAME))

(
    invalidate_live_stats_cache,
    invalidate_read_projections,
    get_cached_traffic_stats,
    get_cached_traffic_stats_projection,
    get_cached_traffic_stats_projection_by_period,
    get_cached_clients,
    enqueue_audit_event,
    audit_worker_loop,
) = build_cache_facade(
    live_stats_runtime=live_stats_runtime,
    clients_runtime=clients_runtime,
    inbounds_runtime=inbounds_runtime,
    audit_runtime=audit_runtime,
)

(
    invalidate_subscription_cache,
    fetch_inbounds,
    get_emails,
    get_links_filtered,
    register_subscription_response_cache_invalidator,
) = build_subscription_links_facade(subscription_links_service=subscription_links_service, db_path=DB_PATH)


app.middleware("http")(
    build_request_controls_and_audit_middleware(
        is_public_endpoint=_is_public_endpoint,
        check_basic_auth_header=check_basic_auth_header,
        check_web_session=check_web_session,
        get_user_role=get_user_role,
        verify_totp_code=verify_totp_code,
        required_role_for_request=_required_role_for_request,
        has_min_role=has_min_role,
        read_only_mode=READ_ONLY_MODE,
        invalidate_read_projections=invalidate_read_projections,
        http_request_count=HTTP_REQUEST_COUNT,
        http_request_latency=HTTP_REQUEST_LATENCY,
        get_client_ip=_get_client_ip,
        extract_basic_auth_username=extract_basic_auth_username,
        enqueue_audit_event=enqueue_audit_event,
        allowed_origins=ALLOW_ORIGINS,
    )
)


register_app_routers(
    app,
    snapshot_collector=snapshot_collector,
    render_metrics_response=render_metrics_response,
    deps_health_status=deps_health_status,
    check_auth=check_auth,
    verify_totp_code=verify_totp_code,
    get_user_role=get_user_role,
    issue_ws_ticket=auth_service.issue_ws_ticket,
    issue_web_session=auth_service.issue_web_session,
    web_session_cookie_name=WEB_SESSION_COOKIE_NAME,
    web_session_ttl_sec=WEB_SESSION_TTL_SEC,
    verify_ws_ticket=auth_service.verify_ws_ticket,
    mfa_totp_enabled=MFA_TOTP_ENABLED,
    monitoring_enabled=MONITORING_ENABLED,
    get_node_or_404=partial(get_node_or_404, node_service),
    get_cached_traffic_stats=get_cached_traffic_stats,
    get_cached_traffic_stats_projection=get_cached_traffic_stats_projection,
    get_cached_traffic_stats_projection_by_period=get_cached_traffic_stats_projection_by_period,
    list_nodes=node_service.list_nodes,
    xui_monitor=xui_monitor,
    node_service=node_service,
    db_path=DB_PATH,
    encrypt=encrypt,
    requests_verify=REQUESTS_VERIFY,
    login_panel=login_panel,
    xui_request=xui_request,
    invalidate_subscription_cache=invalidate_subscription_cache,
    remove_node_metric_labels=_remove_node_metric_labels,
    node_metric_labels_lock=node_metric_labels_lock,
    node_metric_labels_state=node_metric_labels_state,
    ws_manager=ws_manager,
    logger=logger,
    inbound_mgr=inbound_mgr,
    invalidate_live_stats_cache=invalidate_live_stats_cache,
    client_mgr=client_mgr,
    get_cached_clients=get_cached_clients,
    get_cached_inbounds=inbounds_runtime.get_cached_inbounds,
    get_cached_slim_inbounds=inbounds_runtime.get_cached_slim_inbounds,
    get_cached_inbound_options=inbounds_runtime.get_cached_inbound_options,
    check_subscription_rate_limit=_check_subscription_rate_limit,
    get_emails=get_emails,
    get_links_filtered=get_links_filtered,
    register_subscription_response_cache_invalidator=register_subscription_response_cache_invalidator,
    subscription_signing_secret=SUBSCRIPTION_SIGNING_SECRET,
    verify_tls_default=VERIFY_TLS,
    list_adguard_sources=adguard_runtime.list_sources,
    collect_adguard_once=collect_adguard_once,
    adguard_latest=adguard_latest,
    adguard_latest_lock=adguard_latest_lock,
    adguard_collect_interval_sec=ADGUARD_COLLECT_INTERVAL_SEC,
    build_adguard_summary=adguard_runtime.build_summary,
    build_adguard_history=adguard_runtime.build_history,
    parse_basic_auth_pair=adguard_runtime.parse_basic_auth_pair,
    http_probe=adguard_runtime.http_probe,
    prom_query=adguard_runtime.prom_query,
    prometheus_url=PROMETHEUS_URL,
    loki_url=LOKI_URL,
    grafana_url=GRAFANA_URL,
    prometheus_basic_auth=PROMETHEUS_BASIC_AUTH,
    loki_basic_auth=LOKI_BASIC_AUTH,
    grafana_basic_auth=GRAFANA_BASIC_AUTH,
    web_path=WEB_PATH,
    grafana_web_path=GRAFANA_WEB_PATH,
    server_monitor=server_monitor,
    check_basic_auth_header=check_basic_auth_header,
    mfa_totp_ws_strict=MFA_TOTP_WS_STRICT,
    pam_authenticate=p.authenticate,
    handle_websocket_message=handle_websocket_message,
)
app.router.lifespan_context = build_lifespan(
    sync_node_history_names_with_nodes=sync_node_history_names_with_nodes,
    backfill_traffic_history_snapshots=live_stats_runtime.backfill_node_history_snapshots,
    audit_worker_loop=audit_worker_loop,
    audit_flush=audit_runtime.flush,
    snapshot_collector=snapshot_collector,
    adguard_collector_loop=adguard_collector_loop,
    asyncio_module=asyncio,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("APP_PORT", "666")))
