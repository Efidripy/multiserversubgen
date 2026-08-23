"""
Модуль мониторинга серверов node panel
Статус системы, core service-процесса, проверка доступности
"""
import requests
import logging
import base64
import time
from urllib.parse import quote
import sys
import os
from pathlib import Path
from typing import Any, List, Dict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from xui_session import (
    XUI_FAST_RETRIES,
    XUI_FAST_TIMEOUT_SEC,
    bounded_xui_timeout,
    build_panel_base_url,
    diagnose_xui_failure,
    extract_node_auth,
    get_capability_route,
    get_authenticated_session,
    invalidate_node_capabilities,
    invalidate_session_cache,
    is_auth_failure_response,
    join_panel_url,
    make_node_key_for_node,
    login_panel,
    record_capability_route,
    xui_request,
)
from utils import parse_field_as_dict
from shared.security import MAX_BACKUP_B64_CHARS, bounded_log_count, validate_path_segment

logger = logging.getLogger("sub_manager")
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
CA_BUNDLE_PATH = os.getenv("CA_BUNDLE_PATH", "").strip()

SERVER_HISTORY_METRICS = frozenset({
    "cpu", "mem", "netUp", "netDown", "online", "load1", "load5", "load15",
})
SERVER_HISTORY_BUCKETS = frozenset({2, 30, 60, 180, 360, 720, 1440, 2880, 10080})


def validate_server_history_request(metric: str, bucket: int | str) -> tuple[str, int]:
    """Validate documented v3 history path parameters before a node request."""
    normalized_metric = str(metric or "")
    try:
        normalized_bucket = int(bucket)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid history bucket") from exc
    if normalized_metric not in SERVER_HISTORY_METRICS:
        raise ValueError("invalid history metric")
    if normalized_bucket not in SERVER_HISTORY_BUCKETS:
        raise ValueError("invalid history bucket")
    return normalized_metric, normalized_bucket


VALID_SERVER_LOG_LEVELS = frozenset({'debug', 'info', 'notice', 'warning', 'err'})


def validate_server_log_level(level: str) -> str:
    normalized = str(level or 'info').strip().lower()
    if normalized not in VALID_SERVER_LOG_LEVELS:
        raise ValueError(f'Unsupported server log level: {level}')
    return normalized


def _normalize_log_lines(raw_logs: Any) -> List[str]:
    """Normalize empty sentinels returned by different 3x-ui log backends."""
    if raw_logs is None:
        return []
    values = raw_logs if isinstance(raw_logs, list) else str(raw_logs).splitlines()
    lines = []
    for value in values:
        line = str(value or "").strip()
        if line and line.lower() not in {"none", "null"}:
            lines.append(line)
    return lines


def _format_xray_log_entry(entry: Any) -> str:
    """Render the current 3x-ui structured access-log entry for the text UI."""
    if not isinstance(entry, dict):
        return str(entry or "").strip()

    event_names = {0: "DIRECT", 1: "BLOCKED", 2: "PROXY"}
    fields = (
        ("time", entry.get("DateTime")),
        ("from", entry.get("FromAddress")),
        ("to", entry.get("ToAddress")),
        ("inbound", entry.get("Inbound")),
        ("outbound", entry.get("Outbound")),
        ("email", entry.get("Email")),
        ("event", event_names.get(entry.get("Event"), entry.get("Event"))),
    )
    return " | ".join(f"{label}={value}" for label, value in fields if value not in (None, ""))


def _requests_verify_value():
    if not VERIFY_TLS:
        return False
    if CA_BUNDLE_PATH:
        return CA_BUNDLE_PATH
    return True


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            value = value.strip().rstrip("%")
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_number(source: Any, keys: tuple[str, ...], default: float = 0.0) -> float:
    if not isinstance(source, dict):
        return default
    for key in keys:
        if key in source:
            return _to_float(source.get(key), default)
    return default


def _metric_block(source: Any) -> Dict[str, float]:
    if not isinstance(source, dict):
        source = {}
    current = _first_number(source, ("current", "used", "usage", "value"), 0.0)
    total = _first_number(source, ("total", "max", "limit"), 0.0)
    percent = _first_number(source, ("percent", "percentage", "usedPercent", "usagePercent"), -1.0)
    if percent < 0:
        percent = (current / total * 100) if total > 0 else 0.0
    return {
        "current": current,
        "total": total,
        "percent": round(percent, 2),
    }


def _normalize_loads(value: Any) -> List[float]:
    if isinstance(value, list):
        return [_to_float(item, 0.0) for item in value[:3]]
    if isinstance(value, str):
        return [_to_float(part, 0.0) for part in value.replace(",", " ").split()[:3]]
    if isinstance(value, dict):
        return [
            _first_number(value, ("load1", "1", "one", "one_min"), 0.0),
            _first_number(value, ("load5", "5", "five", "five_min"), 0.0),
            _first_number(value, ("load15", "15", "fifteen", "fifteen_min"), 0.0),
        ]
    return []


