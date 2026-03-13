from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from fastapi import Request


def build_metrics_facade(*, get_metrics_runtime, sync_node_history_names_with_nodes_db, db_path: str, logger):
    def remove_node_metric_labels(node_name: str, node_id: str):
        return get_metrics_runtime().remove_node_metric_labels(node_name, node_id)

    def record_node_snapshot(snapshot: Dict):
        return get_metrics_runtime().record_node_snapshot(snapshot)

    def render_metrics_response():
        return get_metrics_runtime().render_metrics_response()

    def deps_health_status() -> Dict:
        return get_metrics_runtime().deps_health_status()

    def sync_node_history_names_with_nodes():
        return sync_node_history_names_with_nodes_db(db_path, logger)

    return (
        remove_node_metric_labels,
        record_node_snapshot,
        render_metrics_response,
        deps_health_status,
        sync_node_history_names_with_nodes,
    )


def build_auth_request_facade(
    *,
    auth_service,
    request_runtime,
    get_mfa_enabled,
    get_mfa_users,
    get_sub_rate_limit_count,
    get_sub_rate_limit_window_sec,
):
    def get_user_role(username: str) -> str:
        return auth_service.get_user_role(username)

    def has_min_role(user_role: str, min_role: str) -> bool:
        return auth_service.has_min_role(user_role, min_role)

    def check_basic_auth_header(auth_header: Optional[str]) -> Optional[str]:
        return request_runtime.check_basic_auth_header(auth_header)

    def verify_totp_code(username: str, totp_code: Optional[str]) -> bool:
        request_runtime.mfa_totp_enabled = get_mfa_enabled()
        request_runtime.mfa_totp_users = get_mfa_users()
        return request_runtime.verify_totp_code(username, totp_code)

    def extract_basic_auth_username(auth_header: Optional[str]) -> Optional[str]:
        return request_runtime.extract_basic_auth_username(auth_header)

    def get_client_ip(request: Request) -> str:
        return request_runtime.get_client_ip(request)

    def check_subscription_rate_limit(request: Request, resource_key: str) -> Tuple[bool, int]:
        request_runtime.sub_rate_limit_count = get_sub_rate_limit_count()
        request_runtime.sub_rate_limit_window_sec = get_sub_rate_limit_window_sec()
        return request_runtime.check_subscription_rate_limit(request, resource_key)

    def is_public_endpoint(path: str) -> bool:
        return request_runtime.is_public_endpoint(path)

    def required_role_for_request(method: str, path: str) -> str:
        return request_runtime.required_role_for_request(method, path)

    def check_auth(request: Request) -> Optional[str]:
        return request_runtime.check_auth(request)

    return (
        get_user_role,
        has_min_role,
        check_basic_auth_header,
        verify_totp_code,
        extract_basic_auth_username,
        get_client_ip,
        check_subscription_rate_limit,
        is_public_endpoint,
        required_role_for_request,
        check_auth,
    )


def build_cache_facade(*, live_stats_runtime, clients_runtime, audit_runtime):
    def invalidate_live_stats_cache():
        return live_stats_runtime.invalidate_live_stats_cache()

    def get_cached_traffic_stats(nodes: List[Dict], group_by: str) -> Dict:
        return live_stats_runtime.get_cached_traffic_stats(nodes, group_by)

    def get_cached_online_clients(nodes: List[Dict]) -> List[Dict]:
        return live_stats_runtime.get_cached_online_clients(nodes)

    def get_cached_clients(nodes: List[Dict], email_filter: Optional[str] = None) -> List[Dict]:
        return clients_runtime.get_cached_clients(nodes, email_filter=email_filter)

    def enqueue_audit_event(payload: Dict) -> None:
        return audit_runtime.enqueue_event(payload)

    async def audit_worker_loop() -> None:
        await audit_runtime.worker_loop()

    return (
        invalidate_live_stats_cache,
        get_cached_traffic_stats,
        get_cached_online_clients,
        get_cached_clients,
        enqueue_audit_event,
        audit_worker_loop,
    )


def build_subscription_links_facade(*, subscription_links_service):
    def invalidate_subscription_cache():
        return subscription_links_service.invalidate_subscription_cache()

    def fetch_inbounds(node: Dict) -> List[Dict]:
        return subscription_links_service.fetch_inbounds(node)

    def get_emails(nodes: List[Dict]) -> List[str]:
        return subscription_links_service.get_emails(nodes)

    def get_links(nodes: List[Dict], email: str) -> List[str]:
        return subscription_links_service.get_links(nodes, email)

    def get_links_filtered(nodes: List[Dict], email: str, protocol_filter: Optional[str] = None) -> List[str]:
        return subscription_links_service.get_links_filtered(nodes, email, protocol_filter)

    return (
        invalidate_subscription_cache,
        fetch_inbounds,
        get_emails,
        get_links,
        get_links_filtered,
    )
