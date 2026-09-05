"""Neutral pre-approval Telegram conversation without transport side effects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from services.subscription_tokens import ensure_tokens, regenerate_token
from services.telegram_traffic import TelegramTrafficService
from services.telegram_registry import (
    IdempotencyConflictError,
    NodePolicyUnavailableError,
    TelegramRegistry,
    TelegramRegistryError,
    VersionConflictError,
)


@dataclass(frozen=True)
class TelegramOutboundMessage:
    chat_id: int
    text: str
    reply_markup: dict[str, Any] | None = None


def _private_actor(update: dict[str, Any]) -> tuple[int, int, dict[str, Any], str | None, str | None] | None:
    """Return trusted transport fields only for a private Telegram chat."""

    message = update.get("message")
    callback = update.get("callback_query")
    payload = message if isinstance(message, dict) else callback if isinstance(callback, dict) else None
    if not isinstance(payload, dict):
        return None
    sender = payload.get("from")
    callback_message = payload.get("message") if isinstance(payload.get("message"), dict) else None
    chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else callback_message.get("chat") if callback_message else None
    if not isinstance(sender, dict) or not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    user_id = sender.get("id")
    chat_id = chat.get("id")
    if isinstance(user_id, bool) or isinstance(chat_id, bool) or not isinstance(user_id, int) or not isinstance(chat_id, int):
        return None
    text = message.get("text") if isinstance(message, dict) and isinstance(message.get("text"), str) else None
    callback_data = callback.get("data") if isinstance(callback, dict) and isinstance(callback.get("data"), str) else None
    return user_id, chat_id, sender, text, callback_data


class TelegramRegistrationService:
    """Handles first contact without exposing technical service details."""

    def __init__(
        self,
        registry: TelegramRegistry,
        *,
        introduction_max_chars: int,
        public_base_url: str = "",
        list_nodes: Callable[[], list[dict[str, Any]]] | None = None,
        get_links_filtered: Callable[[list[dict[str, Any]], str, str | None], list[str]] | None = None,
        primary_admin_id: int | None = None,
        get_cached_inbound_options: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
        traffic_projection_loader: Callable[[], dict[str, Any]] | None = None,
    ):
        self._registry = registry
        self._introduction_max_chars = introduction_max_chars
        self._public_base_url = public_base_url.rstrip("/")
        self._list_nodes = list_nodes
        self._get_links_filtered = get_links_filtered
        self._primary_admin_id = primary_admin_id
        self._get_cached_inbound_options = get_cached_inbound_options
        self._traffic = TelegramTrafficService(registry, traffic_projection_loader)

    @staticmethod
    def _format_bytes(value: int) -> str:
        units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
        amount = float(max(0, value))
        unit = 0
        while amount >= 1024 and unit < len(units) - 1:
            amount /= 1024
            unit += 1
        return f"{amount:.1f} {units[unit]}" if unit else f"{int(amount)} {units[unit]}"

    @staticmethod
    def _inbound_one_supports_bot_contract(node_id: int, inbound_options: list[dict[str, Any]]) -> bool:
        return any(
            isinstance(inbound, dict)
            and inbound.get("node_id") == node_id
            and inbound.get("id") == 1
            and bool(inbound.get("enable"))
            and str(inbound.get("protocol") or "").lower() == "vless"
            and bool(inbound.get("tlsFlowCapable"))
            for inbound in inbound_options
        )

    @staticmethod
    def _admin_home_menu() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": "Заявки", "callback_data": "admin:requests:0"}],
                [{"text": "TG-ноды", "callback_data": "admin:nodes:0"}],
            ]
        }

    def _admin_nodes_message(self, chat_id: int, page: int) -> TelegramOutboundMessage:
        if not self._list_nodes:
            return TelegramOutboundMessage(chat_id, "Список нод пока недоступен.", self._admin_home_menu())
        try:
            nodes = self._list_nodes()
        except Exception:
            return TelegramOutboundMessage(chat_id, "Список нод пока недоступен.", self._admin_home_menu())
        eligible = [
            node for node in nodes
            if isinstance(node, dict)
            and isinstance(node.get("id"), int)
            and bool(node.get("enabled", True))
            and not bool(node.get("read_only", False))
        ]
        eligible.sort(key=lambda node: (str(node.get("name") or "").casefold(), int(node["id"])))
        page_size = 6
        total_pages = max(1, (len(eligible) + page_size - 1) // page_size)
        current_page = min(max(page, 0), total_pages - 1)
        policies = {policy.node_id: policy for policy in self._registry.list_node_provisioning_policies()}
        buttons: list[list[dict[str, str]]] = []
        for node in eligible[current_page * page_size:(current_page + 1) * page_size]:
            policy = policies.get(int(node["id"]))
            active = bool(policy and policy.provisioning_enabled)
            name = str(node.get("name") or f"node-{node['id']}").replace("\n", " ")[:35]
            buttons.append([{
                "text": f"{'✓' if active else '○'} TG · {name}",
                "callback_data": f"admin:node:{int(node['id'])}:{current_page}",
            }])
        navigation: list[dict[str, str]] = []
        if current_page > 0:
            navigation.append({"text": "‹", "callback_data": f"admin:nodes:{current_page - 1}"})
        navigation.append({"text": f"{current_page + 1}/{total_pages}", "callback_data": "admin:home"})
        if current_page + 1 < total_pages:
            navigation.append({"text": "›", "callback_data": f"admin:nodes:{current_page + 1}"})
        buttons.append(navigation)
        buttons.append([{"text": "← Меню", "callback_data": "admin:home"}])
        return TelegramOutboundMessage(chat_id, "TG-ноды. Нажмите, чтобы включить или выключить добавление новых пользователей.", {"inline_keyboard": buttons})

    def _admin_requests_message(self, chat_id: int, page: int) -> TelegramOutboundMessage:
        requests = self._registry.list_pending_applications()
        page_size = 5
        total_pages = max(1, (len(requests) + page_size - 1) // page_size)
        current_page = min(max(page, 0), total_pages - 1)
        visible = requests[current_page * page_size:(current_page + 1) * page_size]
        if not visible:
            return TelegramOutboundMessage(chat_id, "Заявок на рассмотрении нет.", self._admin_home_menu())
        buttons: list[list[dict[str, str]]] = []
        lines = ["Заявки. Подтверждение использует предложенное имя; изменить его можно в панели."]
        for item in visible:
            title = f"@{item.username}" if item.username else (item.first_name or f"#{item.telegram_user_id}")
            lines.append(f"• {title} → {item.suggested_email}")
            buttons.append([{
                "text": f"✓ {title[:28]}",
                "callback_data": f"admin:approve:{item.telegram_user_id}:{item.row_version}:{current_page}",
            }])
        navigation: list[dict[str, str]] = []
        if current_page > 0:
            navigation.append({"text": "‹", "callback_data": f"admin:requests:{current_page - 1}"})
        navigation.append({"text": f"{current_page + 1}/{total_pages}", "callback_data": "admin:home"})
        if current_page + 1 < total_pages:
            navigation.append({"text": "›", "callback_data": f"admin:requests:{current_page + 1}"})
        buttons.append(navigation)
        buttons.append([{"text": "← Меню", "callback_data": "admin:home"}])
        return TelegramOutboundMessage(chat_id, "\n".join(lines), {"inline_keyboard": buttons})

    def _handle_admin(
        self, *, user_id: int, chat_id: int, update_id: int, text: str | None, callback_data: str | None
    ) -> list[TelegramOutboundMessage] | None:
        if user_id != self._primary_admin_id:
            return None
        if text and text.strip().startswith("/admin"):
            return [TelegramOutboundMessage(chat_id, "Управление доступом.", self._admin_home_menu())]
        if callback_data == "admin:home":
            return [TelegramOutboundMessage(chat_id, "Управление доступом.", self._admin_home_menu())]
        parts = callback_data.split(":") if callback_data else []
        try:
            if len(parts) == 3 and parts[:2] == ["admin", "nodes"]:
                return [self._admin_nodes_message(chat_id, int(parts[2]))]
            if len(parts) == 3 and parts[:2] == ["admin", "requests"]:
                return [self._admin_requests_message(chat_id, int(parts[2]))]
            if len(parts) == 4 and parts[:2] == ["admin", "node"]:
                node_id, page = int(parts[2]), int(parts[3])
                policies = {policy.node_id: policy for policy in self._registry.list_node_provisioning_policies()}
                current = policies.get(node_id)
                enabled = not bool(current and current.provisioning_enabled)
                compatible = False
                if enabled:
                    if not self._list_nodes or not self._get_cached_inbound_options:
                        raise TelegramRegistryError("Нельзя проверить совместимость inbound 1")
                    compatible = self._inbound_one_supports_bot_contract(
                        node_id, self._get_cached_inbound_options(self._list_nodes())
                    )
                policy = self._registry.set_node_provisioning_policy(
                    node_id=node_id,
                    provisioning_enabled=enabled,
                    total_bytes=current.total_bytes if current else 0,
                    validity_days=current.validity_days if current else 0,
                    client_enabled=current.client_enabled if current else True,
                    expected_policy_version=current.policy_version if current else 0,
                    idempotency_key=f"telegram-admin-node:{update_id}:{node_id}",
                    updated_by=f"telegram:{user_id}",
                    node_is_compatible=compatible,
                )
                state = "включена" if policy.provisioning_enabled else "выключена"
                return [TelegramOutboundMessage(chat_id, f"TG-политика ноды {state}.", self._admin_nodes_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "approve"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                result = self._registry.approve_new_application(
                    telegram_user_id=target_user_id,
                    expected_identity_version=version,
                    email_display=None,
                    idempotency_key=f"telegram-admin-approve:{update_id}:{target_user_id}",
                    approved_by=f"telegram:{user_id}",
                )
                return [TelegramOutboundMessage(
                    chat_id,
                    f"Заявка одобрена: {result.email_display}. Подготовка на {len(result.target_node_ids)} нодах поставлена в очередь.",
                    self._admin_requests_message(chat_id, page).reply_markup,
                )]
        except (ValueError, NodePolicyUnavailableError, VersionConflictError, IdempotencyConflictError, TelegramRegistryError):
            return [TelegramOutboundMessage(chat_id, "Команда не выполнена: данные устарели или нода не готова.", self._admin_home_menu())]
        return [TelegramOutboundMessage(chat_id, "Команда администратора не распознана.", self._admin_home_menu())]

    @staticmethod
    def _approved_menu(*, suspended: bool = False) -> dict[str, Any]:
        rows = [[{"text": "◎ Получить доступ", "callback_data": "subscription:get"}]]
        if suspended:
            rows.append([{"text": "✉ Написать администратору", "callback_data": "support:appeal"}])
        else:
            rows.extend([
                [{"text": "↻ Сменить ссылку", "callback_data": "subscription:rotate"}],
                [{"text": "? Помощь", "callback_data": "help"}],
            ])
        return {"inline_keyboard": rows}

    def _subscription_message(self, *, user_id: int, chat_id: int, rotate: bool = False) -> TelegramOutboundMessage:
        access = self._registry.get_customer_access(user_id)
        if access.access_status != "approved" or access.customer_id is None or not access.email_display:
            return TelegramOutboundMessage(chat_id, "Сейчас доступ ещё не готов.", self._approved_menu())
        if access.customer_status in {"suspended", "suspend_partial", "resuming", "resume_partial", "deleting", "delete_partial"}:
            return TelegramOutboundMessage(
                chat_id,
                "Доступ временно приостановлен. Если это ошибка, напишите администратору.",
                self._approved_menu(suspended=True),
            )
        if access.customer_status != "active" or not self._list_nodes or not self._get_links_filtered:
            return TelegramOutboundMessage(chat_id, "Доступ готовится. Пожалуйста, проверьте статус позже.", self._approved_menu())
        try:
            links = self._get_links_filtered(self._list_nodes(), access.email_display, None)
        except Exception:
            links = []
        if not links:
            return TelegramOutboundMessage(chat_id, "Доступ готовится. Пожалуйста, проверьте статус позже.", self._approved_menu())
        try:
            token = regenerate_token(self._registry.database_path, "email", access.email_display) if rotate else None
            if not token:
                token = ensure_tokens(self._registry.database_path, "email", [access.email_display]).get(access.email_display)
        except Exception:
            token = None
        if not token or not self._public_base_url:
            return TelegramOutboundMessage(chat_id, "Ссылку пока нельзя выдать. Пожалуйста, попробуйте позже.", self._approved_menu())
        return TelegramOutboundMessage(
            chat_id,
            f"Ваша ссылка доступа:\n{self._public_base_url}/api/v1/sub/{token}",
            self._approved_menu(),
        )

    def _approved_status(self, user_id: int, chat_id: int) -> TelegramOutboundMessage:
        access = self._registry.get_customer_access(user_id)
        if access.access_status != "approved" or not access.customer_status:
            return TelegramOutboundMessage(chat_id, "Заявка ещё ожидает решения администратора.")
        lifetime = None
        if access.customer_id is not None and access.email_display:
            lifetime = self._traffic.refresh_for_access(customer_id=access.customer_id, email=access.email_display)
        traffic_line = f"\nТрафик за всё время: {self._format_bytes(lifetime.lifetime_bytes)}." if lifetime else ""
        return TelegramOutboundMessage(
            chat_id,
            f"Статус доступа: {access.customer_status}.{traffic_line}",
            self._approved_menu(suspended=access.customer_status in {"suspended", "suspend_partial"}),
        )

    def handle_update(self, update: dict[str, Any]) -> list[TelegramOutboundMessage]:
        update_id = update.get("update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id <= 0:
            return []
        actor = _private_actor(update)
        if actor is None:
            return []
        user_id, chat_id, sender, text, callback_data = actor
        update_type = "callback_query" if callback_data is not None else "message"
        digest_source = {
            "update_id": update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "text": text,
            "callback": callback_data,
        }
        digest = hashlib.sha256(
            json.dumps(digest_source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        # The durable update row has an FK to identity. Upsert the immutable
        # numeric identity first; a duplicate update can only refresh display
        # metadata and still cannot create a second application.
        identity = self._registry.get_or_create_identity(
            telegram_user_id=user_id,
            chat_id=chat_id,
            username=sender.get("username") if isinstance(sender.get("username"), str) else None,
            first_name=sender.get("first_name") if isinstance(sender.get("first_name"), str) else None,
            last_name=sender.get("last_name") if isinstance(sender.get("last_name"), str) else None,
            locale="ru",
        )
        if not self._registry.claim_update(
            update_id=update_id,
            telegram_user_id=user_id,
            update_type=update_type,
            payload_digest=digest,
        ):
            return []
        admin_response = self._handle_admin(
            user_id=user_id,
            chat_id=chat_id,
            update_id=update_id,
            text=text,
            callback_data=callback_data,
        )
        if admin_response is not None:
            return admin_response
        if identity.access_status == "blocked":
            return [TelegramOutboundMessage(chat_id, "Сейчас это действие недоступно.")]

        def no_op(message: TelegramOutboundMessage) -> list[TelegramOutboundMessage]:
            outcome = self._registry.record_unapproved_noop(user_id)
            if outcome.auto_blocked:
                return [TelegramOutboundMessage(chat_id, "Сейчас это действие недоступно.")]
            if outcome.suppress_response:
                return []
            return [message]

        if text and text.strip().startswith("/start"):
            pending = self._registry.create_pending_application(user_id)
            if pending.created:
                return [
                    TelegramOutboundMessage(
                        chat_id,
                        "Здравствуйте. Ваша заявка принята и ожидает проверки. Пожалуйста, дождитесь ответа.",
                        {"inline_keyboard": [[{"text": "◎ Представиться", "callback_data": "registration:intro"}]]},
                    )
                ]
            if pending.identity.access_status == "approved":
                return [self._approved_status(user_id, chat_id)]
            return no_op(TelegramOutboundMessage(chat_id, "Заявка уже ожидает проверки. Пожалуйста, дождитесь ответа."))

        if callback_data == "registration:intro":
            if identity.access_status != "pending":
                return no_op(TelegramOutboundMessage(chat_id, "Сейчас представление не требуется."))
            return [
                TelegramOutboundMessage(
                    chat_id,
                    "Если хотите, коротко расскажите о себе и причине обращения одним сообщением. Это необязательно.",
                )
            ]

        if identity.access_status == "approved":
            access = self._registry.get_customer_access(user_id)
            if callback_data in {"subscription:get", "subscription:rotate:confirm"}:
                return [self._subscription_message(user_id=user_id, chat_id=chat_id, rotate=callback_data.endswith(":confirm"))]
            if callback_data == "subscription:rotate":
                return [TelegramOutboundMessage(
                    chat_id,
                    "Старая ссылка сразу перестанет работать. Подтвердить смену?",
                    {"inline_keyboard": [[{"text": "✓ Подтвердить смену", "callback_data": "subscription:rotate:confirm"}], [{"text": "Отмена", "callback_data": "help"}]]},
                )]
            if callback_data == "support:appeal":
                return [TelegramOutboundMessage(chat_id, "Напишите одним сообщением, почему доступ нужно восстановить. Это попадёт администратору на рассмотрение.")]
            if callback_data == "help":
                return [TelegramOutboundMessage(chat_id, "Используйте меню ниже для получения ссылки и проверки статуса.", self._approved_menu())]
            if text and text.strip().startswith("/status"):
                return [self._approved_status(user_id, chat_id)]
            if text and text.strip().startswith("/subscription"):
                return [self._subscription_message(user_id=user_id, chat_id=chat_id)]
            if text and access.customer_id is not None and access.customer_status in {"suspended", "suspend_partial"}:
                try:
                    self._registry.submit_suspended_appeal(telegram_user_id=user_id, body=text)
                except TelegramRegistryError:
                    return [TelegramOutboundMessage(chat_id, "Не удалось принять сообщение. Попробуйте короче.")]
                return [TelegramOutboundMessage(chat_id, "Сообщение принято и передано администратору.", self._approved_menu(suspended=True))]
            return no_op(self._approved_status(user_id, chat_id))

        if text and identity.access_status == "pending":
            try:
                saved = self._registry.submit_introduction(
                    user_id, text, maximum_chars=self._introduction_max_chars
                )
            except TelegramRegistryError:
                return [TelegramOutboundMessage(chat_id, "Сообщение не удалось принять. Попробуйте короче.")]
            if saved:
                return [TelegramOutboundMessage(chat_id, "Спасибо. Заявка по-прежнему ожидает проверки.")]
            return no_op(TelegramOutboundMessage(chat_id, "Заявка уже ожидает проверки. Пожалуйста, дождитесь ответа."))

        return no_op(TelegramOutboundMessage(chat_id, "Для начала отправьте /start."))