def _normalize_network(obj: Dict[str, Any]) -> Dict[str, float]:
    # 3x-ui v3 uses ``netIO: {up, down}``; retain the historical shapes only
    # for older panels and cached snapshots.
    net = obj.get("netIO") or obj.get("netTraffic") or obj.get("network") or obj.get("net") or {}
    return {
        "upload": _first_number(net, ("sent", "upload", "tx", "txBytes", "up"), 0.0),
        "download": _first_number(net, ("recv", "download", "rx", "rxBytes", "down"), 0.0),
    }


def _normalize_3xui_status(node: Dict, obj: Any) -> Dict:
    if not isinstance(obj, dict):
        obj = {}

    xray = obj.get("xray") if isinstance(obj.get("xray"), dict) else {}
    xray_state = str(xray.get("state") or "")
    xray_running = bool(xray.get("running")) or xray_state.lower() == "running"
    loads = _normalize_loads(obj.get("loads") or obj.get("load") or obj.get("loadavg"))

    return {
        "node": node["name"],
        "node_id": node.get("id"),
        "available": True,
        "timestamp": datetime.now().isoformat(),
        "system": {
            "cpu": _first_number(obj, ("cpu", "cpuPercent", "cpu_percent"), 0.0),
            "mem": _metric_block(obj.get("mem") or obj.get("memory") or obj.get("ram")),
            "disk": _metric_block(obj.get("disk") or obj.get("storage")),
            "swap": _metric_block(obj.get("swap")),
            "uptime": _first_number(obj, ("uptime", "upTime", "hostUptime"), 0.0),
            "loads": loads,
        },
        "xray": {
            "state": xray_state,
            "running": xray_running,
            "version": str(xray.get("version") or ""),
            "uptime": _first_number(xray, ("uptime", "upTime"), 0.0),
        },
        "network": _normalize_network(obj),
        "panel_version": str(obj.get("panelVersion") or obj.get("panel_version") or ""),
    }


