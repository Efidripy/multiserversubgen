"""
Модуль мониторинга серверов node panel
Статус системы, Xray-процесса, проверка доступности
"""
import requests
import json
import logging
import time
import sys
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from xui_session import login_node panel

logger = logging.getLogger("sub_manager")


class ServerMonitor:
    def __init__(self, decrypt_func):
        """Инициализация монитора серверов
        
        Args:
            decrypt_func: Функция для расшифровки паролей узлов
        """
        self.decrypt = decrypt_func
    
    def _get_session(self, node: Dict) -> tuple:
        """Создать авторизованную сессию для узла
        
        Returns:
            Кортеж (session, base_url)
        """
        s = requests.Session()
        s.verify = False
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        
        try:
            password = self.decrypt(node.get('password', ''))
            if not login_node panel(s, base_url, node['user'], password):
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
            Словарь со статусом системы (CPU, RAM, диск, uptime, Xray)
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
            res = s.post(primary_url, timeout=5)
            
            if res.status_code == 404:
                # Fallback for older node panel versions
                fallback_url = f"{base_url}/server/status"
                logger.debug(f"Primary endpoint 404, falling back to {fallback_url}")
                res = s.post(fallback_url, timeout=5)
            
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
            res = requests.get(f"{base_url}/", verify=False, timeout=5)
            
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
        """Получить полную конфигурацию Xray с сервера
        
        Args:
            node: Конфигурация узла
            
        Returns:
            Конфигурация Xray
        """
        s, base_url = self._get_session(node)
        if not s:
            return {"error": "Failed to connect"}
        
        try:
            res = s.post(f"{base_url}/xui/API/inbounds/get", timeout=5)
            
            if res.status_code == 200:
                data = res.json()
                return data
            
            return {"error": f"API returned status {res.status_code}"}
        except Exception as exc:
            logger.warning(f"Failed to get Xray config from {node['name']}: {exc}")
            return {"error": str(exc)}
    
    def restart_xray(self, node: Dict) -> bool:
        """Перезапустить Xray на сервере
        
        Args:
            node: Конфигурация узла
            
        Returns:
            True при успехе
        """
        s, base_url = self._get_session(node)
        if not s:
            return False
        
        try:
            res = s.post(f"{base_url}/server/restartXrayService", timeout=10)
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to restart Xray on {node['name']}: {exc}")
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
            
            res = s.post(f"{base_url}/server/logs", json=payload, timeout=5)
            
            if res.status_code == 200:
                data = res.json()
                return {
                    "node": node["name"],
                    "logs": data.get("obj", "").split("\n") if data.get("success") else [],
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
            # API endpoint для получения бэкапа БД
            res = s.get(f"{base_url}/server/getDb", timeout=10)
            
            if res.status_code == 200:
                # Ответ может быть в виде файла или JSON с base64
                try:
                    data = res.json()
                    if data.get("success"):
                        return {
                            "node": node["name"],
                            "backup": data.get("obj", ""),
                            "timestamp": datetime.now().isoformat()
                        }
                except:
                    # Если ответ - файл, возвращаем его содержимое
                    return {
                        "node": node["name"],
                        "backup": res.content.decode('utf-8', errors='ignore'),
                        "timestamp": datetime.now().isoformat()
                    }
            
            return {"error": f"API returned status {res.status_code}"}
        except Exception as exc:
            logger.warning(f"Failed to get database backup from {node['name']}: {exc}")
            return {"error": str(exc)}
    
    def import_database_backup(self, node: Dict, backup_data: str) -> bool:
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
            # API endpoint для импорта БД
            res = s.post(f"{base_url}/server/importDb", 
                        data={"db": backup_data}, 
                        timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                return data.get("success", False)
            
            return False
        except Exception as exc:
            logger.warning(f"Failed to import database to {node['name']}: {exc}")
            return False
