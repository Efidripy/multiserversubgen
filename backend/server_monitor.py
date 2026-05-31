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
from typing import List, Dict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from xui_session import (
    XUI_FAST_RETRIES,
    XUI_FAST_TIMEOUT_SEC,
    XUI_HTTP_TIMEOUT_SEC,
    extract_node_auth,
    get_authenticated_session,
    invalidate_session_cache,
    make_node_key,
    login_panel,
    xui_request,
)
from utils import parse_field_as_dict

logger = logging.getLogger("sub_manager")
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
CA_BUNDLE_PATH = os.getenv("CA_BUNDLE_PATH", "").strip()


def _requests_verify_value():
    if not VERIFY_TLS:
        return False
    if CA_BUNDLE_PATH:
        return CA_BUNDLE_PATH
    return True


class ThreeXUIMonitor:
    """Монитор 3x-UI с cookie-based аутентификацией.

    Использует корректные HTTP-методы согласно 3x-UI API v26.2.6.
    """

    def __init__(self, decrypt_func):
        self.decrypt = decrypt_func

    def _invalidate_cached_session(self, node: Dict) -> None:
        invalidate_session_cache(make_node_key(node.get("ip"), node.get("port"), node.get("base_path", "")))

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

    def _get_session(self, node: Dict) -> tuple:
        """Создать авторизованную сессию для узла.

        Returns:
            Кортеж (session, base_url) или (None, None) при ошибке.
        """
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        try:
            username, password, bearer_token = extract_node_auth(node, self.decrypt)
            auth = get_authenticated_session(
                node_key=make_node_key(node.get("ip"), node.get("port"), node.get("base_path", "")),
                base_url=base_url,
                username=username,
                password=password,
                bearer_token=bearer_token,
                verify_value=_requests_verify_value(),
                timeout=XUI_FAST_TIMEOUT_SEC,
                retries=XUI_FAST_RETRIES,
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
        return auth["session"], auth["base_url"], {"ok": True, "reason": "ok", "error": ""}

    def get_server_status(self, node: Dict) -> Dict:
        """GET /panel/api/server/status — статус CPU, RAM, диска, core service, сети."""
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                "reason": login_result.get("reason", "connection_failed"),
                "error": login_result.get("error") or "Failed to connect",
            }
        try:
            res = xui_request(
                s,
                "GET",
                f"{base_url}/panel/api/server/status",
            )
            if res.status_code in (401, 403):
                self._invalidate_cached_session(node)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    obj = data.get("obj", {})
                    mem = obj.get("mem", {})
                    disk = obj.get("disk", {})
                    xray = obj.get("xray", {})
                    return {
                        "node": node["name"],
                        "available": True,
                        "timestamp": datetime.now().isoformat(),
                        "system": {
                            "cpu": obj.get("cpu", 0),
                            "mem": {
                                "current": mem.get("current", 0),
                                "total": mem.get("total", 1),
                                "percent": round(
                                    mem.get("current", 0) / max(mem.get("total", 1), 1) * 100, 2
                                ),
                            },
                            "disk": {
                                "current": disk.get("current", 0),
                                "total": disk.get("total", 1),
                                "percent": round(
                                    disk.get("current", 0) / max(disk.get("total", 1), 1) * 100, 2
                                ),
                            },
                            "swap": {
                                "current": obj.get("swap", {}).get("current", 0),
                                "total": obj.get("swap", {}).get("total", 0),
                            },
                            "uptime": obj.get("uptime", 0),
                            "loads": obj.get("loads", []),
                        },
                        "xray": {
                            "state": xray.get("state", ""),
                            "running": xray.get("state", "") == "running",
                            "version": xray.get("version", ""),
                            "uptime": xray.get("uptime", 0),
                        },
                        "network": {
                            "upload": obj.get("netTraffic", {}).get("sent", 0),
                            "download": obj.get("netTraffic", {}).get("recv", 0),
                        },
                    }
            logger.warning(
                f"ThreeXUIMonitor: server status for {node['name']} returned {res.status_code}"
            )
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                "reason": f"http_{res.status_code}",
                "error": f"HTTP {res.status_code}",
            }
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: get_server_status error for {node['name']}: {exc}")
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                "reason": "request_failed",
                "error": str(exc),
            }

    def get_inbounds(self, node: Dict) -> Dict:
        """GET /panel/api/inbounds/list — список inbounds."""
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {
                "node": node["name"],
                "available": False,
                "reason": login_result.get("reason", "connection_failed"),
                "error": login_result.get("error") or "Failed to connect",
                "inbounds": [],
            }
        try:
            res = xui_request(
                s,
                "GET",
                f"{base_url}/panel/api/inbounds/list",
            )
            if res.status_code in (401, 403):
                self._invalidate_cached_session(node)
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
            return {"node": node["name"], "available": False, "error": f"HTTP {res.status_code}", "inbounds": []}
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: get_inbounds error for {node['name']}: {exc}")
            return {"node": node["name"], "available": False, "error": str(exc), "inbounds": []}

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
        """POST /panel/api/inbounds/onlines — список активных клиентов."""
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {
                "node": node["name"],
                "available": False,
                "reason": login_result.get("reason", "connection_failed"),
                "error": login_result.get("error") or "Failed to connect",
                "online_clients": [],
            }
        try:
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/inbounds/onlines",
            )
            if res.status_code in (401, 403):
                self._invalidate_cached_session(node)
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
            return {"node": node["name"], "available": False, "error": f"HTTP {res.status_code}", "online_clients": []}
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: get_online_clients error for {node['name']}: {exc}")
            return {"node": node["name"], "available": False, "error": str(exc), "online_clients": []}

    def get_client_traffic(self, node: Dict, email: str) -> Dict:
        """GET /panel/api/inbounds/getClientTraffics/{email} — трафик клиента."""
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {
                "node": node["name"],
                "available": False,
                "reason": login_result.get("reason", "connection_failed"),
                "error": login_result.get("error") or "Failed to connect",
            }
        try:
            safe_email = quote(email, safe="")
            res = xui_request(
                s,
                "GET",
                f"{base_url}/panel/api/inbounds/getClientTraffics/{safe_email}",
            )
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
            return {"node": node["name"], "available": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.warning(
                f"ThreeXUIMonitor: get_client_traffic error for {email}@{node['name']}: {exc}"
            )
            return {"node": node["name"], "available": False, "error": str(exc)}


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
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        
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
        """Получить статус системы сервера
        
        Args:
            node: Конфигурация узла
            
        Returns:
            Словарь со статусом системы (CPU, RAM, диск, uptime, core service)
        """
        s, base_url = self._get_session(node)
        if not s:
            return {
                "node": node["name"],
                "available": False,
                "error": "Failed to connect"
            }
        
        try:
            # Primary API endpoint for node panel panel (panel/api path)
            primary_url = f"{base_url}/panel/api/server/status"
            res = xui_request(s, "POST", primary_url)
            
            if res.status_code == 404:
                # Fallback for older node panel versions
                fallback_url = f"{base_url}/server/status"
                logger.debug(f"Primary endpoint 404, falling back to {fallback_url}")
                res = xui_request(s, "POST", fallback_url)
            
            if res.status_code != 200:
                logger.warning(
                    f"Server status request to {node['name']} returned {res.status_code}; "
                    f"url={res.url}; body={res.text[:200]!r}"
                )
            
            if res.status_code == 200:
                data = res.json()
                
                if data.get("success"):
                    obj = data.get("obj", {})
                    
                    return {
                        "node": node["name"],
                        "available": True,
                        "timestamp": datetime.now().isoformat(),
                        "system": {
                            "cpu": obj.get("cpu", 0),
                            "mem": {
                                "current": obj.get("mem", {}).get("current", 0),
                                "total": obj.get("mem", {}).get("total", 0),
                                "percent": round(obj.get("mem", {}).get("current", 0) / obj.get("mem", {}).get("total", 1) * 100, 2)
                            },
                            "disk": {
                                "current": obj.get("disk", {}).get("current", 0),
                                "total": obj.get("disk", {}).get("total", 0),
                                "percent": round(obj.get("disk", {}).get("current", 0) / obj.get("disk", {}).get("total", 1) * 100, 2)
                            },
                            "swap": {
                                "current": obj.get("swap", {}).get("current", 0),
                                "total": obj.get("swap", {}).get("total", 0)
                            },
                            "uptime": obj.get("uptime", 0),
                            "loads": obj.get("loads", [])
                        },
                        "xray": {
                            "state": obj.get("xray", {}).get("state", ""),
                            "running": obj.get("xray", {}).get("state", "") == "running",
                            "version": obj.get("xray", {}).get("version", ""),
                            "uptime": obj.get("xray", {}).get("uptime", 0)
                        },
                        "network": {
                            "upload": obj.get("netTraffic", {}).get("sent", 0),
                            "download": obj.get("netTraffic", {}).get("recv", 0)
                        }
                    }
            
            return {
                "node": node["name"],
                "available": False,
                "error": f"API returned status {res.status_code}"
            }
        except Exception as exc:
            logger.warning(f"Failed to get status from {node['name']}: {exc}")
            return {
                "node": node["name"],
                "available": False,
                "error": str(exc)
            }
    
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
            b_path = node.get("base_path", "").strip("/")
            prefix = f"/{b_path}" if b_path else ""
            base_url = f"https://{node['ip']}:{node['port']}{prefix}"
            
            # Простой запрос для проверки доступности
            res = requests.get(
                f"{base_url}/",
                verify=_requests_verify_value(),
                timeout=XUI_HTTP_TIMEOUT_SEC,
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
            res = xui_request(s, "POST", f"{base_url}/xui/API/inbounds/get")
            
            if res.status_code == 200:
                data = res.json()
                return data
            
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
        
        try:
            endpoints = [
                f"{base_url}/panel/api/server/restartXrayService",
                f"{base_url}/server/restartXrayService",
            ]
            for endpoint in endpoints:
                try:
                    res = xui_request(s, "POST", endpoint, timeout=15)
                except Exception:
                    continue
                if res.status_code != 200:
                    continue
                try:
                    data = res.json()
                    # x-ui can return 200 with {"success": false}
                    if isinstance(data, dict) and "success" in data:
                        if bool(data.get("success")):
                            return True
                        continue
                except Exception:
                    # Older variants may return non-JSON on success.
                    return True
                return True
            return False
        except Exception as exc:
            logger.warning(f"Failed to restart core service on {node['name']}: {exc}")
            return False
    
    def get_server_logs(self, node: Dict, count: int = 100, level: str = "info") -> Dict:
        """Получить логи сервера
        
        Args:
            node: Конфигурация узла
            count: Количество строк лога
            level: Уровень логов (debug, info, warning, error)
            
        Returns:
            Логи сервера
        """
        s, base_url = self._get_session(node)
        if not s:
            return {"error": "Failed to connect"}
        
        try:
            body = {"level": level, "syslog": False}
            res = None

            # v3: count в URL path — POST /panel/api/server/logs/{count}
            try:
                candidate = xui_request(s, "POST",
                                        f"{base_url}/panel/api/server/logs/{count}",
                                        json=body, timeout=15)
                if candidate.status_code != 404:
                    res = candidate
            except Exception:
                pass

            # v2 fallback: count в теле запроса
            if res is None:
                try:
                    payload_v2 = {"count": count, **body}
                    for ep in (f"{base_url}/panel/api/server/logs",
                               f"{base_url}/server/logs"):
                        try:
                            candidate = xui_request(s, "POST", ep, json=payload_v2)
                        except Exception:
                            continue
                        if candidate.status_code != 404:
                            res = candidate
                            break
                except Exception:
                    pass

            if res is None:
                return {"error": "Logs endpoint not found"}

            if res.status_code == 200:
                data = res.json()
                raw_logs = data.get("obj", "")
                if isinstance(raw_logs, list):
                    logs = [str(item) for item in raw_logs]
                else:
                    logs = str(raw_logs).split("\n") if data.get("success") else []
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
            if res.status_code == 404:
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
            if res.status_code == 404:
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

    def get_server_history(self, node: Dict, metric: str, bucket: str = "5m") -> Dict:
        """Получить время-серию метрики сервера.

        Endpoint: GET /panel/api/server/history/{metric}/{bucket}
        Возвращает [{t: timestamp, v: value}, ...]

        Примеры metric: cpu, mem, disk, netSent, netRecv, tcpCount
        Примеры bucket: 1m, 5m, 15m, 1h, 6h, 24h
        """
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

        Endpoint: GET /panel/setting/apiTokens
        """
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"node": node["name"], "error": login_result.get("error"), "tokens": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/setting/apiTokens")
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

        Endpoint: POST /panel/setting/apiTokens/create
        Возвращает {"token": "...", "id": N} при успехе.
        """
        s, base_url, login_result = self._normalize_session_result(self._get_session(node))
        if not s:
            return {"error": login_result.get("error")}
        try:
            res = xui_request(s, "POST",
                              f"{base_url}/panel/setting/apiTokens/create",
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
            path = f"{base_url}/panel/api/server/updateGeofile"
            if file_name:
                path = f"{path}/{file_name}"
            res = xui_request(s, "POST", path, timeout=60)
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
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/server/xraylogs/{count}",
                              json={"level": level, "syslog": False}, timeout=15)
            if res.status_code == 200:
                data = res.json()
                raw = data.get("obj", "")
                logs = raw.split("\n") if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
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
            res = xui_request(s, "GET", f"{base_url}/panel/xray/getOutboundsTraffic")
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
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/setting/apiTokens/delete/{token_id}")
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("delete_api_token %s: %s", node["name"], exc)
            return False

    def set_api_token_enabled(self, node, token_id: int, enabled: bool):
        s, base_url, r = self._normalize_session_result(self._get_session(node))
        if not s:
            return False
        try:
            res = xui_request(s, "POST",
                              f"{base_url}/panel/setting/apiTokens/setEnabled/{token_id}",
                              json={"enabled": enabled})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("set_api_token_enabled %s: %s", node["name"], exc)
            return False