class ThreeXUIMonitor:
    """Монитор 3x-UI с cookie-based аутентификацией.

    Использует корректные HTTP-методы согласно 3x-UI API v26.2.6.
    """

    def __init__(self, decrypt_func):
        self.decrypt = decrypt_func

    def _invalidate_cached_session(self, node: Dict) -> None:
        invalidate_session_cache(make_node_key_for_node(node))

    @staticmethod
    def _diagnostic_payload(
        *,
        response: requests.Response | None = None,
        error: Exception | None = None,
        endpoint_probe: bool = False,
    ) -> Dict[str, str]:
        """Return a redacted operator-facing error contract."""
        diagnostic = diagnose_xui_failure(
            response=response, error=error, endpoint_probe=endpoint_probe
        )
        return {
            "reason": diagnostic["code"],
            "error": diagnostic["message"],
            "diagnostic": diagnostic["code"],
        }

    @staticmethod
    def _login_failure_payload(login_result: Dict[str, Any]) -> Dict[str, str]:
        """Map known authentication outcomes to safe, actionable messages."""
        code = str(login_result.get("reason") or "network_error")
        messages = {
            "auth_failed": "Panel rejected the configured authentication",
            "two_factor_required": "Panel requires two-factor authentication",
            "bearer_token_invalid": "Panel rejected the configured authentication",
            "tls_error": "TLS certificate or handshake failed",
            "timeout": "Node panel did not respond before the timeout",
            "network_error": "Network request to node panel failed",
        }
        diagnostic = diagnose_xui_failure(error=Exception(login_result.get("error") or ""))
        return {
            "reason": code,
            "error": messages.get(code, diagnostic["message"]),
            "diagnostic": code,
        }

    @staticmethod
    def _normalize_inbound(inbound: Dict, node: Dict) -> Dict:
        normalized = dict(inbound)
        stream = parse_field_as_dict(
            inbound.get("streamSettings"),
            node_id=node.get("id") or node.get("name"),
            field_name="streamSettings",
        )
        settings = parse_field_as_dict(
            inbound.get("settings"),
            node_id=node.get("id") or node.get("name"),
            field_name="settings",
        )
        security = stream.get("security") or normalized.get("security") or ""
        normalized["streamSettings"] = stream
        normalized["settings"] = settings
        normalized["security"] = security
        normalized["is_reality"] = security == "reality"
        return normalized

    @staticmethod
    def _normalize_session_result(session_result: tuple) -> tuple:
        if not isinstance(session_result, tuple):
            return None, None, {"ok": False, "reason": "connection_failed", "error": "Failed to connect"}
        if len(session_result) == 3:
            return session_result
        if len(session_result) == 2:
            session, base_url = session_result
            if session:
                return session, base_url, {"ok": True, "reason": "ok", "error": ""}
            return None, None, {"ok": False, "reason": "connection_failed", "error": "Failed to connect"}
        return None, None, {"ok": False, "reason": "connection_failed", "error": "Failed to connect"}

    def _get_session(self, node: Dict, *, force_reauth: bool = False) -> tuple:
        """Создать авторизованную сессию для узла.

        Returns:
            Кортеж (session, base_url) или (None, None) при ошибке.
        """
        base_url = build_panel_base_url(node)
        try:
            username, password, bearer_token = extract_node_auth(node, self.decrypt)
            auth = get_authenticated_session(
                node_key=make_node_key_for_node(node),
                base_url=base_url,
                username=username,
                password=password,
                bearer_token=bearer_token,
                verify_value=_requests_verify_value(),
                timeout=XUI_FAST_TIMEOUT_SEC,
                retries=XUI_FAST_RETRIES,
                force_reauth=force_reauth,
            )
            if not auth.get("ok"):
                logger.warning(f"ThreeXUIMonitor: failed to login to {node['name']}")
                return None, None, auth
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: login error for {node['name']}: {exc}")
            return None, None, {
                "ok": False,
                "reason": "monitor_exception",
                "error": str(exc),
            }
        return auth["session"], auth["base_url"], {
            "ok": True,
            "reason": "ok",
            "error": "",
            "cached": bool(auth.get("cached")),
        }

    def _request_with_reauth(
        self,
        node: Dict,
        method: str,
        path: str,
        *,
        endpoint_probe: bool = False,
        **kwargs,
    ) -> tuple:
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return None, None, login_result

        try:
            res = xui_request(s, method, join_panel_url(base_url, path), **kwargs)
        except Exception as exc:
            return None, None, {"ok": False, "reason": "request_failed", "error": str(exc)}
        # 3x-ui may mask an expired panel session as 404 on /panel/api/*.  For
        # a compatibility probe, re-authenticate and repeat the *same* route
        # once before classifying it as absent.  The caller may select legacy
        # only after that second 404/405.
        probe_ambiguous = endpoint_probe and res.status_code in (404, 405)
        if not probe_ambiguous and not is_auth_failure_response(res, include_panel_api_404=True):
            return res, base_url, {"ok": True, "reason": "ok", "error": ""}

        logger.info("ThreeXUIMonitor: session expired for %s, re-authenticating once", node.get("name"))
        self._invalidate_cached_session(node)
        s, base_url, login_result = self._normalize_session_result(self._get_session(node, force_reauth=True))
        if not s:
            return None, None, login_result

        try:
            res = xui_request(s, method, join_panel_url(base_url, path), **kwargs)
        except Exception as exc:
            return None, None, {"ok": False, "reason": "request_failed", "error": str(exc)}
        if is_auth_failure_response(res, include_panel_api_404=not endpoint_probe):
            self._invalidate_cached_session(node)
        return res, base_url, {"ok": True, "reason": "ok", "error": ""}

    def _request_first_supported(
        self,
        node: Dict,
        method: str,
        operation: str,
        paths: tuple[str, ...],
        **kwargs,
    ) -> tuple:
        """Call the first API route supported by a node panel.

        3x-ui v3.6 documents clients/* routes while older panels keep several
        equivalents under inbounds/*.  Route support is probed at runtime:
        a 404/405 advances to the next documented compatibility path, whereas
        an authentication or application response keeps its original meaning.
        """
        node_key = make_node_key_for_node(node)
        cached_path = get_capability_route(node_key, operation, paths)
        ordered_paths = ((cached_path,) if cached_path else ()) + tuple(path for path in paths if path != cached_path)
        last_result = (None, None, {"ok": False, "reason": "endpoint_unsupported", "error": "No compatible API route"})
        for path in ordered_paths:
            result = self._request_with_reauth(
                node, method, path, endpoint_probe=True, **kwargs
            )
            response = result[0]
            last_result = result
            if response is None:
                return result
            if response.status_code in (404, 405):
                # A cached route may disappear after a panel upgrade; retry the
                # remaining modern/legacy contract in this same request.
                invalidate_node_capabilities(node_key)
                continue
            if 200 <= response.status_code < 300:
                record_capability_route(node_key, operation, path, response)
            return result
        return last_result

    def get_server_status(self, node: Dict) -> Dict:
        """GET /panel/api/server/status — статус CPU, RAM, диска, core service, сети."""
        res, _base_url, login_result = self._request_with_reauth(
            node,
            "GET",
            "/panel/api/server/status",
        )
        if res is None:
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                **self._login_failure_payload(login_result),
            }
        try:
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return _normalize_3xui_status(node, data.get("obj", {}))
            logger.warning(
                f"ThreeXUIMonitor: server status for {node['name']} returned {res.status_code}"
            )
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                **self._diagnostic_payload(response=res),
            }
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: get_server_status error for {node['name']}: {exc}")
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                **self._diagnostic_payload(error=exc),
            }

    def get_inbounds(self, node: Dict) -> Dict:
        """GET /panel/api/inbounds/list — список inbounds."""
        res, _base_url, login_result = self._request_with_reauth(
            node,
            "GET",
            "/panel/api/inbounds/list",
        )
        if res is None:
            return {
                "node": node["name"],
                "available": False,
                **self._login_failure_payload(login_result),
                "inbounds": [],
            }
        try:
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    inbounds = [
                        self._normalize_inbound(ib, node)
                        for ib in data.get("obj", [])
                        if isinstance(ib, dict)
                    ]
                    return {
                        "node": node["name"],
                        "available": True,
                        "inbounds": inbounds,
                    }
            logger.warning(
                f"ThreeXUIMonitor: inbounds list for {node['name']} returned {res.status_code}"
            )
            return {
                "node": node["name"], "available": False, "inbounds": [],
                **self._diagnostic_payload(response=res),
            }
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: get_inbounds error for {node['name']}: {exc}")
            return {
                "node": node["name"], "available": False, "inbounds": [],
                **self._diagnostic_payload(error=exc),
            }

    def get_traffic(self, node: Dict) -> Dict:
        """Трафик по inbounds (up/down из /panel/api/inbounds/list)."""
        result = self.get_inbounds(node)
        if not result.get("available"):
            return result
        traffic = [
            {
                "id": ib.get("id"),
                "remark": ib.get("remark", ""),
                "protocol": ib.get("protocol", ""),
                "upload": ib.get("up", 0),
                "download": ib.get("down", 0),
                "total": ib.get("up", 0) + ib.get("down", 0),
            }
            for ib in result.get("inbounds", [])
        ]
        return {
            "node": node["name"],
            "available": True,
            "traffic": traffic,
        }

    def get_online_clients(self, node: Dict) -> Dict:
        """List online clients via modern 3x-ui API with a legacy fallback."""
        res, _base_url, login_result = self._request_first_supported(
            node,
            "POST",
            "online_clients",
            (
                "/panel/api/clients/onlines",
                "/panel/api/inbounds/onlines",
            ),
        )
        if res is None:
            return {
                "node": node["name"],
                "available": False,
                **self._login_failure_payload(login_result),
                "online_clients": [],
            }
        try:
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {
                        "node": node["name"],
                        "available": True,
                        "online_clients": data.get("obj", []),
                    }
            logger.warning(
                f"ThreeXUIMonitor: online clients for {node['name']} returned {res.status_code}"
            )
            return {
                "node": node["name"], "available": False, "online_clients": [],
                **self._diagnostic_payload(response=res, endpoint_probe=res.status_code in (404, 405)),
            }
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: get_online_clients error for {node['name']}: {exc}")
            return {
                "node": node["name"], "available": False, "online_clients": [],
                **self._diagnostic_payload(error=exc),
            }

    def get_client_traffic(self, node: Dict, email: str) -> Dict:
        """Read client traffic via modern 3x-ui API with a legacy fallback."""
        safe_email = quote(email, safe="")
        res, _base_url, login_result = self._request_first_supported(
            node,
            "GET",
            "client_traffic",
            (
                f"/panel/api/clients/traffic/{safe_email}",
                f"/panel/api/inbounds/getClientTraffics/{safe_email}",
            ),
        )
        if res is None:
            return {
                "node": node["name"],
                "available": False,
                **self._login_failure_payload(login_result),
            }
        try:
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    obj = data.get("obj")
                    if not isinstance(obj, dict):
                        obj = {}
                    return {
                        "node": node["name"],
                        "available": True,
                        "email": email,
                        "upload": obj.get("up", 0),
                        "download": obj.get("down", 0),
                        "total": obj.get("up", 0) + obj.get("down", 0),
                        "enable": obj.get("enable", True),
                        "expiryTime": obj.get("expiryTime", 0),
                    }
            logger.warning(
                f"ThreeXUIMonitor: client traffic for {email}@{node['name']} returned {res.status_code}"
            )
            return {
                "node": node["name"], "available": False,
                **self._diagnostic_payload(response=res, endpoint_probe=res.status_code in (404, 405)),
            }
        except Exception as exc:
            logger.warning(
                f"ThreeXUIMonitor: get_client_traffic error for {email}@{node['name']}: {exc}"
            )
            return {
                "node": node["name"], "available": False,
                **self._diagnostic_payload(error=exc),
            }


