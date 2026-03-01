"""
Модуль управления клиентами node panel
Содержит функции для управления клиентами: добавление, обновление, удаление, статистика
"""
import requests
import json
import logging
import uuid
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from xui_session import login_node panel, xui_request
from utils import parse_field_as_dict

logger = logging.getLogger("sub_manager")
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
CA_BUNDLE_PATH = os.getenv("CA_BUNDLE_PATH", "").strip()
TRAFFIC_MAX_WORKERS = max(1, int(os.getenv("TRAFFIC_MAX_WORKERS", "8")))


def _requests_verify_value():
    if not VERIFY_TLS:
        return False
    if CA_BUNDLE_PATH:
        return CA_BUNDLE_PATH
    return True


class ClientManager:
    def __init__(self, decrypt_func, encrypt_func=None):
        """Инициализация менеджера клиентов с функциями шифрования/дешифрования
        
        Args:
            decrypt_func: Функция для расшифровки паролей узлов
            encrypt_func: Опциональная функция для шифрования паролей
        """
        self.decrypt = decrypt_func
        self.encrypt = encrypt_func
    
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
            if not login_node panel(s, base_url, node['user'], password):
                logger.warning(f"Failed to login to {node['name']}")
                return None, None
        except Exception as exc:
            logger.warning(f"Failed to login to {node['name']}: {exc}")
            return None, None
        
        return s, base_url
    
    def _fetch_inbounds_from_node(self, node: Dict) -> List[Dict]:
        """Получить инбаунды с узла"""
        s, base_url = self._get_session(node)
        if not s:
            return []
        
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/inbounds/list")
            if res.status_code == 200:
                data = res.json()
                return data.get("obj", []) if data.get("success", False) else []
        except Exception as exc:
            logger.warning(f"Failed to fetch inbounds from {node['name']}: {exc}")
        
        return []
    
    def get_all_clients(self, nodes: List[Dict], email_filter: Optional[str] = None) -> List[Dict]:
        """Получить всех клиентов со всех узлов
        
        Args:
            nodes: Список узлов
            email_filter: Опциональный фильтр по email/имени клиента
            
        Returns:
            Список клиентов с метаданными
        """
        if not nodes:
            return []

        needle = email_filter.lower() if email_filter else ""

        def _collect_node_clients(node: Dict) -> List[Dict]:
            node_clients: List[Dict] = []
            try:
                inbounds = self._fetch_inbounds_from_node(node)
                for inbound in inbounds:
                    try:
                        settings = parse_field_as_dict(
                            inbound.get("settings"), node_id=node["name"], field_name="settings"
                        )
                        clients = settings.get("clients", [])

                        for client in clients:
                            client_email = client.get("email", "")
                            if needle and needle not in client_email.lower():
                                continue

                            client_data = {
                                "id": client.get("id"),
                                "email": client_email,
                                "enable": client.get("enable", True),
                                "expiryTime": client.get("expiryTime", 0),
                                "totalGB": client.get("totalGB", 0),
                                "flow": client.get("flow", ""),
                                "node_name": node["name"],
                                "node_ip": node["ip"],
                                "inbound_id": inbound.get("id"),
                                "inbound_remark": inbound.get("remark", ""),
                                "protocol": inbound.get("protocol"),
                                "password": client.get("password", "") if inbound.get("protocol") == "trojan" else "",
                            }
                            node_clients.append(client_data)
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Invalid settings for inbound in {node['name']}: {exc}")
            except Exception as exc:
                logger.warning(f"Failed to fetch clients from {node['name']}: {exc}")
            return node_clients

        all_clients: List[Dict] = []
        workers = min(len(nodes), TRAFFIC_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_collect_node_clients, node) for node in nodes]
            for future in as_completed(futures):
                try:
                    all_clients.extend(future.result())
                except Exception as exc:
                    logger.warning(f"Failed to aggregate clients: {exc}")

        return all_clients
    
    def add_client(self, node: Dict, inbound_id: int, client_config: Dict) -> bool:
        """Добавить клиента в инбаунд
        
        Args:
            node: Конфигурация узла
            inbound_id: ID инбаунда
            client_config: Конфигурация клиента
            
        Returns:
            True при успехе
        """
        s, base_url = self._get_session(node)
        if not s:
            return False
        
        try:
            payload = {
                "id": inbound_id,
                "settings": json.dumps({"clients": [client_config]})
            }
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/inbounds/addClient",
                json=payload,
            )
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to add client to {node['name']}: {exc}")
            return False
    
    def batch_add_clients(self, nodes: List[Dict], clients_configs: List[Dict]) -> Dict:
        """Массово добавить клиентов на узлы
        
        Args:
            nodes: Список узлов для добавления
            clients_configs: Список конфигураций клиентов, каждая должна содержать:
                - email: Email клиента
                - inbound_id: ID инбаунда (или можно указать inbound_remark)
                - totalGB: Лимит трафика в GB (опционально)
                - expiryTime: Время истечения в ms (опционально)
                - enable: Активен ли клиент (по умолчанию True)
                
        Returns:
            Результаты добавления по узлам
        """
        results = []
        
        for node in nodes:
            node_results = []
            
            # Получить инбаунды узла для поиска по remark
            inbounds = self._fetch_inbounds_from_node(node)
            
            for client_config in clients_configs:
                # Найти inbound_id если указан remark
                inbound_id = client_config.get("inbound_id")
                if not inbound_id and client_config.get("inbound_remark"):
                    matching = [ib for ib in inbounds 
                               if ib.get("remark") == client_config["inbound_remark"]]
                    if matching:
                        inbound_id = matching[0]["id"]
                
                if not inbound_id:
                    node_results.append({
                        "email": client_config.get("email"),
                        "success": False,
                        "error": "Inbound not found"
                    })
                    continue
                
                # Получить протокол инбаунда для генерации правильного ID
                inbound = next((ib for ib in inbounds if ib["id"] == inbound_id), None)
                if not inbound:
                    node_results.append({
                        "email": client_config.get("email"),
                        "success": False,
                        "error": "Inbound not found"
                    })
                    continue
                
                protocol = inbound.get("protocol")
                
                # Создать конфигурацию клиента
                new_client = {
                    "email": client_config.get("email", ""),
                    "enable": client_config.get("enable", True),
                    "expiryTime": client_config.get("expiryTime", 0),
                    "totalGB": client_config.get("totalGB", 0),
                    "flow": client_config.get("flow", "")
                }
                
                # Генерация ID/password в зависимости от протокола
                if protocol == "trojan":
                    new_client["password"] = str(uuid.uuid4())
                else:
                    new_client["id"] = str(uuid.uuid4())
                
                success = self.add_client(node, inbound_id, new_client)
                node_results.append({
                    "email": client_config.get("email"),
                    "success": success,
                    "inbound_id": inbound_id
                })
            
            results.append({
                "node": node["name"],
                "results": node_results
            })
        
        return {"results": results}
    
    def update_client(self, node: Dict, inbound_id: int, client_uuid: str, updates: Dict) -> bool:
        """Обновить параметры клиента
        
        Args:
            node: Конфигурация узла
            inbound_id: ID инбаунда
            client_uuid: UUID клиента
            updates: Обновляемые параметры (email, enable, totalGB, expiryTime и т.д.)
            
        Returns:
            True при успехе
        """
        s, base_url = self._get_session(node)
        if not s:
            return False
        
        try:
            payload = {
                "id": inbound_id,
                "settings": json.dumps({
                    "clients": [{
                        "id": client_uuid,
                        **updates
                    }]
                })
            }
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/inbounds/updateClient/{client_uuid}",
                json=payload,
            )
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to update client on {node['name']}: {exc}")
            return False
    
    def delete_client(self, node: Dict, inbound_id: int, client_uuid: str) -> bool:
        """Удалить клиента из инбаунда
        
        Args:
            node: Конфигурация узла
            inbound_id: ID инбаунда
            client_uuid: UUID клиента
            
        Returns:
            True при успехе
        """
        s, base_url = self._get_session(node)
        if not s:
            return False
        
        try:
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}",
            )
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to delete client from {node['name']}: {exc}")
            return False
    
    def batch_delete_clients(self, nodes: List[Dict], email_pattern: Optional[str] = None,
                            expired_only: bool = False, depleted_only: bool = False) -> Dict:
        """Массово удалить клиентов с фильтрацией
        
        Args:
            nodes: Список узлов
            email_pattern: Паттерн для фильтрации по email (contains)
            expired_only: Удалить только истекших клиентов
            depleted_only: Удалить только клиентов с исчерпанным трафиком
            
        Returns:
            Результаты удаления
        """
        results = []
        now_ms = int(datetime.now().timestamp() * 1000)
        
        for node in nodes:
            deleted_count = 0
            errors = []
            
            try:
                inbounds = self._fetch_inbounds_from_node(node)
                
                for inbound in inbounds:
                    try:
                        settings = parse_field_as_dict(
                            inbound.get("settings"), node_id=node["name"], field_name="settings"
                        )
                        clients = settings.get("clients", [])
                        
                        for client in clients:
                            client_email = client.get("email", "")
                            
                            # Применить фильтры
                            should_delete = True
                            
                            if email_pattern and email_pattern.lower() not in client_email.lower():
                                should_delete = False
                            
                            if expired_only:
                                expiry = client.get("expiryTime", 0)
                                if expiry == 0 or expiry > now_ms:
                                    should_delete = False
                            
                            if depleted_only:
                                # Проверить статистику трафика
                                traffic = self.get_client_traffic(node, client.get("id", ""), 
                                                                 inbound.get("protocol", ""))
                                total_limit = client.get("totalGB", 0)
                                if total_limit > 0:
                                    used_gb = (traffic.get("up", 0) + traffic.get("down", 0)) / (1024**3)
                                    if used_gb < total_limit:
                                        should_delete = False
                                else:
                                    should_delete = False
                            
                            if should_delete:
                                success = self.delete_client(node, inbound["id"], client.get("id", ""))
                                if success:
                                    deleted_count += 1
                                else:
                                    errors.append(client_email)
                    except Exception as exc:
                        logger.warning(f"Error processing inbound in {node['name']}: {exc}")
            except Exception as exc:
                logger.warning(f"Failed batch delete on {node['name']}: {exc}")
                errors.append(str(exc))
            
            results.append({
                "node": node["name"],
                "deleted_count": deleted_count,
                "errors": errors
            })
        
        return {"results": results}
    
    def get_client_traffic(self, node: Dict, client_uuid: str, protocol: str) -> Dict:
        """Получить статистику трафика клиента
        
        Args:
            node: Конфигурация узла
            client_uuid: UUID клиента
            protocol: Протокол (vless, vmess, trojan и т.д.)
            
        Returns:
            Словарь с данными трафика (up, down, total)
        """
        s, base_url = self._get_session(node)
        if not s:
            return {}
        
        try:
            # API endpoint зависит от протокола
            if protocol in ("vless", "vmess"):
                endpoint = f"{base_url}/panel/api/inbounds/getClientTrafficsById/{client_uuid}"
            else:
                endpoint = f"{base_url}/panel/api/inbounds/getClientTraffics/{client_uuid}"
            
            res = xui_request(s, "GET", endpoint)
            if res.status_code == 200:
                data = res.json()
                obj = data.get("obj", {})
                if not isinstance(obj, dict):
                    logger.warning(
                        f"Unexpected type for traffic obj on {node['name']}: "
                        f"expected dict, got {type(obj).__name__}"
                    )
                    return {}
                return obj
        except Exception as exc:
            logger.warning(f"Failed to get client traffic from {node['name']}: {exc}")
        
        return {}
    
    def _build_stats_for_node(self, node: Dict, group_by: str) -> Dict[str, Dict[str, int]]:
        """Построить статистику для одного узла."""
        node_stats: Dict[str, Dict[str, int]] = {}
        inbounds = self._fetch_inbounds_from_node(node)

        for inbound in inbounds:
            try:
                client_stats = inbound.get("clientStats")
                if isinstance(client_stats, list):
                    for cstat in client_stats:
                        if not isinstance(cstat, dict):
                            continue
                        up = cstat.get("up", 0) or 0
                        down = cstat.get("down", 0) or 0
                        client_email = cstat.get("email", "")

                        if group_by == "client":
                            key = client_email
                        elif group_by == "inbound":
                            key = f"{node['name']}:{inbound.get('remark', inbound.get('id'))}"
                        else:  # node
                            key = node["name"]

                        if key not in node_stats:
                            node_stats[key] = {"up": 0, "down": 0, "total": 0, "count": 0}
                        node_stats[key]["up"] += up
                        node_stats[key]["down"] += down
                        node_stats[key]["total"] += up + down
                        node_stats[key]["count"] += 1
                    continue

                # Compatibility fallback for older/non-standard panels.
                settings = parse_field_as_dict(
                    inbound.get("settings"), node_id=node["name"], field_name="settings"
                )
                clients = settings.get("clients", [])
                protocol = inbound.get("protocol", "")

                for client in clients:
                    client_uuid = client.get("id", "")
                    client_email = client.get("email", "")
                    traffic = self.get_client_traffic(node, client_uuid, protocol)
                    up = traffic.get("up", 0)
                    down = traffic.get("down", 0)

                    if group_by == "client":
                        key = client_email
                    elif group_by == "inbound":
                        key = f"{node['name']}:{inbound.get('remark', inbound.get('id'))}"
                    else:  # node
                        key = node["name"]

                    if key not in node_stats:
                        node_stats[key] = {"up": 0, "down": 0, "total": 0, "count": 0}
                    node_stats[key]["up"] += up
                    node_stats[key]["down"] += down
                    node_stats[key]["total"] += up + down
                    node_stats[key]["count"] += 1
            except Exception as exc:
                logger.warning(f"Error processing inbound stats in {node['name']}: {exc}")

        return node_stats

    def get_traffic_stats(self, nodes: List[Dict], group_by: str = "client") -> Dict:
        """Получить агрегированную статистику трафика
        
        Args:
            nodes: Список узлов
            group_by: Группировка ("client", "inbound", "node")
            
        Returns:
            Агрегированная статистика
        """
        stats: Dict[str, Dict[str, int]] = {}
        if not nodes:
            return {"stats": stats, "group_by": group_by}

        workers = min(len(nodes), TRAFFIC_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._build_stats_for_node, node, group_by): node for node in nodes}
            for future in as_completed(futures):
                node = futures[future]
                try:
                    node_stats = future.result()
                    for key, item in node_stats.items():
                        if key not in stats:
                            stats[key] = {"up": 0, "down": 0, "total": 0, "count": 0}
                        stats[key]["up"] += item.get("up", 0)
                        stats[key]["down"] += item.get("down", 0)
                        stats[key]["total"] += item.get("total", 0)
                        stats[key]["count"] += item.get("count", 0)
                except Exception as exc:
                    logger.warning(f"Failed to get stats from {node.get('name', 'unknown')}: {exc}")

        return {"stats": stats, "group_by": group_by}
    
    def reset_client_traffic(self, node: Dict, inbound_id: int, client_email: str) -> bool:
        """Сбросить статистику трафика клиента
        
        Args:
            node: Конфигурация узла
            inbound_id: ID инбаунда
            client_email: Email клиента
            
        Returns:
            True при успехе
        """
        s, base_url = self._get_session(node)
        if not s:
            return False
        
        try:
            payload = {
                "id": inbound_id,
                "email": client_email
            }
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/inbounds/resetClientTraffic/{client_email}",
                json=payload,
            )
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to reset client traffic on {node['name']}: {exc}")
            return False
    
    def reset_all_traffic(self, nodes: List[Dict], inbound_id: Optional[int] = None) -> Dict:
        """Сбросить весь трафик на узлах (или для конкретного инбаунда)
        
        Args:
            nodes: Список узлов
            inbound_id: Опциональный ID инбаунда для сброса только его трафика
            
        Returns:
            Результаты операции
        """
        results = []
        
        for node in nodes:
            reset_count = 0
            
            try:
                inbounds = self._fetch_inbounds_from_node(node)
                
                # Фильтровать по inbound_id если указан
                if inbound_id:
                    inbounds = [ib for ib in inbounds if ib.get("id") == inbound_id]
                
                for inbound in inbounds:
                    s, base_url = self._get_session(node)
                    if not s:
                        continue
                    
                    try:
                        res = xui_request(
                            s,
                            "POST",
                            f"{base_url}/panel/api/inbounds/resetAllTraffics/{inbound['id']}",
                        )
                        if res.status_code == 200:
                            reset_count += 1
                    except Exception as exc:
                        logger.warning(f"Failed to reset inbound {inbound['id']} on {node['name']}: {exc}")
            except Exception as exc:
                logger.warning(f"Failed reset operation on {node['name']}: {exc}")
            
            results.append({
                "node": node["name"],
                "reset_count": reset_count
            })
        
        return {"results": results}
    
    def add_client_to_multiple_nodes(self, nodes: List[Dict], email: str, inbound_id: int,
                                      flow: str = "", totalGB: int = 0,
                                      expiryTime: int = 0, enable: bool = True) -> Dict:
        """Добавить клиента на несколько узлов одновременно с автогенерацией UUID и subId=email.

        Args:
            nodes: Список узлов для добавления
            email: Email клиента (используется также как subId)
            inbound_id: ID инбаунда на каждом узле
            flow: Поток XTLS ("", "xtls-rprx-vision", "xtls-rprx-vision-udp443")
            totalGB: Лимит трафика в GB
            expiryTime: Время истечения в мс
            enable: Активен ли клиент

        Returns:
            Словарь с результатами по каждому узлу
        """
        valid_flows = {"", "xtls-rprx-vision", "xtls-rprx-vision-udp443"}
        if flow not in valid_flows:
            raise ValueError(f"Invalid flow value. Must be one of: {sorted(valid_flows)}")

        results = []
        total = len(nodes)
        successful = 0
        failed = 0

        for node in nodes:
            # Fetch inbounds to determine protocol
            inbounds = self._fetch_inbounds_from_node(node)
            inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)

            if not inbound:
                results.append({
                    "node": node["name"],
                    "success": False,
                    "error": f"Inbound {inbound_id} not found"
                })
                failed += 1
                continue

            protocol = inbound.get("protocol", "")

            # Build client config — auto-generate UUID; set subId equal to email
            new_client: Dict = {
                "email": email,
                "subId": email,
                "enable": enable,
                "expiryTime": expiryTime,
                "totalGB": totalGB,
                "flow": flow,
            }

            if protocol == "trojan":
                new_client["password"] = str(uuid.uuid4())
            else:
                new_client["id"] = str(uuid.uuid4())

            success = self.add_client(node, inbound_id, new_client)
            entry: Dict = {"node": node["name"], "success": success}
            if not success:
                entry["error"] = "Failed to add client"
                failed += 1
            else:
                successful += 1
            results.append(entry)

        return {
            "results": results,
            "summary": {"total": total, "successful": successful, "failed": failed},
        }

    def get_online_clients(self, nodes: List[Dict]) -> List[Dict]:
        """Получить список активных (онлайн) клиентов
        
        Args:
            nodes: Список узлов
            
        Returns:
            Список онлайн клиентов
        """
        online_clients = []
        if not nodes:
            return online_clients

        def fetch_node_online(node: Dict) -> List[Dict]:
            s, base_url = self._get_session(node)
            if not s:
                return []
            try:
                res = xui_request(s, "POST", f"{base_url}/panel/api/inbounds/onlines")
                if res.status_code == 200:
                    data = res.json()
                    if data.get("success"):
                        return [{"email": c, "node": node["name"]} for c in (data.get("obj", []) or [])]
            except Exception as exc:
                logger.warning(f"Failed to get online clients from {node['name']}: {exc}")
            return []

        workers = min(len(nodes), TRAFFIC_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_node_online, node) for node in nodes]
            for future in as_completed(futures):
                try:
                    online_clients.extend(future.result())
                except Exception as exc:
                    logger.warning(f"Failed to aggregate online clients: {exc}")

        return online_clients
