"""
Модуль мониторинга серверов node panel
Статус системы, core service-процесса, проверка доступности
"""
import requests
import json
import logging
import base64
from urllib.parse import quote
import time
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from xui_session import (
    XUI_FAST_RETRIES,
    XUI_FAST_TIMEOUT_SEC,
    XUI_HTTP_TIMEOUT_SEC,
    login_panel,
    login_panel_detailed,
    xui_request,
)

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
        s = requests.Session()
        s.verify = _requests_verify_value()
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        try:
            password = self.decrypt(node.get("password", ""))
            login_result = login_panel_detailed(
                s,
                base_url,
                node["user"],
                password,
                timeout=XUI_FAST_TIMEOUT_SEC,
                retries=XUI_FAST_RETRIES,
            )
            if not login_result.get("ok"):
                logger.warning(f"ThreeXUIMonitor: failed to login to {node['name']}")
                return None, None, login_result
        except Exception as exc:
            logger.warning(f"ThreeXUIMonitor: login error for {node['name']}: {exc}")
            return None, None, {
                "ok": False,
                "reason": "monitor_exception",
                "error": str(exc),
            }
        return s, base_url, {"ok": True, "reason": "ok", "error": ""}

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
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {
                        "node": node["name"],
                        "available": True,
                        "inbounds": data.get("obj", []),
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
            password = self.decrypt(node.get('password', ''))
            if not login_panel(s, base_url, node['user'], password):
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
            payload = {
                "count": count,
                "level": level,
                "syslog": False
            }
            
            endpoints = [
                f"{base_url}/panel/api/server/logs",
                f"{base_url}/server/logs",
            ]
            res = None
            for endpoint in endpoints:
                try:
                    candidate = xui_request(s, "POST", endpoint, json=payload)
                except Exception:
                    continue
                if candidate.status_code == 404:
                    continue
                res = candidate
                break

            if res is None:
                return {"error": "Logs endpoint not found"}

            if res.status_code == 200:
                data = res.json()
                raw_logs = data.get("obj", "")
                if isinstance(raw_logs, list):
                    logs = [str(item) for item in raw_logs]
                else:
                    logs = str(raw_logs).split("\n") if data.get("success") else []
                return {
                    "node": node["name"],
                    "logs": logs,
                    "count": count,
                    "level": level
                }
            
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