class ServerMonitor:
    def __init__(self, decrypt_func):
        """Инициализация монитора серверов

        Args:
            decrypt_func: Функция для расшифровки паролей узлов
        """
        self.decrypt = decrypt_func

    @staticmethod
    def _is_read_only(node: Dict) -> bool:
        return bool(node.get("read_only"))

    @staticmethod
    def _normalize_session_result(session_result: tuple) -> tuple:
        if not isinstance(session_result, tuple):
            return None, None, {"ok": False, "reason": "connection_failed", "error": "Failed to connect"}
        if len(session_result) == 3:
            return session_result
        if len(session_result) == 2:
            session, base_url = session_result
            if session:
                return session, base_url, {"ok": True, "reason": "ok", "error": ""}
            return None, None, {"ok": False, "reason": "connection_failed", "error": "Failed to connect"}
        return None, None, {"ok": False, "reason": "connection_failed", "error": "Failed to connect"}

    @staticmethod
    def _xui_success(res) -> bool:
        try:
            return res.status_code == 200 and res.json().get("success", False)
        except Exception:
            return False
    
    def _get_session(self, node: Dict) -> tuple:
        """Создать авторизованную сессию для узла
        
        Returns:
            Кортеж (session, base_url)
        """
        s = requests.Session()
        s.verify = _requests_verify_value()
        base_url = build_panel_base_url(node)
        
        try:
            username, password, bearer_token = extract_node_auth(node, self.decrypt)
            if not login_panel(s, base_url, username, password, bearer_token=bearer_token):
                logger.warning(f"Failed to login to {node['name']}")
                return None, None
        except Exception as exc:
            logger.warning(f"Failed to login to {node['name']}: {exc}")
            return None, None
        
        return s, base_url
    
    def get_server_status(self, node: Dict) -> Dict:
        """Compatibility facade for the current GET-only status adapter.

        ``ThreeXUIMonitor`` is the canonical implementation.  Keeping this
        public method as a delegation preserves callers of ``ServerMonitor``
        without maintaining a stale POST-based status contract in parallel.
        """
        return ThreeXUIMonitor(self.decrypt).get_server_status(node)
    
    def get_all_servers_status(self, nodes: List[Dict]) -> List[Dict]:
        """Получить статус всех серверов
        
        Args:
            nodes: Список узлов
            
        Returns:
            Список со статусами всех серверов
        """
        statuses = []
        
        for node in nodes:
            status = self.get_server_status(node)
            statuses.append(status)
        
        return statuses
    
    def check_server_availability(self, node: Dict) -> Dict:
        """Проверить доступность сервера (ping + latency)
        
        Args:
            node: Конфигурация узла
            
        Returns:
            Статус доступности и время отклика
        """
        start_time = time.time()
        
        try:
            base_url = build_panel_base_url(node)
            
            # Простой запрос для проверки доступности
            res = requests.get(
                join_panel_url(base_url, "/"),
                verify=_requests_verify_value(),
                timeout=bounded_xui_timeout(),
            )
            
            latency = (time.time() - start_time) * 1000  # в миллисекундах
            
            return {
                "node": node["name"],
                "available": True,
                "latency_ms": round(latency, 2),
                "status_code": res.status_code,
                "timestamp": datetime.now().isoformat()
            }
        except requests.Timeout:
            return {
                "node": node["name"],
                "available": False,
                "error": "Timeout",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as exc:
            return {
                "node": node["name"],
                "available": False,
                "error": str(exc),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_xray_config(self, node: Dict) -> Dict:
        """Получить полную конфигурацию core service с сервера
        
        Args:
            node: Конфигурация узла
            
        Returns:
            Конфигурация core service
        """
        s, base_url = self._get_session(node)
        if not s:
            return {"error": "Failed to connect"}
        
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/getConfigJson")
            
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and data.get("success"):
                    return data
                if isinstance(data, dict):
                    return {"error": data.get("msg") or "API returned unsuccessful response"}
                return {"error": "API returned malformed response"}
            
            return {"error": f"API returned status {res.status_code}"}
        except Exception as exc:
            logger.warning(f"Failed to get core service config from {node['name']}: {exc}")
            return {"error": str(exc)}
    
    def restart_xray(self, node: Dict) -> bool:
        if self._is_read_only(node):
            logger.info(f"Skip restart xray on read-only node {node['name']}")
            return False
        """Перезапустить core service на сервере
        
        Args:
            node: Конфигурация узла
            
        Returns:
            True при успехе
        """
        s, base_url = self._get_session(node)
        if not s:
            return False
        
        modern_endpoint = f"{base_url}/panel/api/server/restartXrayService"
        legacy_endpoint = f"{base_url}/server/restartXrayService"
        try:
            modern_response = xui_request(s, "POST", modern_endpoint, timeout=15)
        except Exception as exc:
            logger.warning("Restart Xray request failed for %s: %s", node["name"], exc)
            return False

        if modern_response.status_code not in (404, 405):
            # A reachable modern endpoint is terminal even when it reports an
            # application failure. Retrying via legacy can perform a second
            # restart after an ambiguous first write.
            return self._xui_success(modern_response)

        try:
            legacy_response = xui_request(s, "POST", legacy_endpoint, timeout=15)
        except Exception as exc:
            logger.warning("Legacy restart Xray request failed for %s: %s", node["name"], exc)
            return False
        return self._xui_success(legacy_response)
    
    def get_server_logs(
        self,
        node: Dict,
        count: int = 100,
        level: str = "info",
        syslog: bool | None = None,
    ) -> Dict:
        """Получить логи сервера
        
        Args:
            node: Конфигурация узла
            count: Количество строк лога
            level: Уровень логов (debug, info, warning, error)
            
        Returns:
            Логи сервера
        """
        count = bounded_log_count(count)
        s, base_url = self._get_session(node)
        if not s:
            return {"error": "Failed to connect"}
        
        try:
            # The pinned v3 OpenAPI declares JSON for the count-in-path
            # endpoints.  Form data is a narrowly bounded compatibility path
            # only when a concrete media-type rejection proves it is needed.
            json_body = {"level": validate_server_log_level(level), "syslog": bool(syslog)}
            form_body = {"level": json_body["level"], "syslog": "true" if syslog else "false"}
            res = None
            logs_endpoint = ""
            v3_form_compat = False

            # v3: count в URL path — POST /panel/api/server/logs/{count}
            try:
                candidate = xui_request(s, "POST",
                                        f"{base_url}/panel/api/server/logs/{count}",
                                        json=json_body, timeout=15)
                if candidate.status_code in (415, 422):
                    candidate = xui_request(s, "POST",
                                            f"{base_url}/panel/api/server/logs/{count}",
                                            data=form_body, timeout=15)
                    v3_form_compat = True
                if candidate.status_code not in (404, 405):
                    res = candidate
                    logs_endpoint = f"{base_url}/panel/api/server/logs/{count}"
            except Exception:
                pass

            # v2 fallback: count в теле запроса
            if res is None:
                try:
                    payload_v2 = {"count": str(count), **form_body}
                    for ep in (f"{base_url}/panel/api/server/logs",
                               f"{base_url}/server/logs"):
                        try:
                            candidate = xui_request(s, "POST", ep, data=payload_v2)
                        except Exception:
                            continue
                        if candidate.status_code not in (404, 405):
                            res = candidate
                            logs_endpoint = ep
                            break
                except Exception:
                    pass

            if res is None:
                return {"error": "Logs endpoint not found"}

            if res.status_code == 200:
                data = res.json()
                if not data.get("success"):
                    return {"error": str(data.get("msg") or "Logs API returned an unsuccessful response")}
                logs = _normalize_log_lines(data.get("obj"))

                # logger.GetLogs can be empty on systemd installations even
                # though journalctl still holds the panel service history.
                # Keep the historical empty-app-log fallback only when the
                # caller omitted syslog. An explicit checkbox choice must be
                # respected and must not silently switch sources.
                if not logs and syslog is None:
                    syslog_payload = {"level": level, "syslog": "true"}
                    if logs_endpoint.endswith(f"/{count}"):
                        request_kwargs = {"data": syslog_payload} if v3_form_compat else {
                            "json": {"level": level, "syslog": True}
                        }
                    else:
                        request_kwargs = {"data": {"count": str(count), **syslog_payload}}
                    syslog_response = xui_request(
                        s,
                        "POST",
                        logs_endpoint,
                        timeout=15,
                        **request_kwargs,
                    )
                    if syslog_response.status_code == 200:
                        syslog_data = syslog_response.json()
                        if syslog_data.get("success"):
                            logs = _normalize_log_lines(syslog_data.get("obj"))
                return {"node": node["name"], "logs": logs, "count": count, "level": level}

            return {"error": f"API returned status {res.status_code}"}
        except Exception as exc:
            logger.warning(f"Failed to get logs from {node['name']}: {exc}")
            return {"error": str(exc)}
    
    def get_database_backup(self, node: Dict) -> Dict:
        """Получить резервную копию базы данных
        
        Args:
            node: Конфигурация узла
            
        Returns:
            База данных в формате base64 или ошибка
        """
        s, base_url = self._get_session(node)
        if not s:
            return {"error": "Failed to connect"}
        
        try:
            # 3x-ui modern endpoint: /panel/api/server/getDb
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/getDb", timeout=15)
            if res.status_code in (404, 405):
                # fallback for old panels
                res = xui_request(s, "GET", f"{base_url}/server/getDb", timeout=15)
            
            if res.status_code == 200:
                # Response can be binary file or JSON wrapper with base64 payload.
                try:
                    data = res.json()
                    if data.get("success"):
                        obj = data.get("obj", "")
                        if isinstance(obj, str):
                            backup_b64 = obj
                        else:
                            backup_b64 = ""
                        return {
                            "node": node["name"],
                            "backup_b64": backup_b64,
                            "encoding": "base64",
                            "timestamp": datetime.now().isoformat()
                        }
                except Exception:
                    # Binary response: keep as base64 to preserve bytes safely.
                    return {
                        "node": node["name"],
                        "backup_b64": base64.b64encode(res.content).decode("ascii"),
                        "encoding": "base64",
                        "timestamp": datetime.now().isoformat()
                    }
            
            return {"error": f"API returned status {res.status_code}"}
        except Exception as exc:
            logger.warning(f"Failed to get database backup from {node['name']}: {exc}")
            return {"error": str(exc)}
    
    def import_database_backup(self, node: Dict, backup_data: str) -> bool:
        if self._is_read_only(node):
            logger.info(f"Skip import database backup on read-only node {node['name']}")
            return False
        """Импортировать резервную копию базы данных
        
        Args:
            node: Конфигурация узла
            backup_data: Данные бэкапа (base64 или SQL)
            
        Returns:
            True при успехе
        """
        s, base_url = self._get_session(node)
        if not s:
            return False
        
        try:
            if not isinstance(backup_data, str) or not backup_data or len(backup_data) > MAX_BACKUP_B64_CHARS:
                return False
            raw_bytes = b""
            try:
                raw_bytes = base64.b64decode(backup_data, validate=True)
            except Exception:
                # Backward compatibility: allow plain SQL/text payload.
                raw_bytes = str(backup_data).encode("utf-8", errors="ignore")
            if not raw_bytes:
                return False

            # 3x-ui modern endpoint: /panel/api/server/importDB
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/server/importDB",
                files={"db": ("backup.db", raw_bytes, "application/octet-stream")},
                timeout=30,
            )
            if res.status_code in (404, 405):
                # fallback for older nodes
                res = xui_request(
                    s,
                    "POST",
                    f"{base_url}/server/importDb",
                    files={"db": ("backup.db", raw_bytes, "application/octet-stream")},
                    timeout=30,
                )
            
            if res.status_code == 200:
                data = res.json()
                return data.get("success", False)
            
            return False
        except Exception as exc:
            logger.warning(f"Failed to import database to {node['name']}: {exc}")
            return False

    def get_server_history(self, node: Dict, metric: str, bucket: int | str = 360) -> Dict:
        """Получить время-серию метрики сервера.

        Endpoint: GET /panel/api/server/history/{metric}/{bucket}
        Возвращает [{t: timestamp, v: value}, ...]

        Допустимые metric: cpu, mem, netUp, netDown, online, load1, load5, load15.
        Допустимые bucket (секунды): 2, 30, 60, 180, 360, 720, 1440, 2880, 10080.
        """
        try:
            metric, bucket = validate_server_history_request(metric, bucket)
        except ValueError as exc:
            return {"node": node["name"], "error": str(exc), "data": []}
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"node": node["name"], "error": login_result.get("error", "login failed"), "data": []}
        try:
            res = xui_request(s, "GET",
                              f"{base_url}/panel/api/server/history/{metric}/{bucket}")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "metric": metric, "bucket": bucket,
                            "data": data.get("obj") or []}
            return {"node": node["name"], "error": f"HTTP {res.status_code}", "data": []}
        except Exception as exc:
            logger.warning("get_server_history failed for %s: %s", node["name"], exc)
            return {"node": node["name"], "error": str(exc), "data": []}

    def get_panel_update_info(self, node: Dict) -> Dict:
        """Проверить доступность обновления 3x-ui панели.

        Endpoint: GET /panel/api/server/getPanelUpdateInfo
        """
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"node": node["name"], "error": login_result.get("error")}
        try:
            res = xui_request(s, "GET",
                              f"{base_url}/panel/api/server/getPanelUpdateInfo",
                              timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "update_info": data.get("obj")}
            return {"node": node["name"], "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.warning("get_panel_update_info failed for %s: %s", node["name"], exc)
            return {"node": node["name"], "error": str(exc)}

    def get_xray_observatory(self, node: Dict) -> Dict:
        """Получить данные Xray Observatory — latency и health outbounds.

        Endpoint: GET /panel/api/server/xrayObservatory
        """
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"node": node["name"], "error": login_result.get("error")}
        try:
            res = xui_request(s, "GET",
                              f"{base_url}/panel/api/server/xrayObservatory")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "observatory": data.get("obj")}
            return {"node": node["name"], "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.debug("get_xray_observatory failed for %s: %s", node["name"], exc)
            return {"node": node["name"], "error": str(exc)}

    def get_api_tokens(self, node: Dict) -> Dict:
        """Получить список API токенов панели.

        Endpoint: GET /panel/api/setting/apiTokens
        """
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"node": node["name"], "error": login_result.get("error"), "tokens": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/setting/apiTokens")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "tokens": data.get("obj") or []}
            return {"node": node["name"], "error": f"HTTP {res.status_code}", "tokens": []}
        except Exception as exc:
            logger.warning("get_api_tokens failed for %s: %s", node["name"], exc)
            return {"node": node["name"], "error": str(exc), "tokens": []}

    def create_api_token(self, node: Dict, name: str) -> Dict:
        """Создать новый API токен на панели.

        Endpoint: POST /panel/api/setting/apiTokens/create
        Возвращает {"token": "...", "id": N} при успехе.
        """
        if self._is_read_only(node):
            return {"error": "read-only"}
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": login_result.get("error")}
        try:
            res = xui_request(s, "POST",
                              f"{base_url}/panel/api/setting/apiTokens/create",
                              json={"name": name})
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("obj") or {}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.warning("create_api_token failed for %s: %s", node["name"], exc)
            return {"error": str(exc)}

    def stop_xray(self, node):
        if self._is_read_only(node):
            return False
        s, base_url, _ = self._normalize_session_result(self._get_session(node))
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/server/stopXrayService", timeout=10)
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("stop_xray %s: %s", node["name"], exc)
            return False

    def get_xray_versions(self, node):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error"), "versions": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/getXrayVersion", timeout=15)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "versions": data.get("obj") or []}
            return {"error": f"HTTP {res.status_code}", "versions": []}
        except Exception as exc:
            return {"error": str(exc), "versions": []}

    def install_xray(self, node, version: str):
        if self._is_read_only(node):
            return {"error": "read-only"}
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            version = validate_path_segment(version, field="xray version")
        except ValueError:
            return {"error": "invalid xray version"}
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/server/installXray/{version}", timeout=180)
            if res.status_code == 200:
                data = res.json()
                return {"success": data.get("success", False), "msg": data.get("msg", "")}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def update_geofile(self, node, file_name: str = ""):
        if self._is_read_only(node):
            return {"error": "read-only"}
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            if file_name:
                file_name = validate_path_segment(file_name, field="geofile name")
        except ValueError:
            return {"error": "invalid geofile name"}
        try:
            path = f"{base_url}/panel/api/server/updateGeofile"
            if file_name:
                path = f"{path}/{file_name}"
            # OpenAPI v3 requires a JSON body.  ``fileName`` is optional, so
            # use an explicit empty object for the all-geofiles action.
            body = {"fileName": file_name} if file_name else {}
            res = xui_request(s, "POST", path, json=body, timeout=60)
            if res.status_code == 200:
                data = res.json()
                return {"success": data.get("success", False), "msg": data.get("msg", "")}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def update_panel(self, node):
        if self._is_read_only(node):
            return {"error": "read-only"}
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/server/updatePanel", timeout=180)
            if res.status_code == 200:
                data = res.json()
                return {"success": data.get("success", False), "msg": data.get("msg", "")}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def get_xray_logs(self, node, count: int = 100, level: str = "info"):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error"), "logs": []}
        count = bounded_log_count(count)
        try:
            # The modern handler consumes URL-encoded PostForm values. It
            # returns structured LogEntry objects, unlike the legacy text API.
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/server/xraylogs/{count}",
                data={
                    "filter": "",
                    "showDirect": "true",
                    "showBlocked": "true",
                    "showProxy": "true",
                },
                timeout=15,
            )
            if res.status_code == 200:
                data = res.json()
                if not data.get("success"):
                    return {"error": str(data.get("msg") or "Xray logs API returned an unsuccessful response"), "logs": []}
                raw = data.get("obj")
                if isinstance(raw, list):
                    logs = [line for line in (_format_xray_log_entry(item) for item in raw) if line]
                else:
                    logs = _normalize_log_lines(raw)
                return {"node": node["name"], "logs": logs}
            return {"error": f"HTTP {res.status_code}", "logs": []}
        except Exception as exc:
            return {"error": str(exc), "logs": []}

    def get_xray_metrics(self, node):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/xrayMetricsState")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "metrics": data.get("obj")}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def get_outbounds_traffic(self, node):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error"), "outbounds": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/xray/getOutboundsTraffic")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "outbounds": data.get("obj") or []}
            return {"error": f"HTTP {res.status_code}", "outbounds": []}
        except Exception as exc:
            return {"error": str(exc), "outbounds": []}

    def generate_uuid(self, node):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/getNewUUID")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"uuid": data.get("obj", "")}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def generate_x25519_cert(self, node):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/getNewX25519Cert")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("obj") or {}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def generate_vless_enc(self, node):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/getNewVlessEnc")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("obj") or {}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def generate_mldsa65(self, node):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/server/getNewmldsa65")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("obj") or {}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def backup_to_telegram(self, node):
        if self._is_read_only(node):
            return {"error": "read-only"}
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": r.get("error")}
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/backuptotgbot", timeout=30)
            if res.status_code == 200:
                data = res.json()
                return {"success": data.get("success", False), "msg": data.get("msg", "")}
            return {"error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def delete_api_token(self, node, token_id: int):
        if self._is_read_only(node):
            return False
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/setting/apiTokens/delete/{token_id}")
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("delete_api_token %s: %s", node["name"], exc)
            return False

    def set_api_token_enabled(self, node, token_id: int, enabled: bool):
        if self._is_read_only(node):
            return False
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return False
        try:
            res = xui_request(s, "POST",
                              f"{base_url}/panel/api/setting/apiTokens/setEnabled/{token_id}",
                              json={"enabled": enabled})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("set_api_token_enabled %s: %s", node["name"], exc)
            return False
