"""
Модуль управления клиентами node panel
Содержит функции для управления клиентами: добавление, обновление, удаление, статистика
"""
import json
import logging
import uuid
import sys
import os
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from xui_session import (
    XUI_FAST_RETRIES, XUI_FAST_TIMEOUT_SEC,
    build_panel_base_url,
    extract_node_auth, get_authenticated_session, make_node_key_for_node, xui_request,
    # Imported for compatibility with older integrations/tests only. Version
    # telemetry is deliberately not used as a routing authority below.
    get_node_api_version, set_node_api_version,  # noqa: F401 - legacy telemetry import surface
)
from utils import parse_field_as_dict

logger = logging.getLogger("sub_manager")
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
CA_BUNDLE_PATH = os.getenv("CA_BUNDLE_PATH", "").strip()
TRAFFIC_MAX_WORKERS = max(1, int(os.getenv("TRAFFIC_MAX_WORKERS", "8")))

# Shared executor: переиспользуется между вызовами вместо пересоздания
_shared_executor = ThreadPoolExecutor(max_workers=TRAFFIC_MAX_WORKERS, thread_name_prefix="client_mgr")


def _path_segment(value: object) -> str:
    """Encode one opaque 3x-ui path segment without changing route delimiters."""
    return quote(str(value), safe="")


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
            # A successful HTTP status without a JSON body is not proof that
            # a mutation was applied.  Keep compatibility with wrappers that
            # omit ``success``, but fail closed on malformed/non-JSON bodies.
            return isinstance(data, dict)
        except Exception:
            return False
    
    def _get_session(self, node: Dict, *, force_reauth: bool = False) -> tuple:
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
                force_reauth=force_reauth,
            )
            if not auth.get("ok"):
                logger.warning(f"Failed to login to {node['name']}")
                return None, None
        except Exception as exc:
            logger.warning(f"Failed to login to {node['name']}: {exc}")
            return None, None

        return auth["session"], auth["base_url"]

    def _retry_v3_after_reauth(self, node: Dict, operation):
        """Repeat a v3 operation once with a fresh session after 404/405.

        Some 3x-ui builds deliberately return a panel-API 404 for an expired
        cookie.  A route is therefore legacy-only only when the same request
        is still 404/405 after a forced login.  Callers must use this helper
        only for the exact same v3 operation; it never invokes a v2 write.
        """
        fresh_session, fresh_base_url = self._get_session(node, force_reauth=True)
        if not fresh_session:
            return "reauth_failed", None, None, None
        try:
            result = operation(fresh_session, fresh_base_url)
            return ("confirmed_absent" if result is None else "response"), result, fresh_session, fresh_base_url
        except Exception as exc:
            logger.warning("v3 retry after re-auth failed for %s: %s", node.get("name"), exc)
            return "retry_failed", None, fresh_session, fresh_base_url
    
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

    def _probe_v3(self, s, base_url: str) -> tuple[str, List[Dict]]:
        """Попробовать GET /panel/api/clients/list (v3).

        Возвращает ``(supported|unsupported|failed, clients)``.  Только
        explicit 404/405 означает legacy capability; timeout, TLS/auth и
        malformed responses never permanently downgrade a node to v2.
        """
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/list",
                              timeout=XUI_FAST_TIMEOUT_SEC, retries=XUI_FAST_RETRIES)
            if res.status_code in (404, 405):
                return "unsupported", []
            if res.status_code != 200:
                return "failed", []
            data = res.json()
            if not isinstance(data, dict) or not data.get("success") or not isinstance(data.get("obj"), list):
                return "failed", []
            return "supported", data.get("obj") or []
        except Exception as exc:
            logger.debug("v3 clients list probe failed for %s: %s", base_url, exc)
            return "failed", []

    def _map_v3_client(self, c: Dict, node: Dict) -> Dict:
        """Конвертировать v3 client object в наш внутренний формат."""
        inbound_ids: List[int] = c.get("inboundIds") or []
        traffic: Dict = c.get("traffic") or {}
        return {
            "id": c.get("uuid", ""),
            "db_id": c.get("id"),
            "email": c.get("email", ""),
            "enable": c.get("enable", True),
            "expiryTime": c.get("expiryTime", 0),
            "totalGB": c.get("totalGB", 0),
            "limitIp": c.get("limitIp"),
            "security": c.get("security", ""),
            "subId": c.get("subId", ""),
            "reset": c.get("reset", 0),
            "group": c.get("group", ""),
            "flow": c.get("flow", ""),
            "comment": c.get("comment", ""),
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
            "traffic_total": traffic.get("total", (traffic.get("up", 0) or 0) + (traffic.get("down", 0) or 0)),
        }

    def _add_client_v3(self, s, base_url: str, email: str,
                       inbound_ids: List[int], config: Dict) -> Optional[bool]:
        """POST /panel/api/clients/add — v3 single call."""
        # Keep the client contract explicit.  Passing a hand-picked minimum
        # silently discarded valid 3x-ui fields such as subId, flow and
        # protocol-specific credentials before the panel ever saw them.
        supported_fields = (
            "id", "email", "enable", "totalGB", "expiryTime", "limitIp",
            "tgId", "subId", "flow", "password", "security", "comment",
            "group", "reset", "reverse", "auth", "privateKey", "publicKey",
            "allowedIPs", "preSharedKey", "keepAlive", "secret", "adTag",
        )
        client = {field: config[field] for field in supported_fields if field in config}
        client.update({
            "email": email,
            "enable": config.get("enable", True),
            "totalGB": config.get("totalGB", 0),
            "expiryTime": config.get("expiryTime", 0),
            "limitIp": config.get("limitIp", 0),
            "tgId": config.get("tgId", 0),
            # Required by the v3 Client schema.  Explicit defaults prevent
            # relying on undocumented panel defaults during a remote write.
            "comment": config.get("comment", ""),
            "security": config.get("security", ""),
            "reset": config.get("reset", 0),
            "subId": config.get("subId", email),
        })
        payload = {"client": client, "inboundIds": inbound_ids}
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/add", json=payload)
            if res.status_code in (404, 405):
                return None  # type: ignore  # v2 fallback needed
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("v3 add_client failed: %s", exc)
            return False

    @staticmethod
    def _v3_update_payload(existing: Dict, updates: Dict) -> Dict:
        """Convert the v3 list record to the full object required by update.

        Current 3x-ui binds ``model.Client`` and replaces the stored row.  A
        control-plane update is normally partial, so send the existing fields
        back unchanged and overlay only recognised caller changes.  The list
        endpoint exposes ``uuid`` while the mutation contract expects ``id``.
        """
        payload: Dict = {}
        preserved_fields = (
            "security", "password", "flow", "auth", "privateKey", "publicKey",
            "preSharedKey", "keepAlive", "secret", "adTag", "email", "limitIp",
            "totalGB", "expiryTime", "enable", "tgId", "subId", "group",
            "comment", "reset",
        )
        for field in preserved_fields:
            if field in existing:
                payload[field] = existing[field]

        if existing.get("uuid"):
            payload["id"] = existing["uuid"]
        elif existing.get("id"):
            payload["id"] = existing["id"]

        for field in ("reverse", "allowedIPs"):
            value = existing.get(field)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = None
            if isinstance(value, (dict, list)):
                payload[field] = value

        for field, value in updates.items():
            if field in {*preserved_fields, "id", "reverse", "allowedIPs"}:
                payload[field] = value
        return payload

    def _update_client_v3(self, s, base_url: str, client_identifier: str,
                          inbound_id: int, updates: Dict) -> Optional[bool]:
        """Read and merge a client through the v3 full-replacement contract.

        The caller only carries a local client UUID for many v3 panels.  Match
        it against the authenticated list response to recover the *current*
        email and full client object before issuing the write.
        """
        try:
            listed = xui_request(
                s,
                "GET",
                f"{base_url}/panel/api/clients/list",
                timeout=XUI_FAST_TIMEOUT_SEC,
                retries=XUI_FAST_RETRIES,
            )
            if listed.status_code in (404, 405):
                return None  # v2 fallback
            if listed.status_code != 200:
                return False
            listing = listed.json()
            if not isinstance(listing, dict) or not listing.get("success"):
                return False
            clients = listing.get("obj")
            if not isinstance(clients, list):
                return False

            identifier = str(client_identifier)
            existing = next(
                (
                    client for client in clients
                    if isinstance(client, dict)
                    and identifier in {
                        str(client.get("uuid") or ""),
                        str(client.get("id") or ""),
                        str(client.get("email") or ""),
                    }
                ),
                None,
            )
            if not existing or not existing.get("email"):
                return False

            email = str(existing["email"])
            payload = self._v3_update_payload(existing, updates)
            if not payload.get("email"):
                return False
            # v3 updates propagate through every attached inbound.  The
            # old scoped ``?inboundIds=`` query is undocumented and caused
            # divergent behavior across current panels.
            url = f"{base_url}/panel/api/clients/update/{_path_segment(email)}"
            res = xui_request(s, "POST", url, json=payload)
            if res.status_code in (404, 405):
                return None  # v2 fallback
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("v3 update_client failed: %s", exc)
            return False

    def _delete_client_v3(self, s, base_url: str, client_identifier: str,
                          keep_traffic: bool = False) -> Optional[bool]:
        """Resolve a v3 UUID/email then POST /panel/api/clients/del/{email}."""
        try:
            listed = xui_request(
                s,
                "GET",
                f"{base_url}/panel/api/clients/list",
                timeout=XUI_FAST_TIMEOUT_SEC,
                retries=XUI_FAST_RETRIES,
            )
            if listed.status_code in (404, 405):
                return None  # v2 fallback
            if listed.status_code != 200:
                return False
            listing = listed.json()
            clients = listing.get("obj") if isinstance(listing, dict) and listing.get("success") else None
            if not isinstance(clients, list):
                return False
            identifier = str(client_identifier)
            existing = next(
                (
                    client for client in clients
                    if isinstance(client, dict)
                    and identifier in {
                        str(client.get("uuid") or ""),
                        str(client.get("id") or ""),
                        str(client.get("email") or ""),
                    }
                ),
                None,
            )
            if not existing or not existing.get("email"):
                return False
            email = str(existing["email"])
            url = f"{base_url}/panel/api/clients/del/{_path_segment(email)}?keepTraffic={1 if keep_traffic else 0}"
            res = xui_request(s, "POST", url)
            if res.status_code in (404, 405):
                return None  # v2 fallback
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("v3 delete_client failed: %s", exc)
            return False

    def _bulk_delete_v3(self, s, base_url: str, emails: List[str],
                        keep_traffic: bool = False) -> tuple[str, Dict]:
        """POST /panel/api/clients/bulkDel — v3 batch delete.

        ``unsupported`` is exclusively a documented route-absence signal.
        A completed request with an operational/API error is ``failed`` and
        must never be replayed through a second mutation path.
        """
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/bulkDel",
                              json={"emails": emails, "keepTraffic": keep_traffic})
            if res.status_code in (404, 405):
                return "unsupported", {}
            if res.status_code != 200:
                return "failed", {}
            data = res.json()
            if not isinstance(data, dict) or data.get("success") is not True:
                return "failed", {}
            obj = data.get("obj") or {}
            return ("supported", obj) if isinstance(obj, dict) else ("failed", {})
        except Exception as exc:
            logger.warning("v3 bulkDel failed: %s", exc)
            return "failed", {}

    def _get_online_v3(self, s, base_url: str) -> tuple[str, List[str]]:
        """POST /panel/api/clients/onlines — v3."""
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/onlines")
            if res.status_code in (404, 405):
                return "unsupported", []
            if res.status_code != 200:
                return "failed", []
            data = res.json()
            if not isinstance(data, dict) or not data.get("success") or not isinstance(data.get("obj"), list):
                return "failed", []
            return "supported", data.get("obj") or []
        except Exception as exc:
            logger.debug("v3 onlines failed: %s", exc)
            return "failed", []

    def _get_traffic_v3(self, s, base_url: str, email: str) -> tuple[str, Dict]:
        """GET /panel/api/clients/traffic/{email} — v3."""
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/traffic/{_path_segment(email)}")
            if res.status_code in (404, 405):
                return "unsupported", {}
            if res.status_code != 200:
                return "failed", {}
            data = res.json()
            if not isinstance(data, dict) or not data.get("success") or not isinstance(data.get("obj"), dict):
                return "failed", {}
            return "supported", data.get("obj") or {}
        except Exception as exc:
            logger.debug("v3 traffic failed: %s", exc)
            return "failed", {}

    def _resolve_v3_client_email(self, s, base_url: str, client_identifier: str) -> tuple[str, str]:
        """Resolve a v3 UUID/id to the panel's email-addressed client route."""
        try:
            listed = xui_request(
                s,
                "GET",
                f"{base_url}/panel/api/clients/list",
                timeout=XUI_FAST_TIMEOUT_SEC,
                retries=XUI_FAST_RETRIES,
            )
            if listed.status_code in (404, 405):
                return "unsupported", ""
            if listed.status_code != 200:
                return "failed", ""
            data = listed.json()
            clients = data.get("obj") if isinstance(data, dict) and data.get("success") is True else None
            if not isinstance(clients, list):
                return "failed", ""
            identifier = str(client_identifier)
            match = next(
                (
                    client for client in clients
                    if isinstance(client, dict)
                    and identifier in {
                        str(client.get("uuid") or ""),
                        str(client.get("id") or ""),
                        str(client.get("email") or ""),
                    }
                ),
                None,
            )
            email = str(match.get("email") or "") if match else ""
            return ("supported", email) if email else ("failed", "")
        except Exception as exc:
            logger.debug("v3 client identity resolution failed for %s: %s", base_url, exc)
            return "failed", ""

    def _reset_client_traffic_v3(self, s, base_url: str, email: str) -> Optional[bool]:
        """POST /panel/api/clients/resetTraffic/{email} — v3."""
        try:
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/clients/resetTraffic/{_path_segment(email)}",
            )
            if res.status_code in (404, 405):
                return None  # v2 fallback only when the v3 route is absent
            if res.status_code != 200:
                return False
            data = res.json()
            return isinstance(data, dict) and data.get("success") is True
        except Exception as exc:
            logger.warning("v3 reset_client_traffic failed: %s", exc)
            return False

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
                # API version is telemetry, not routing authority.  Probe the
                # current v3 operation first for every node; only this route's
                # confirmed absence permits its v2 legacy equivalent.
                v3_state, v3_obj = self._probe_v3(s, base_url)
                if v3_state == "supported":
                    for c in v3_obj:
                        email = c.get("email", "")
                        if needle and needle not in email.lower():
                            continue
                        node_clients.append(self._map_v3_client(c, node))
                    return node_clients
                if v3_state != "unsupported":
                    logger.warning("v3 clients list failed for %s; legacy route was not assumed", node["name"])
                    return node_clients

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
                                "limitIp": client.get("limitIp"),
                                "security": client.get("security", client.get("encryption", "")),
                                "subId": client.get("subId", ""),
                                "reset": client.get("reset", 0),
                                "group": client.get("group", ""),
                                "flow": client.get("flow", ""),
                                "comment": client.get("comment", ""),
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
            result = self._add_client_v3(
                s, base_url,
                email=email,
                inbound_ids=[inbound_id],
                config=client_config,
            )
            if result is not None:
                logger.info("add_client v3 END node=%r email=%r result=%s", node["name"], email, result)
                return result
            # 404/405 can be an expired session on current panels.  Re-auth
            # and retry the *same v3 request* before deciding this operation
            # is legacy-only.  No v2 request is sent after any other outcome.
            retry_state, retry_result, retry_session, retry_base_url = self._retry_v3_after_reauth(
                node,
                lambda fresh, fresh_base: self._add_client_v3(
                    fresh, fresh_base, email=email, inbound_ids=[inbound_id], config=client_config,
                ),
            )
            if retry_state == "response":
                return retry_result
            if retry_state != "confirmed_absent":
                return False
            s, base_url = retry_session, retry_base_url
            logger.debug("add_client: v3 route confirmed absent for node=%r; using v2 legacy", node["name"])

            # v2 fallback
            payload = {
                "id": inbound_id,
                "settings": json.dumps({"clients": [client_config]})
            }
            res = xui_request(s, "POST", f"{base_url}/panel/api/inbounds/addClient", json=payload)

            # A missing legacy route means the node is actually v3.  Do not
            # replay after an operational failure (5xx/timeout/malformed
            # response), because the legacy request may already have reached
            # the panel.
            if res.status_code in (404, 405):
                logger.info("add_client: v2 /addClient %s, retrying documented v3 route for node=%r", res.status_code, node["name"])
                result = self._add_client_v3(s, base_url, email=email, inbound_ids=[inbound_id], config=client_config)
                if result is not None:
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
            # v3 replaces a full client record. It remains primary even when
            # telemetry from an optional feature once said "v2".
            if client_uuid:
                result = self._update_client_v3(s, base_url, str(client_uuid), inbound_id, updates)
                if result is not None:
                    return result
                retry_state, retry_result, retry_session, retry_base_url = self._retry_v3_after_reauth(
                    node,
                    lambda fresh, fresh_base: self._update_client_v3(
                        fresh, fresh_base, str(client_uuid), inbound_id, updates,
                    ),
                )
                if retry_state == "response":
                    return retry_result
                if retry_state != "confirmed_absent":
                    return False
                s, base_url = retry_session, retry_base_url

            # v2 fallback
            payload = {
                "id": inbound_id,
                "settings": json.dumps({"clients": [{"id": client_uuid, **updates}]})
            }
            res = xui_request(s, "POST",
                              f"{base_url}/panel/api/inbounds/updateClient/{_path_segment(client_uuid)}",
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
            # v3 deletes by email; local callers normally carry the UUID.
            if client_uuid:
                result = self._delete_client_v3(s, base_url, str(client_uuid))
                if result is not None:
                    return result
                retry_state, retry_result, retry_session, retry_base_url = self._retry_v3_after_reauth(
                    node,
                    lambda fresh, fresh_base: self._delete_client_v3(fresh, fresh_base, str(client_uuid)),
                )
                if retry_state == "response":
                    return retry_result
                if retry_state != "confirmed_absent":
                    return False
                s, base_url = retry_session, retry_base_url

            # v2 fallback: delete by UUID
            res = xui_request(s, "POST",
                              f"{base_url}/panel/api/inbounds/{_path_segment(inbound_id)}/delClient/{_path_segment(client_uuid)}")
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

                # v3 is always the first capability.  A missing bulk route
                # may degrade only to the documented v3 single-client route;
                # an application/network error must never start legacy writes.
                s, base_url = self._get_session(node)
                if s:
                    bulk_state, bulk_result = self._bulk_delete_v3(s, base_url, emails_to_delete)
                    if bulk_state == "supported":
                        deleted_count = bulk_result.get("deleted", len(emails_to_delete))
                        skipped = [sk.get("email", "") for sk in (bulk_result.get("skipped") or [])]
                        errors = skipped
                        results.append({"node": node["name"], "deleted_count": deleted_count, "errors": errors})
                        continue
                    if bulk_state == "failed":
                        results.append({
                            "node": node["name"],
                            "deleted_count": 0,
                            "errors": ["v3 bulkDel failed; legacy fallback skipped"],
                        })
                        continue
                    # A panel can hide a live v3 route behind a stale/expired
                    # session as 404.  Confirm the absence after a fresh login
                    # before any individual legacy mutation is allowed.
                    def retry_bulk_delete(fresh, fresh_base):
                        retry_state, retry_obj = self._bulk_delete_v3(
                            fresh, fresh_base, emails_to_delete
                        )
                        return None if retry_state == "unsupported" else (retry_state, retry_obj)

                    retry_state, retry_result, _retry_session, _retry_base_url = self._retry_v3_after_reauth(
                        node, retry_bulk_delete
                    )
                    if retry_state == "response":
                        if (
                            isinstance(retry_result, tuple)
                            and retry_result[0] == "supported"
                            and isinstance(retry_result[1], dict)
                        ):
                            retry_obj = retry_result[1]
                            deleted_count = retry_obj.get("deleted", len(emails_to_delete))
                            skipped = [sk.get("email", "") for sk in (retry_obj.get("skipped") or [])]
                            results.append({"node": node["name"], "deleted_count": deleted_count, "errors": skipped})
                            continue
                        results.append({
                            "node": node["name"],
                            "deleted_count": 0,
                            "errors": ["v3 bulkDel retry failed; legacy fallback skipped"],
                        })
                        continue
                    if retry_state != "confirmed_absent":
                        results.append({
                            "node": node["name"],
                            "deleted_count": 0,
                            "errors": ["v3 bulkDel retry failed; legacy fallback skipped"],
                        })
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
            # v3 traffic is email-addressed.  Avoid an extra list request for
            # the common email case; resolve a UUID only when an email is not
            # already available.  An operational v3 failure is terminal and
            # cannot fall through to a different legacy identity.
            identifier = str(client_uuid)
            if "@" in identifier:
                v3_state, result = self._get_traffic_v3(s, base_url, identifier)
            else:
                resolve_state, email = self._resolve_v3_client_email(s, base_url, identifier)
                if resolve_state == "supported":
                    v3_state, result = self._get_traffic_v3(s, base_url, email)
                elif resolve_state == "unsupported":
                    v3_state, result = "unsupported", {}
                else:
                    return {}
            if v3_state == "supported":
                return result if isinstance(result, dict) else {}
            if v3_state != "unsupported":
                return {}

            # v2 fallback: endpoint depends on protocol
            if protocol in ("vless", "vmess"):
                endpoint = f"{base_url}/panel/api/inbounds/getClientTrafficsById/{_path_segment(client_uuid)}"
            else:
                endpoint = f"{base_url}/panel/api/inbounds/getClientTraffics/{_path_segment(client_uuid)}"
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
            result = self._reset_client_traffic_v3(s, base_url, client_email)
            if result is not None:
                return result
            retry_state, retry_result, retry_session, retry_base_url = self._retry_v3_after_reauth(
                node,
                lambda fresh, fresh_base: self._reset_client_traffic_v3(fresh, fresh_base, client_email),
            )
            if retry_state == "response":
                return retry_result
            if retry_state != "confirmed_absent":
                return False
            s, base_url = retry_session, retry_base_url

            payload = {
                "id": inbound_id,
                "email": client_email
            }
            res = xui_request(
                s,
                "POST",
                f"{base_url}/panel/api/inbounds/resetClientTraffic/{_path_segment(client_email)}",
                json=payload,
            )
            return self._xui_success(res)
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
                s, base_url = self._get_session(node)
                if not s:
                    results.append({"node": node["name"], "reset_count": 0, "error": "login failed"})
                    continue
                if inbound_id is not None:
                    endpoint = f"{base_url}/panel/api/inbounds/{_path_segment(inbound_id)}/resetTraffic"
                else:
                    endpoint = f"{base_url}/panel/api/inbounds/resetAllTraffics"
                res = xui_request(s, "POST", endpoint)
                if self._xui_success(res):
                    reset_count = 1
                else:
                    logger.warning("Failed to reset traffic on %s: status=%s", node["name"], res.status_code)
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
                v3_state, emails = self._get_online_v3(s, base_url)
                if v3_state == "supported":
                    return [{"email": e, "node": node["name"]} for e in emails]
                if v3_state != "unsupported":
                    return []

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
                res = xui_request(s, "POST", f"{base_url}/panel/api/clients/delDepleted")
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, dict) and data.get("success") is True:
                        obj = data.get("obj")
                        if obj is None:
                            obj = {}
                        if not isinstance(obj, dict):
                            results.append({"node": node["name"], "deleted": 0, "error": "v3 delDepleted malformed response"})
                            continue
                        results.append({"node": node["name"], "deleted": obj.get("deleted", 0)})
                        continue
                    results.append({"node": node["name"], "deleted": 0, "error": "v3 delDepleted failed"})
                    continue
                if res.status_code not in (404, 405):
                    results.append({"node": node["name"], "deleted": 0, "error": f"v3 delDepleted failed ({res.status_code})"})
                    continue
                def retry_del_depleted(fresh, fresh_base):
                    retry = xui_request(fresh, "POST", f"{fresh_base}/panel/api/clients/delDepleted")
                    return None if retry.status_code in (404, 405) else retry

                retry_state, retry_result, retry_session, retry_base_url = self._retry_v3_after_reauth(
                    node, retry_del_depleted,
                )
                if retry_state == "response":
                    if retry_result is not None and retry_result.status_code == 200:
                        retry_data = retry_result.json()
                        retry_obj = retry_data.get("obj") if isinstance(retry_data, dict) and retry_data.get("success") is True else None
                        if isinstance(retry_obj, dict):
                            results.append({"node": node["name"], "deleted": retry_obj.get("deleted", 0)})
                            continue
                    results.append({"node": node["name"], "deleted": 0, "error": "v3 delDepleted retry failed"})
                    continue
                if retry_state != "confirmed_absent":
                    results.append({"node": node["name"], "deleted": 0, "error": "v3 delDepleted retry failed"})
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
                payload: Dict = {"emails": emails}
                if add_days:
                    payload["addDays"] = add_days
                if add_bytes:
                    payload["addBytes"] = add_bytes
                res = xui_request(s, "POST", f"{base_url}/panel/api/clients/bulkAdjust", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, dict) and data.get("success") is True:
                        obj = data.get("obj")
                        if obj is None:
                            obj = {}
                        if not isinstance(obj, dict):
                            results.append({"node": node["name"], "adjusted": 0, "error": "v3 bulkAdjust malformed response"})
                            continue
                        results.append({"node": node["name"], "adjusted": obj.get("adjusted", 0), "skipped": obj.get("skipped", [])})
                        continue
                    results.append({"node": node["name"], "adjusted": 0, "error": "v3 bulkAdjust failed"})
                    continue
                if res.status_code not in (404, 405):
                    results.append({"node": node["name"], "adjusted": 0, "error": f"v3 bulkAdjust failed ({res.status_code})"})
                    continue
                def retry_bulk_adjust(fresh, fresh_base):
                    retry = xui_request(
                        fresh,
                        "POST",
                        f"{fresh_base}/panel/api/clients/bulkAdjust",
                        json=payload,
                    )
                    return None if retry.status_code in (404, 405) else retry

                retry_state, retry_result, retry_session, retry_base_url = self._retry_v3_after_reauth(
                    node, retry_bulk_adjust,
                )
                if retry_state == "response":
                    if retry_result is not None and retry_result.status_code == 200:
                        retry_data = retry_result.json()
                        retry_obj = retry_data.get("obj") if isinstance(retry_data, dict) and retry_data.get("success") is True else None
                        if isinstance(retry_obj, dict):
                            results.append({"node": node["name"], "adjusted": retry_obj.get("adjusted", 0), "skipped": retry_obj.get("skipped", [])})
                            continue
                    results.append({"node": node["name"], "adjusted": 0, "error": "v3 bulkAdjust retry failed"})
                    continue
                if retry_state != "confirmed_absent":
                    results.append({"node": node["name"], "adjusted": 0, "error": "v3 bulkAdjust retry failed"})
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
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/links/{_path_segment(email)}")
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and data.get("success") is True:
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
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/ips/{_path_segment(email)}")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    obj = data.get("obj") or ""
                    if isinstance(obj, str):
                        return {"ips": [ip.strip() for ip in obj.split("\n") if ip.strip()]}
                    if isinstance(obj, list):
                        ips: List[str] = []
                        details: List[Dict] = []
                        for item in obj:
                            if isinstance(item, str):
                                value = item.strip()
                                if value:
                                    ips.append(value)
                            elif isinstance(item, dict):
                                value = str(item.get("ip") or "").strip()
                                if value:
                                    ips.append(value)
                                    details.append({key: item[key] for key in ("ip", "time", "node") if key in item})
                        result: Dict = {"ips": ips}
                        if details:
                            result["ip_details"] = details
                        return result
        except Exception as exc:
            logger.debug("get_client_ips failed for %s/%s: %s", node["name"], email, exc)
        return {"ips": []}

    def clear_client_ips(self, node: Dict, email: str) -> bool:
        """POST /panel/api/clients/clearIps/{email} — wipe stored IPs."""
        s, base_url = self._get_session(node)
        if not s:
            return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/clearIps/{_path_segment(email)}")
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
            # v3 accepts no filter body; retain our public filtering contract
            # locally rather than transmitting an ignored remote filter.
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/lastOnline")
            if res.status_code == 200:
                data = res.json()
                obj = data.get("obj") if isinstance(data, dict) and data.get("success") is True else None
                if isinstance(obj, dict):
                    if emails is not None:
                        requested = {str(email) for email in emails}
                        obj = {email: value for email, value in obj.items() if email in requested}
                    return {"data": obj}
        except Exception as exc:
            logger.debug("get_last_online failed for %s: %s", node["name"], exc)
        return {"data": {}}

    # ---------------------------------------------------------------------------
    # Bulk traffic reset
    # ---------------------------------------------------------------------------

    def bulk_reset_traffic(self, nodes: List[Dict], emails: List[str]) -> Dict:
        """Reset specific clients via the current 3x-ui bulk-reset contract.

        Only a missing bulk route (404/405) permits the documented v3
        single-client route.  This method has no inbound IDs, so it must never
        guess or call the legacy inbound reset endpoint.
        """
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
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, dict) and data.get("success") is True:
                        successful += len(emails)
                    else:
                        failed += len(emails)
                    continue

                if res.status_code not in (404, 405):
                    failed += len(emails)
                    continue

                # A missing batch route can be adapted only to the documented
                # v3 email-addressed route.  No inbound ID is available for a
                # safe v2 request, so an absent single route remains failed.
                for email in emails:
                    result = self._reset_client_traffic_v3(s, base_url, email)
                    if result is True:
                        successful += 1
                    else:
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
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/{_path_segment(email)}/attach", json={"inboundIds": inbound_ids})
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
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/{_path_segment(email)}/detach", json={"inboundIds": inbound_ids})
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
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/groups/{_path_segment(group_name)}/emails")
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
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/subLinks/{_path_segment(sub_id)}")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("obj") or []
        except Exception as exc:
            logger.debug("get_sub_links failed for %s/%s: %s", node["name"], sub_id, exc)
        return []
