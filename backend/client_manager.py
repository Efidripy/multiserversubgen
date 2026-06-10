"""
Модуль управления клиентами node panel
Содержит функции для управления клиентами: добавление, обновление, удаление, статистика
"""
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
from xui_session import (
    XUI_FAST_RETRIES, XUI_FAST_TIMEOUT_SEC,
    build_panel_base_url,
    extract_node_auth, get_authenticated_session, make_node_key_for_node, xui_request,
    get_node_api_version, set_node_api_version,
)
from utils import parse_field_as_dict

logger = logging.getLogger("sub_manager")
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
CA_BUNDLE_PATH = os.getenv("CA_BUNDLE_PATH", "").strip()
TRAFFIC_MAX_WORKERS = max(1, int(os.getenv("TRAFFIC_MAX_WORKERS", "8")))

# Shared executor: переиспользуется между вызовами вместо пересоздания
_shared_executor = ThreadPoolExecutor(max_workers=TRAFFIC_MAX_WORKERS, thread_name_prefix="client_mgr")


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

    @staticmethod
    def _is_read_only(node: Dict) -> bool:
        return bool(node.get("read_only"))

    @staticmethod
    def _xui_success(res) -> bool:
        if res.status_code != 200:
            return False
        try:
            data = res.json()
            if isinstance(data, dict) and "success" in data:
                return bool(data.get("success"))
        except Exception:
            pass
        return True
    
    def _get_session(self, node: Dict) -> tuple:
        """Создать авторизованную сессию для узла
        
        Returns:
            Кортеж (session, base_url)
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
            )
            if not auth.get("ok"):
                logger.warning(f"Failed to login to {node['name']}")
                return None, None
        except Exception as exc:
            logger.warning(f"Failed to login to {node['name']}: {exc}")
            return None, None

        return auth["session"], auth["base_url"]
    
    def _fetch_inbounds_from_node(self, node: Dict) -> List[Dict]:
        """Получить инбаунды с узла"""
        s, base_url = self._get_session(node)
        if not s:
            return []
        
        try:
            res = xui_request(
                s,
                "GET",
                f"{base_url}/panel/api/inbounds/list",
                timeout=XUI_FAST_TIMEOUT_SEC,
                retries=XUI_FAST_RETRIES,
            )
            if res.status_code == 200:
                data = res.json()
                return data.get("obj", []) if data.get("success", False) else []
        except Exception as exc:
            logger.warning(f"Failed to fetch inbounds from {node['name']}: {exc}")
        
        return []

    
    # ------------------------------------------------------------------
    # v3 API helpers — 3x-ui >= 3.x first-class client endpoints
    # ------------------------------------------------------------------

    def _probe_v3(self, s, base_url: str) -> Optional[List[Dict]]:
        """Попробовать GET /panel/api/clients/list (v3).
        Возвращает список объектов клиентов, или None если endpoint недоступен (v2 нода).
        """
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/list",
                              timeout=XUI_FAST_TIMEOUT_SEC, retries=XUI_FAST_RETRIES)
            if res.status_code == 404:
                return None  # v2 нода
            if res.status_code != 200:
                return []
            data = res.json()
            return data.get("obj") or [] if data.get("success") else []
        except Exception as exc:
            logger.debug("v3 clients list probe failed for %s: %s", base_url, exc)
            return None

    def _map_v3_client(self, c: Dict, node: Dict) -> Dict:
        """Конвертировать v3 client object в наш внутренний формат."""
        inbound_ids: List[int] = c.get("inboundIds") or []
        traffic: Dict = c.get("traffic") or {}
        return {
            "id": c.get("uuid", ""),
            "email": c.get("email", ""),
            "enable": c.get("enable", True),
            "expiryTime": c.get("expiryTime", 0),
            "totalGB": c.get("totalGB", 0),
            "flow": c.get("flow", ""),
            "node_id": node.get("id"),
            "node_name": node["name"],
            "node_ip": node.get("ip", ""),
            "inbound_id": inbound_ids[0] if inbound_ids else None,
            "inbound_ids": inbound_ids,
            "inbound_remark": "",   # недоступно в v3 list без доп. запроса
            "protocol": "",         # аналогично
            "password": "",
            "traffic_up": traffic.get("up", 0),
            "traffic_down": traffic.get("down", 0),
        }

    def _add_client_v3(self, s, base_url: str, email: str,
                       inbound_ids: List[int], config: Dict) -> bool:
        """POST /panel/api/clients/add — v3 single call."""
        payload = {
            "client": {
                "email": email,
                "enable": config.get("enable", True),
                "totalGB": config.get("totalGB", 0),
                "expiryTime": config.get("expiryTime", 0),
                "limitIp": config.get("limitIp", 0),
                "tgId": config.get("tgId", 0),
            },
            "inboundIds": inbound_ids,
        }
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/add", json=payload)
            if res.status_code == 404:
                return None  # type: ignore  # v2 fallback needed
            data = res.json()
            return bool(data.get("success"))
        except Exception as exc:
            logger.warning("v3 add_client failed: %s", exc)
            return False

    def _update_client_v3(self, s, base_url: str, email: str, updates: Dict) -> Optional[bool]:
        """POST /panel/api/clients/update/{email} — v3."""
        payload = {"email": email, **updates}
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/update/{email}",
                              json=payload)
            if res.status_code == 404:
                return None  # v2 fallback
            return bool(res.json().get("success"))
        except Exception as exc:
            logger.warning("v3 update_client failed: %s", exc)
            return False

    def _delete_client_v3(self, s, base_url: str, email: str,
                          keep_traffic: bool = False) -> Optional[bool]:
        """POST /panel/api/clients/del/{email} — v3."""
        try:
            url = f"{base_url}/panel/api/clients/del/{email}"
            if keep_traffic:
                url += "?keepTraffic=1"
            res = xui_request(s, "POST", url)
            if res.status_code == 404:
                return None  # v2 fallback
            return bool(res.json().get("success"))
        except Exception as exc:
            logger.warning("v3 delete_client failed: %s", exc)
            return False

    def _bulk_delete_v3(self, s, base_url: str, emails: List[str],
                        keep_traffic: bool = False) -> Optional[Dict]:
        """POST /panel/api/clients/bulkDel — v3 batch delete."""
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/bulkDel",
                              json={"emails": emails, "keepTraffic": keep_traffic})
            if res.status_code == 404:
                return None  # v2 fallback
            data = res.json()
            return data.get("obj") if data.get("success") else None
        except Exception as exc:
            logger.warning("v3 bulkDel failed: %s", exc)
            return None

    def _get_online_v3(self, s, base_url: str) -> Optional[List[str]]:
        """POST /panel/api/clients/onlines — v3."""
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/onlines")
            if res.status_code == 404:
                return None
            data = res.json()
            return data.get("obj") or [] if data.get("success") else None
        except Exception as exc:
            logger.debug("v3 onlines failed: %s", exc)
            return None

    def _get_traffic_v3(self, s, base_url: str, email: str) -> Optional[Dict]:
        """GET /panel/api/clients/traffic/{email} — v3."""
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/traffic/{email}")
            if res.status_code == 404:
                return None
            data = res.json()
            return data.get("obj") if data.get("success") else None
        except Exception as exc:
            logger.debug("v3 traffic failed: %s", exc)
            return None

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
            s, base_url = self._get_session(node)
            if not s:
                return node_clients

            try:
                # Определяем версию API (из кеша или проверяем)
                api_version = get_node_api_version(base_url)
                if api_version != "v2":
                    # Пробуем v3
                    v3_obj = self._probe_v3(s, base_url)
                    if v3_obj is not None:
                        set_node_api_version(base_url, "v3")
                        for c in v3_obj:
                            email = c.get("email", "")
                            if needle and needle not in email.lower():
                                continue
                            node_clients.append(self._map_v3_client(c, node))
                        return node_clients
                    # v3 вернул None → нода v2
                    set_node_api_version(base_url, "v2")

                # v2 fallback: извлекаем клиентов из инбаундов
                try:
                    inbounds_res = xui_request(
                        s, "GET", f"{base_url}/panel/api/inbounds/list",
                        timeout=XUI_FAST_TIMEOUT_SEC, retries=XUI_FAST_RETRIES,
                    )
                    inbounds = []
                    if inbounds_res.status_code == 200:
                        data = inbounds_res.json()
                        inbounds = data.get("obj", []) if data.get("success") else []
                except Exception as exc:
                    logger.warning("Failed to fetch inbounds from %s: %s", node["name"], exc)

                for inbound in inbounds:
                    try:
                        settings = parse_field_as_dict(
                            inbound.get("settings"), node_id=node["name"], field_name="settings"
                        )
                        for client in settings.get("clients", []):
                            client_email = client.get("email", "")
                            if needle and needle not in client_email.lower():
                                continue
                            node_clients.append({
                                "id": client.get("id"),
                                "email": client_email,
                                "enable": client.get("enable", True),
                                "expiryTime": client.get("expiryTime", 0),
                                "totalGB": client.get("totalGB", 0),
                                "flow": client.get("flow", ""),
                                "node_id": node.get("id"),
                                "node_name": node["name"],
                                "node_ip": node["ip"],
                                "inbound_id": inbound.get("id"),
                                "inbound_remark": inbound.get("remark", ""),
                                "protocol": inbound.get("protocol"),
                                "password": client.get("password", "") if inbound.get("protocol") == "trojan" else "",
                            })
                    except (TypeError, ValueError) as exc:
                        logger.warning("Invalid settings for inbound in %s: %s", node["name"], exc)
            except Exception as exc:
                logger.warning("Failed to fetch clients from %s: %s", node["name"], exc)
            return node_clients

        all_clients: List[Dict] = []
        futures = [_shared_executor.submit(_collect_node_clients, node) for node in nodes]
        for future in as_completed(futures):
            try:
                all_clients.extend(future.result())
            except Exception as exc:
                logger.warning(f"Failed to aggregate clients: {exc}")

        return all_clients
    
    def add_client(self, node: Dict, inbound_id: int, client_config: Dict) -> bool:
        if self._is_read_only(node):
            logger.info(f"Skip add client on read-only node {node['name']}")
            return False
        """Добавить клиента в инбаунд"""
        email = client_config.get("email", "")
        logger.info(
            "add_client START node=%r inbound_id=%s email=%r config=%s",
            node["name"], inbound_id, email,
            {k: v for k, v in client_config.items() if k not in ("id", "password")},
        )
        s, base_url = self._get_session(node)
        if not s:
            logger.warning("add_client: session failed for node=%r email=%r", node["name"], email)
            return False

        try:
            api_version = get_node_api_version(base_url)
            logger.debug("add_client: api_version=%r node=%r", api_version, node["name"])
            if api_version != "v2":
                result = self._add_client_v3(
                    s, base_url,
                    email=email,
                    inbound_ids=[inbound_id],
                    config=client_config,
                )
                if result is not None:
                    set_node_api_version(base_url, "v3")
                    logger.info("add_client v3 END node=%r email=%r result=%s", node["name"], email, result)
                    return result
                set_node_api_version(base_url, "v2")
                logger.debug("add_client: v3 returned None, falling back to v2 for node=%r", node["name"])

            # v2 fallback
            payload = {
                "id": inbound_id,
                "settings": json.dumps({"clients": [client_config]})
            }
            res = xui_request(s, "POST", f"{base_url}/panel/api/inbounds/addClient", json=payload)

            # 404 on v2 endpoint → node is actually v3, retry with v3 API and update cache
            if res.status_code == 404:
                logger.info("add_client: v2 /addClient 404, upgrading node=%r to v3", node["name"])
                result = self._add_client_v3(s, base_url, email=email, inbound_ids=[inbound_id], config=client_config)
                if result is not None:
                    set_node_api_version(base_url, "v3")
                    logger.info("add_client v3 upgrade END node=%r email=%r result=%s", node["name"], email, result)
                    return result

            ok = self._xui_success(res)
            logger.info("add_client v2 END node=%r email=%r result=%s http_status=%s", node["name"], email, ok, res.status_code)
            return ok
        except Exception as exc:
            logger.warning("add_client FAILED node=%r email=%r inbound_id=%s error=%s", node["name"], email, inbound_id, exc)
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
        if self._is_read_only(node):
            logger.info(f"Skip update client on read-only node {node['name']}")
            return False
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
            # v3: update by email, no UUID or inbound_id needed
            email = updates.get("email") or ""
            if email and get_node_api_version(base_url) != "v2":
                result = self._update_client_v3(s, base_url, email, updates)
                if result is not None:
                    set_node_api_version(base_url, "v3")
                    return result
                set_node_api_version(base_url, "v2")

            # v2 fallback
            payload = {
                "id": inbound_id,
                "settings": json.dumps({"clients": [{"id": client_uuid, **updates}]})
            }
            res = xui_request(s, "POST",
                              f"{base_url}/panel/api/inbounds/updateClient/{client_uuid}",
                              json=payload)
            return self._xui_success(res)
        except Exception as exc:
            logger.warning(f"Failed to update client on {node['name']}: {exc}")
            return False

    def delete_client(self, node: Dict, inbound_id: int, client_uuid: str) -> bool:
        if self._is_read_only(node):
            logger.info(f"Skip delete client on read-only node {node['name']}")
            return False
        """Удалить клиента из инбаунда/по email (v3) или по UUID (v2)."""
        s, base_url = self._get_session(node)
        if not s:
            return False

        try:
            # v3: delete by email — client_uuid may actually be an email string
            # Если передан email (содержит @) или нода точно v3 — пробуем v3
            is_email = "@" in str(client_uuid) or "." in str(client_uuid)
            if (is_email or get_node_api_version(base_url) != "v2"):
                result = self._delete_client_v3(s, base_url, str(client_uuid))
                if result is not None:
                    set_node_api_version(base_url, "v3")
                    return result
                set_node_api_version(base_url, "v2")

            # v2 fallback: delete by UUID
            res = xui_request(s, "POST",
                              f"{base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}")
            return self._xui_success(res)
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
            errors: List[str] = []

            try:
                # Собираем все клиенты ноды (v3 или v2)
                all_clients = self.get_all_clients([node])
                emails_to_delete: List[str] = []

                for client in all_clients:
                    client_email = client.get("email", "")

                    should_delete = True
                    if email_pattern and email_pattern.lower() not in client_email.lower():
                        should_delete = False
                    if expired_only:
                        expiry = client.get("expiryTime", 0)
                        if expiry == 0 or expiry > now_ms:
                            should_delete = False
                    if depleted_only:
                        traffic = self.get_client_traffic(
                            node,
                            client_email if "@" in client_email else (client.get("id") or ""),
                            client.get("protocol", ""),
                        )
                        total_limit = client.get("totalGB", 0)
                        if total_limit > 0:
                            used_gb = (traffic.get("up", 0) + traffic.get("down", 0)) / (1024 ** 3)
                            if used_gb < total_limit:
                                should_delete = False
                        else:
                            should_delete = False

                    if should_delete:
                        emails_to_delete.append(client_email)

                if not emails_to_delete:
                    results.append({"node": node["name"], "deleted_count": 0, "errors": []})
                    continue

                # v3: bulkDel — один запрос вместо N
                s, base_url = self._get_session(node)
                if s and get_node_api_version(base_url) == "v3":
                    bulk_result = self._bulk_delete_v3(s, base_url, emails_to_delete)
                    if bulk_result is not None:
                        deleted_count = bulk_result.get("deleted", len(emails_to_delete))
                        skipped = [sk.get("email", "") for sk in (bulk_result.get("skipped") or [])]
                        errors = skipped
                        results.append({"node": node["name"], "deleted_count": deleted_count, "errors": errors})
                        continue

                # v2 fallback: delete one by one
                for client in all_clients:
                    if client.get("email") not in emails_to_delete:
                        continue
                    inbound_id = client.get("inbound_id")
                    client_identifier = client.get("id") or client.get("email") or ""
                    if not inbound_id:
                        errors.append(client.get("email", ""))
                        continue
                    success = self.delete_client(node, inbound_id, client_identifier)
                    if success:
                        deleted_count += 1
                    else:
                        errors.append(client.get("email", ""))

            except Exception as exc:
                logger.warning(f"Failed batch delete on {node['name']}: {exc}")
                errors.append(str(exc))

            results.append({"node": node["name"], "deleted_count": deleted_count, "errors": errors})
        
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
            # v3: GET /panel/api/clients/traffic/{email}
            if "@" in str(client_uuid) or get_node_api_version(base_url) == "v3":
                result = self._get_traffic_v3(s, base_url, str(client_uuid))
                if result is not None:
                    set_node_api_version(base_url, "v3")
                    return result if isinstance(result, dict) else {}
                set_node_api_version(base_url, "v2")

            # v2 fallback: endpoint depends on protocol
            if protocol in ("vless", "vmess"):
                endpoint = f"{base_url}/panel/api/inbounds/getClientTrafficsById/{client_uuid}"
            else:
                endpoint = f"{base_url}/panel/api/inbounds/getClientTraffics/{client_uuid}"
            res = xui_request(s, "GET", endpoint)
            if res.status_code == 200:
                data = res.json()
                obj = data.get("obj", {})
                if not isinstance(obj, dict):
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
        if self._is_read_only(node):
            logger.info(f"Skip reset client traffic on read-only node {node['name']}")
            return False
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
            if self._is_read_only(node):
                results.append({
                    "node": node["name"],
                    "reset_count": 0,
                    "error": "Node is read-only",
                })
                continue
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
                # v3: POST /panel/api/clients/onlines
                if get_node_api_version(base_url) != "v2":
                    emails = self._get_online_v3(s, base_url)
                    if emails is not None:
                        set_node_api_version(base_url, "v3")
                        return [{"email": e, "node": node["name"]} for e in emails]
                    set_node_api_version(base_url, "v2")

                # v2 fallback: POST /panel/api/inbounds/onlines
                res = xui_request(s, "POST", f"{base_url}/panel/api/inbounds/onlines")
                if res.status_code == 200:
                    data = res.json()
                    if data.get("success"):
                        return [{"email": c, "node": node["name"]} for c in (data.get("obj", []) or [])]
            except Exception as exc:
                logger.warning(f"Failed to get online clients from {node['name']}: {exc}")
            return []

        futures = [_shared_executor.submit(fetch_node_online, node) for node in nodes]
        for future in as_completed(futures):
            try:
                online_clients.extend(future.result())
            except Exception as exc:
                logger.warning(f"Failed to aggregate online clients: {exc}")

        return online_clients

    def del_depleted(self, nodes: List[Dict]) -> Dict:
        """Удалить всех истощённых клиентов на нодах.

        v3: POST /panel/api/clients/delDepleted — один запрос на ноду.
        v2 fallback: batch_delete_clients(depleted_only=True).
        """
        results = []
        for node in nodes:
            if self._is_read_only(node):
                results.append({"node": node["name"], "deleted": 0, "error": "read-only"})
                continue
            s, base_url = self._get_session(node)
            if not s:
                results.append({"node": node["name"], "deleted": 0, "error": "login failed"})
                continue
            try:
                if get_node_api_version(base_url) != "v2":
                    res = xui_request(s, "POST", f"{base_url}/panel/api/clients/delDepleted")
                    if res.status_code != 404:
                        data = res.json()
                        if data.get("success"):
                            set_node_api_version(base_url, "v3")
                            obj = data.get("obj") or {}
                            results.append({"node": node["name"], "deleted": obj.get("deleted", 0)})
                            continue
                # v2 fallback
                fallback = self.batch_delete_clients([node], depleted_only=True)
                deleted = sum(r.get("deleted_count", 0) for r in fallback.get("results", []))
                results.append({"node": node["name"], "deleted": deleted})
            except Exception as exc:
                logger.warning("del_depleted failed for %s: %s", node["name"], exc)
                results.append({"node": node["name"], "deleted": 0, "error": str(exc)})
        total = sum(r.get("deleted", 0) for r in results)
        return {"results": results, "total_deleted": total}

    def bulk_adjust(self, nodes: List[Dict], emails: List[str],
                    add_days: int = 0, add_bytes: int = 0) -> Dict:
        """Продлить срок/трафик группе клиентов.

        v3: POST /panel/api/clients/bulkAdjust — один запрос на ноду.
        v2 fallback: обновить каждого клиента по одному.

        Args:
            emails: Список email-адресов клиентов.
            add_days: Дней добавить к expiryTime (может быть отрицательным).
            add_bytes: Байт добавить к totalGB (может быть отрицательным).
        """
        results = []
        for node in nodes:
            if self._is_read_only(node):
                results.append({"node": node["name"], "adjusted": 0, "error": "read-only"})
                continue
            s, base_url = self._get_session(node)
            if not s:
                results.append({"node": node["name"], "adjusted": 0, "error": "login failed"})
                continue
            try:
                if get_node_api_version(base_url) != "v2":
                    payload: Dict = {"emails": emails}
                    if add_days:
                        payload["addDays"] = add_days
                    if add_bytes:
                        payload["addBytes"] = add_bytes
                    res = xui_request(s, "POST",
                                      f"{base_url}/panel/api/clients/bulkAdjust",
                                      json=payload)
                    if res.status_code != 404:
                        data = res.json()
                        if data.get("success"):
                            set_node_api_version(base_url, "v3")
                            obj = data.get("obj") or {}
                            results.append({
                                "node": node["name"],
                                "adjusted": obj.get("adjusted", 0),
                                "skipped": obj.get("skipped", []),
                            })
                            continue
                # v2 fallback: update each client individually
                adjusted = 0
                now_ms = int(__import__("time").time() * 1000)
                ms_per_day = 86400 * 1000
                node_clients = self.get_all_clients([node])
                for c in node_clients:
                    if c.get("email") not in emails:
                        continue
                    updates: Dict = {}
                    if add_bytes:
                        current_gb = c.get("totalGB", 0)
                        updates["totalGB"] = max(0, current_gb + add_bytes)
                    if add_days:
                        expiry = c.get("expiryTime", 0) or 0
                        base_ms = max(expiry, now_ms) if expiry else now_ms
                        updates["expiryTime"] = base_ms + add_days * ms_per_day
                    if updates:
                        ok = self.update_client(
                            node,
                            c.get("inbound_id", 0),
                            c.get("id", ""),
                            {**updates, "email": c["email"]},
                        )
                        if ok:
                            adjusted += 1
                results.append({"node": node["name"], "adjusted": adjusted, "skipped": []})
            except Exception as exc:
                logger.warning("bulk_adjust failed for %s: %s", node["name"], exc)
                results.append({"node": node["name"], "adjusted": 0, "error": str(exc)})
        total = sum(r.get("adjusted", 0) for r in results)
        return {"results": results, "total_adjusted": total}

    def get_client_links(self, node: Dict, email: str) -> List[str]:
        """Получить subscription links для клиента.

        v3: GET /panel/api/clients/links/{email} — панель генерирует ссылки сама.
        v2: возвращает пустой список (ссылки строятся через subscription_links.py).
        """
        s, base_url = self._get_session(node)
        if not s:
            return []
        try:
            if get_node_api_version(base_url) != "v2":
                res = xui_request(s, "GET",
                                  f"{base_url}/panel/api/clients/links/{email}")
                if res.status_code != 404:
                    data = res.json()
                    if data.get("success"):
                        set_node_api_version(base_url, "v3")
                        return data.get("obj") or []
        except Exception as exc:
            logger.debug("get_client_links failed for %s/%s: %s", node["name"], email, exc)
        return []

    # ---------------------------------------------------------------------------
    # IP tracking
    # ---------------------------------------------------------------------------

    def get_client_ips(self, node: Dict, email: str) -> Dict:
        """GET /panel/api/clients/ips/{email} — recent connection IPs."""
        s, base_url = self._get_session(node)
        if not s:
            return {"ips": []}
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/ips/{email}")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    obj = data.get("obj") or ""
                    ips = [ip.strip() for ip in obj.split("\n") if ip.strip()] if isinstance(obj, str) else (obj if isinstance(obj, list) else [])
                    return {"ips": ips}
        except Exception as exc:
            logger.debug("get_client_ips failed for %s/%s: %s", node["name"], email, exc)
        return {"ips": []}

    def clear_client_ips(self, node: Dict, email: str) -> bool:
        """POST /panel/api/clients/clearIps/{email} — wipe stored IPs."""
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/clearIps/{email}")
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("clear_client_ips failed for %s/%s: %s", node["name"], email, exc)
            return False

    def get_last_online(self, node: Dict, emails: Optional[List[str]] = None) -> Dict:
        """POST /panel/api/clients/lastOnline — last-seen timestamps."""
        s, base_url = self._get_session(node)
        if not s:
            return {"data": {}}
        try:
            body = {"emails": emails} if emails else {}
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/lastOnline", json=body)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"data": data.get("obj") or {}}
        except Exception as exc:
            logger.debug("get_last_online failed for %s: %s", node["name"], exc)
        return {"data": {}}

    # ---------------------------------------------------------------------------
    # Bulk traffic reset
    # ---------------------------------------------------------------------------

    def bulk_reset_traffic(self, nodes: List[Dict], emails: List[str]) -> Dict:
        """POST /panel/api/clients/bulkResetTraffic — reset traffic for specific emails."""
        successful = 0
        failed = 0
        for node in nodes:
            if self._is_read_only(node):
                continue
            s, base_url = self._get_session(node)
            if not s:
                failed += len(emails)
                continue
            try:
                res = xui_request(s, "POST", f"{base_url}/panel/api/clients/bulkResetTraffic", json={"emails": emails})
                if res.status_code == 200 and res.json().get("success"):
                    successful += len(emails)
                else:
                    # Fall back: reset individually
                    for email in emails:
                        try:
                            r2 = xui_request(s, "POST", f"{base_url}/panel/api/clients/resetClientTraffic/{email}")
                            if r2.status_code == 200 and r2.json().get("success"):
                                successful += 1
                            else:
                                failed += 1
                        except Exception:
                            failed += 1
            except Exception as exc:
                logger.debug("bulk_reset_traffic failed for %s: %s", node["name"], exc)
                failed += len(emails)
        return {"successful": successful, "failed": failed, "total": successful + failed}

    # ---------------------------------------------------------------------------
    # Attach / Detach (v3 only)
    # ---------------------------------------------------------------------------

    def attach_client(self, node: Dict, email: str, inbound_ids: List[int]) -> bool:
        """POST /panel/api/clients/{email}/attach — attach client to additional inbounds."""
        if self._is_read_only(node):
            return False
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/{email}/attach", json={"inboundIds": inbound_ids})
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("attach_client failed for %s/%s: %s", node["name"], email, exc)
            return False

    def detach_client(self, node: Dict, email: str, inbound_ids: List[int]) -> bool:
        """POST /panel/api/clients/{email}/detach — detach client from inbounds."""
        if self._is_read_only(node):
            return False
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/{email}/detach", json={"inboundIds": inbound_ids})
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("detach_client failed for %s/%s: %s", node["name"], email, exc)
            return False

    # ---------------------------------------------------------------------------
    # Client groups (v3 only)
    # ---------------------------------------------------------------------------

    def get_client_groups(self, node: Dict) -> Dict:
        """GET /panel/api/clients/groups — list all client groups."""
        s, base_url = self._get_session(node)
        if not s:
            return {"groups": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/groups")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    obj = data.get("obj") or []
                    groups = [g if isinstance(g, str) else g.get("name", "") for g in obj]
                    return {"groups": [g for g in groups if g]}
        except Exception as exc:
            logger.debug("get_client_groups failed for %s: %s", node["name"], exc)
        return {"groups": []}

    def create_client_group(self, node: Dict, name: str) -> bool:
        """POST /panel/api/clients/groups/create — create a new group."""
        if self._is_read_only(node):
            return False
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/create", json={"name": name})
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("create_client_group failed for %s/%s: %s", node["name"], name, exc)
            return False

    def rename_client_group(self, node: Dict, old_name: str, new_name: str) -> bool:
        """POST /panel/api/clients/groups/rename."""
        if self._is_read_only(node):
            return False
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/rename", json={"oldName": old_name, "newName": new_name})
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("rename_client_group failed for %s: %s", node["name"], exc)
            return False

    def delete_client_group(self, node: Dict, name: str) -> bool:
        """POST /panel/api/clients/groups/delete."""
        if self._is_read_only(node):
            return False
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/delete", json={"name": name})
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("delete_client_group failed for %s/%s: %s", node["name"], name, exc)
            return False

    def add_to_group(self, node: Dict, group_name: str, emails: List[str]) -> bool:
        """POST /panel/api/clients/groups/bulkAdd."""
        if self._is_read_only(node):
            return False
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/bulkAdd", json={"groupName": group_name, "emails": emails})
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("add_to_group failed for %s/%s: %s", node["name"], group_name, exc)
            return False

    def remove_from_group(self, node: Dict, group_name: str, emails: List[str]) -> bool:
        """POST /panel/api/clients/groups/bulkRemove."""
        if self._is_read_only(node):
            return False
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/bulkRemove", json={"groupName": group_name, "emails": emails})
            return res.status_code == 200 and res.json().get("success", False)
        except Exception as exc:
            logger.debug("remove_from_group failed for %s/%s: %s", node["name"], group_name, exc)
            return False

    def get_group_emails(self, node: Dict, group_name: str) -> Dict:
        """GET /panel/api/clients/groups/{name}/emails."""
        s, base_url = self._get_session(node)
        if not s:
            return {"emails": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/groups/{group_name}/emails")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"emails": data.get("obj") or []}
        except Exception as exc:
            logger.debug("get_group_emails failed for %s/%s: %s", node["name"], group_name, exc)
        return {"emails": []}

    # ---------------------------------------------------------------------------
    # Sub-links by subscription ID
    # ---------------------------------------------------------------------------

    def get_sub_links(self, node: Dict, sub_id: str) -> List[str]:
        """GET /panel/api/clients/subLinks/{subId} — get links for a subscription ID."""
        s, base_url = self._get_session(node)
        if not s:
            return []
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/subLinks/{sub_id}")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("obj") or []
        except Exception as exc:
            logger.debug("get_sub_links failed for %s/%s: %s", node["name"], sub_id, exc)
        return []
