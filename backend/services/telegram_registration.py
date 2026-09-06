"""Neutral pre-approval Telegram conversation without transport side effects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from services.subscription_tokens import ensure_tokens, regenerate_token
from services.telegram_access import resolve_effective_access
from services.telegram_qr import TelegramQrError, build_subscription_qr_png
from services.telegram_traffic import TelegramTrafficService
from services.telegram_registry import (
    DiscoveredExistingBinding,
    IdempotencyConflictError,
    LifecycleUnavailableError,
    NodePolicyUnavailableError,
    TelegramRegistry,
    TelegramRegistryError,
    VersionConflictError,
)
from services.telegram_provisioning import ExistingRemoteBinding


@dataclass(frozen=True)
class TelegramOutboundMessage:
    chat_id: int
    text: str
    reply_markup: dict[str, Any] | None = None
    photo_png: bytes | None = None
    photo_filename: str | None = None


def _private_actor(
    update: dict[str, Any],
) -> tuple[int, int, dict[str, Any], str | None, str | None, str | None] | None:
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
    contact = message.get("contact") if isinstance(message, dict) and isinstance(message.get("contact"), dict) else None
    phone_number = (
        contact.get("phone_number")
        if contact and contact.get("user_id") == user_id and isinstance(contact.get("phone_number"), str)
        else None
    )
    return user_id, chat_id, sender, text, callback_data, phone_number


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
        discover_existing: Callable[[str], tuple[ExistingRemoteBinding, ...]] | None = None,
    ):
        self._registry = registry
        self._introduction_max_chars = introduction_max_chars
        self._public_base_url = public_base_url.rstrip("/")
        self._list_nodes = list_nodes
        self._get_links_filtered = get_links_filtered
        self._primary_admin_id = primary_admin_id
        self._get_cached_inbound_options = get_cached_inbound_options
        self._traffic = TelegramTrafficService(registry, traffic_projection_loader)
        self._discover_existing = discover_existing

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
                [{"text": "Пользователи", "callback_data": "admin:customers:0"}],
                [{"text": "TG-ноды", "callback_data": "admin:nodes:0"}],
                [{"text": "Рассылки", "callback_data": "admin:broadcasts"}],
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
            return TelegramOutboundMessage(
                chat_id,
                "Заявок на рассмотрении нет.",
                {"inline_keyboard": [
                    [{"text": "⊘ Заблокированные", "callback_data": "admin:blocked:0"}],
                    [{"text": "← Меню", "callback_data": "admin:home"}],
                ]},
            )
        buttons: list[list[dict[str, str]]] = []
        lines = ["Заявки. Откройте карточку, чтобы проверить данные и принять решение."]
        for item in visible:
            title = f"@{item.username}" if item.username else (item.first_name or f"#{item.telegram_user_id}")
            lines.append(f"• {title} → {item.suggested_email}")
            buttons.append([{
                "text": f"◎ {title[:28]}",
                "callback_data": f"admin:request:{item.telegram_user_id}:{item.row_version}:{current_page}",
            }])
        navigation: list[dict[str, str]] = []
        if current_page > 0:
            navigation.append({"text": "‹", "callback_data": f"admin:requests:{current_page - 1}"})
        navigation.append({"text": f"{current_page + 1}/{total_pages}", "callback_data": "admin:home"})
        if current_page + 1 < total_pages:
            navigation.append({"text": "›", "callback_data": f"admin:requests:{current_page + 1}"})
        buttons.append(navigation)
        buttons.append([{"text": "⊘ Заблокированные", "callback_data": "admin:blocked:0"}])
        buttons.append([{"text": "← Меню", "callback_data": "admin:home"}])
        return TelegramOutboundMessage(chat_id, "\n".join(lines), {"inline_keyboard": buttons})

    def _admin_request_message(self, chat_id: int, telegram_user_id: int, page: int) -> TelegramOutboundMessage:
        item = self._registry.get_pending_application(telegram_user_id)
        title = f"@{item.username}" if item.username else (item.first_name or f"#{item.telegram_user_id}")
        name = " ".join(part for part in (item.first_name, item.last_name) if part) or "—"
        introduction = item.introduction_text or "не отправлено"
        lines = [
            "Заявка",
            f"Telegram: {title}",
            f"Имя: {name}",
            f"ID: {item.telegram_user_id}",
            f"Предложенное имя/email: {item.suggested_email}",
            "Представление:",
            introduction,
        ]
        return TelegramOutboundMessage(
            chat_id,
            "\n".join(lines),
            {"inline_keyboard": [
                [{"text": "Создать нового", "callback_data": f"admin:new:{item.telegram_user_id}:{item.row_version}:{page}"}],
                [{"text": "Привязать существующего", "callback_data": f"admin:existing:{item.telegram_user_id}:{item.row_version}:{page}"}],
                [{"text": "Отклонить", "callback_data": f"admin:reject:{item.telegram_user_id}:{item.row_version}:{page}"}],
                [{"text": "Заблокировать", "callback_data": f"admin:block:{item.telegram_user_id}:{item.row_version}:{page}"}],
                [{"text": "← К заявкам", "callback_data": f"admin:requests:{page}"}],
            ]},
        )

    def _admin_new_customer_preview(
        self, chat_id: int, *, telegram_user_id: int, row_version: int, page: int, email_display: str
    ) -> TelegramOutboundMessage:
        node_count = self._registry.eligible_provisioning_node_count()
        return TelegramOutboundMessage(
            chat_id,
            "Проверка нового пользователя\n\n"
            f"Имя/email для нод: {email_display}\n"
            f"Нод для подготовки: {node_count}\n"
            "Параметры: inbound 1, xtls-rprx-vision, без лимита и срока, включён.\n\n"
            "Клиент и задания будут созданы только после отдельного подтверждения.",
            {"inline_keyboard": [
                [{"text": "✓ Одобрить и создать", "callback_data": f"admin:new-confirm:{telegram_user_id}:{row_version}:{page}"}],
                [{"text": "✎ Ввести другое имя", "callback_data": f"admin:new-input:{telegram_user_id}:{row_version}:{page}"}],
                [{"text": "← К заявке", "callback_data": f"admin:request:{telegram_user_id}:{row_version}:{page}"}],
            ]},
        )

    def _admin_new_name_choice(
        self, chat_id: int, *, telegram_user_id: int, row_version: int, page: int, suggested_email: str
    ) -> TelegramOutboundMessage:
        return TelegramOutboundMessage(
            chat_id,
            "Новое имя/email для пользователя\n\n"
            f"Предложено: {suggested_email}\n\n"
            "Можно принять предложение или отправить другое имя одним сообщением.",
            {"inline_keyboard": [
                [{"text": f"✓ Использовать {suggested_email[:28]}", "callback_data": f"admin:new-use:{telegram_user_id}:{row_version}:{page}"}],
                [{"text": "✎ Ввести другое имя", "callback_data": f"admin:new-input:{telegram_user_id}:{row_version}:{page}"}],
                [{"text": "← К заявке", "callback_data": f"admin:request:{telegram_user_id}:{row_version}:{page}"}],
            ]},
        )

    def _admin_customers_message(self, chat_id: int, page: int) -> TelegramOutboundMessage:
        page_size = 6
        customer_page = self._registry.list_customers(page=max(page, 0) + 1, page_size=page_size)
        total_pages = max(1, (customer_page.total + page_size - 1) // page_size)
        current_page = min(max(page, 0), total_pages - 1)
        if current_page != page:
            customer_page = self._registry.list_customers(page=current_page + 1, page_size=page_size)
        if not customer_page.items:
            return TelegramOutboundMessage(chat_id, "Пользователей пока нет.", self._admin_home_menu())
        buttons: list[list[dict[str, str]]] = []
        lines = [f"Пользователи: {customer_page.total}."]
        for item in customer_page.items:
            lines.append(f"• {item.email_display} · {item.status}")
            buttons.append([{
                "text": f"◎ {item.email_display[:30]}",
                "callback_data": f"admin:customer:{item.customer_id}:{current_page}",
            }])
        navigation: list[dict[str, str]] = []
        if current_page > 0:
            navigation.append({"text": "‹", "callback_data": f"admin:customers:{current_page - 1}"})
        navigation.append({"text": f"{current_page + 1}/{total_pages}", "callback_data": "admin:home"})
        if current_page + 1 < total_pages:
            navigation.append({"text": "›", "callback_data": f"admin:customers:{current_page + 1}"})
        buttons.append(navigation)
        buttons.append([{"text": "← Меню", "callback_data": "admin:home"}])
        return TelegramOutboundMessage(chat_id, "\n".join(lines), {"inline_keyboard": buttons})

    def _admin_customer_message(self, chat_id: int, customer_id: int, page: int) -> TelegramOutboundMessage:
        customer = self._registry.get_customer(customer_id)
        profile = self._registry.get_customer_telegram_profile(customer.customer_id)
        traffic = self._registry.get_customer_traffic(customer.customer_id)
        matrix = self._registry.customer_node_matrix(customer.customer_id)
        full_name = " ".join(part for part in (profile.first_name, profile.last_name) if part) or "не указано"
        lines = [
            f"Пользователь: {customer.email_display}",
            f"Статус: {customer.status}",
            f"Никнейм: @{profile.username}" if profile.username else "Никнейм: не указан",
            f"Telegram: {profile.telegram_user_id}" if profile.telegram_user_id else "Telegram: не привязан",
            f"Имя и фамилия: {full_name}",
            f"Телефон: {profile.phone_number}" if profile.phone_number else "Телефон: не указан",
            f"Трафик за всё время: {self._format_bytes(traffic.lifetime_bytes)}",
            "Ноды:",
        ]
        buttons: list[list[dict[str, str]]] = []
        for item in matrix:
            label = item.node_name.replace("\n", " ")[:30]
            state_label = {
                "active": "✓",
                "suspended": "○",
                "available_to_add": "+",
                "problem": "!",
            }.get(item.state, "?")
            lines.append(f"{state_label} {label}")
            action = {"active": "suspend", "suspended": "resume", "available_to_add": "add"}.get(item.state)
            if action:
                buttons.append([{
                    "text": f"{state_label} {label}",
                    "callback_data": f"admin:cn:{customer.customer_id}:{item.node_id}:{action}:{page}",
                }])
        if not matrix:
            lines.append("— пока нет назначенных или доступных TG-нод")
        if customer.status == "active":
            buttons.append([{
                "text": "⏸ Приостановить пользователя",
                "callback_data": f"admin:customer-op:{customer.customer_id}:{customer.row_version}:suspend:{page}",
            }])
        elif customer.status == "suspended":
            buttons.append([{
                "text": "▶ Возобновить пользователя",
                "callback_data": f"admin:customer-op:{customer.customer_id}:{customer.row_version}:resume:{page}",
            }])
        if customer.status not in {"deleted", "deleting", "delete_partial"}:
            buttons.append([{
                "text": "Удалить пользователя…",
                "callback_data": f"admin:customer-delete:{customer.customer_id}:{customer.row_version}:{page}",
            }])
        if profile.telegram_user_id is not None:
            buttons.append([{
                "text": "✉ Написать в бот",
                "callback_data": f"admin:message:{customer.customer_id}:{page}",
            }])
        buttons.append([{"text": "← К пользователям", "callback_data": f"admin:customers:{page}"}])
        return TelegramOutboundMessage(chat_id, "\n".join(lines), {"inline_keyboard": buttons})

    def _admin_broadcasts_message(self, chat_id: int) -> TelegramOutboundMessage:
        recipients = self._registry.registered_broadcast_recipient_count()
        return TelegramOutboundMessage(
            chat_id,
            "Рассылки\n\n"
            f"Получатели сейчас: {recipients}.\n"
            "Войдут только подтверждённые зарегистрированные пользователи с включёнными фоновыми уведомлениями. "
            "Заявки, заблокированные и удалённые пользователи исключены.",
            {"inline_keyboard": [
                [{"text": "✉ Новое объявление", "callback_data": "admin:broadcast:new"}],
                [{"text": "← Меню", "callback_data": "admin:home"}],
            ]},
        )

    def _admin_blocked_message(self, chat_id: int, page: int) -> TelegramOutboundMessage:
        page_size = 6
        blocked = self._registry.list_blocked_identities(limit=200)
        total_pages = max(1, (len(blocked) + page_size - 1) // page_size)
        current_page = min(max(page, 0), total_pages - 1)
        visible = blocked[current_page * page_size:(current_page + 1) * page_size]
        if not visible:
            return TelegramOutboundMessage(
                chat_id, "Заблокированных заявок нет.",
                {"inline_keyboard": [[{"text": "← К заявкам", "callback_data": "admin:requests:0"}]]},
            )
        lines = ["Заблокированные заявки."]
        buttons: list[list[dict[str, str]]] = []
        for item in visible:
            label = f"@{item.username}" if item.username else (item.first_name or f"#{item.telegram_user_id}")
            lines.append(f"• {label}")
            buttons.append([{
                "text": f"Разблокировать {label[:22]}",
                "callback_data": f"admin:unblock:{item.telegram_user_id}:{item.row_version}:{current_page}",
            }])
        navigation: list[dict[str, str]] = []
        if current_page > 0:
            navigation.append({"text": "‹", "callback_data": f"admin:blocked:{current_page - 1}"})
        navigation.append({"text": f"{current_page + 1}/{total_pages}", "callback_data": "admin:requests:0"})
        if current_page + 1 < total_pages:
            navigation.append({"text": "›", "callback_data": f"admin:blocked:{current_page + 1}"})
        buttons.append(navigation)
        buttons.append([{"text": "← К заявкам", "callback_data": "admin:requests:0"}])
        return TelegramOutboundMessage(chat_id, "\n".join(lines), {"inline_keyboard": buttons})

    def _handle_admin_draft(
        self, *, user_id: int, chat_id: int, text: str | None
    ) -> list[TelegramOutboundMessage] | None:
        if not text or text.strip().startswith("/"):
            return None
        draft = self._registry.get_admin_draft(user_id)
        if draft is None:
            return None
        try:
            if draft.action == "new_customer_name" and draft.telegram_user_id and draft.expected_row_version:
                selected = self._registry.normalize_new_customer_email(text)
                self._registry.set_admin_draft(
                    admin_telegram_user_id=user_id, action=draft.action,
                    telegram_user_id=draft.telegram_user_id, expected_row_version=draft.expected_row_version,
                    page=draft.page, value=selected,
                )
                return [self._admin_new_customer_preview(
                    chat_id, telegram_user_id=draft.telegram_user_id,
                    row_version=draft.expected_row_version, page=draft.page, email_display=selected,
                )]
            if draft.action == "existing_customer_email" and draft.telegram_user_id and draft.expected_row_version:
                try:
                    customer = self._registry.get_customer_by_email(text)
                except TelegramRegistryError:
                    if self._discover_existing is None:
                        raise
                    remote_bindings = self._discover_existing(text)
                    if not remote_bindings:
                        raise TelegramRegistryError("existing service username was not found")
                    email_display = remote_bindings[0].remote_email
                    self._registry.set_admin_draft(
                        admin_telegram_user_id=user_id, action=draft.action,
                        telegram_user_id=draft.telegram_user_id, expected_row_version=draft.expected_row_version,
                        page=draft.page, value=email_display,
                    )
                    return [TelegramOutboundMessage(
                        chat_id,
                        f"Найден существующий пользователь: {email_display} на нодах: {len(remote_bindings)}. Привязать заявку без создания новых записей?",
                        {"inline_keyboard": [
                            [{"text": "✓ Привязать", "callback_data": f"admin:existing-discovered-confirm:{draft.telegram_user_id}:{draft.expected_row_version}:{draft.page}"}],
                            [{"text": "← К заявке", "callback_data": f"admin:request:{draft.telegram_user_id}:{draft.expected_row_version}:{draft.page}"}],
                        ]},
                    )]
                self._registry.set_admin_draft(
                    admin_telegram_user_id=user_id, action=draft.action,
                    telegram_user_id=draft.telegram_user_id, expected_row_version=draft.expected_row_version,
                    page=draft.page, value=customer.email_display,
                )
                return [TelegramOutboundMessage(
                    chat_id,
                    f"Найден пользователь: {customer.email_display}. Привязать эту заявку?",
                    {"inline_keyboard": [
                        [{"text": "✓ Привязать", "callback_data": f"admin:existing-confirm:{draft.telegram_user_id}:{draft.expected_row_version}:{customer.customer_id}:{draft.page}"}],
                        [{"text": "← К заявке", "callback_data": f"admin:request:{draft.telegram_user_id}:{draft.expected_row_version}:{draft.page}"}],
                    ]},
                )]
            if draft.action == "delete_customer_confirmation" and draft.customer_id and draft.expected_row_version:
                customer = self._registry.get_customer(draft.customer_id)
                if customer.row_version != draft.expected_row_version or text.strip() != customer.email_display:
                    return [TelegramOutboundMessage(
                        chat_id, "Значение не совпало. Введите точный service username/email ещё раз.",
                    )]
                preview = self._registry.preview_customer_operation(customer_id=customer.customer_id, operation_type="delete")
                if preview.expected_customer_version != draft.expected_row_version:
                    raise VersionConflictError("customer is stale")
                self._registry.set_admin_draft(
                    admin_telegram_user_id=user_id, action=draft.action, customer_id=customer.customer_id,
                    expected_row_version=draft.expected_row_version, page=draft.page, value=customer.email_display,
                )
                return [TelegramOutboundMessage(
                    chat_id,
                    f"Удаление {customer.email_display}\nБудет затронуто нод: {len(preview.targets)}.\n\nПодтвердить постановку в очередь?",
                    {"inline_keyboard": [
                        [{"text": "✓ Подтвердить удаление", "callback_data": f"admin:customer-delete-confirm:{customer.customer_id}:{draft.expected_row_version}:{draft.page}"}],
                        [{"text": "Отмена", "callback_data": f"admin:customer:{customer.customer_id}:{draft.page}"}],
                    ]},
                )]
        except TelegramRegistryError:
            return [TelegramOutboundMessage(chat_id, "Не удалось принять значение. Проверьте его и попробуйте ещё раз.")]
        return None

    def _handle_admin_message_draft(
        self, *, user_id: int, chat_id: int, text: str | None
    ) -> list[TelegramOutboundMessage] | None:
        if not text or text.strip().startswith("/"):
            return None
        draft = self._registry.get_admin_message_draft(user_id)
        if draft is None:
            return None
        try:
            saved = self._registry.set_admin_message_draft(
                admin_telegram_user_id=user_id,
                mode=draft.mode,
                customer_id=draft.customer_id,
                page=draft.page,
                body=text,
            )
        except TelegramRegistryError:
            return [TelegramOutboundMessage(chat_id, "Текст не принят. Допустимо от 1 до 2000 символов.")]
        assert saved.body is not None
        if saved.mode == "direct" and saved.customer_id is not None:
            customer = self._registry.get_customer(saved.customer_id)
            return [TelegramOutboundMessage(
                chat_id,
                f"Отправить сообщение пользователю {customer.email_display}?\n\n{saved.body}",
                {"inline_keyboard": [
                    [{"text": "✓ Отправить", "callback_data": "admin:message-confirm"}],
                    [{"text": "Отмена", "callback_data": f"admin:message-cancel:{saved.customer_id}:{saved.page}"}],
                ]},
            )]
        recipients = self._registry.registered_broadcast_recipient_count()
        return [TelegramOutboundMessage(
            chat_id,
            f"Разослать объявление зарегистрированным пользователям?\n"
            f"Получателей: {recipients}.\n\n{saved.body}",
            {"inline_keyboard": [
                [{"text": "✓ Запустить рассылку", "callback_data": "admin:broadcast-confirm"}],
                [{"text": "Отмена", "callback_data": "admin:broadcasts"}],
            ]},
        )]

    def _handle_admin(
        self, *, user_id: int, chat_id: int, update_id: int, text: str | None, callback_data: str | None
    ) -> list[TelegramOutboundMessage] | None:
        if user_id != self._primary_admin_id:
            return None
        if text and text.strip().startswith("/admin"):
            self._registry.clear_admin_draft(user_id)
            self._registry.clear_admin_message_draft(user_id)
            return [TelegramOutboundMessage(chat_id, "Управление доступом.", self._admin_home_menu())]
        if callback_data == "admin:home":
            self._registry.clear_admin_draft(user_id)
            self._registry.clear_admin_message_draft(user_id)
            return [TelegramOutboundMessage(chat_id, "Управление доступом.", self._admin_home_menu())]
        message_draft_response = self._handle_admin_message_draft(user_id=user_id, chat_id=chat_id, text=text)
        if message_draft_response is not None:
            return message_draft_response
        draft_response = self._handle_admin_draft(user_id=user_id, chat_id=chat_id, text=text)
        if draft_response is not None:
            return draft_response
        parts = callback_data.split(":") if callback_data else []
        try:
            if callback_data == "admin:broadcasts":
                self._registry.clear_admin_draft(user_id)
                self._registry.clear_admin_message_draft(user_id)
                return [self._admin_broadcasts_message(chat_id)]
            if callback_data == "admin:broadcast:new":
                self._registry.clear_admin_draft(user_id)
                self._registry.set_admin_message_draft(
                    admin_telegram_user_id=user_id,
                    mode="broadcast",
                )
                return [TelegramOutboundMessage(
                    chat_id,
                    "Отправьте текст объявления одним сообщением. До подтверждения ничего не будет отправлено.",
                    {"inline_keyboard": [[{"text": "Отмена", "callback_data": "admin:broadcasts"}]]},
                )]
            if callback_data == "admin:broadcast-confirm":
                draft = self._registry.get_admin_message_draft(user_id)
                if draft is None or draft.mode != "broadcast" or not draft.body:
                    raise VersionConflictError("broadcast draft is missing")
                result = self._registry.queue_registered_broadcast(
                    body=draft.body,
                    created_by=user_id,
                    idempotency_key=f"telegram-admin-broadcast:{update_id}",
                )
                self._registry.clear_admin_message_draft(user_id)
                return [TelegramOutboundMessage(
                    chat_id,
                    f"Рассылка поставлена в очередь. Получателей: {result.recipient_count}.",
                    self._admin_broadcasts_message(chat_id).reply_markup,
                )]
            if len(parts) == 4 and parts[:2] == ["admin", "message"]:
                customer_id, page = int(parts[2]), int(parts[3])
                profile = self._registry.get_customer_telegram_profile(customer_id)
                if profile.telegram_user_id is None:
                    raise TelegramRegistryError("customer has no Telegram identity")
                self._registry.clear_admin_draft(user_id)
                self._registry.set_admin_message_draft(
                    admin_telegram_user_id=user_id,
                    mode="direct",
                    customer_id=customer_id,
                    page=page,
                )
                return [TelegramOutboundMessage(
                    chat_id,
                    "Отправьте текст пользователю одним сообщением. До подтверждения ничего не будет отправлено.",
                    {"inline_keyboard": [[{
                        "text": "Отмена",
                        "callback_data": f"admin:message-cancel:{customer_id}:{page}",
                    }]]},
                )]
            if callback_data == "admin:message-confirm":
                draft = self._registry.get_admin_message_draft(user_id)
                if draft is None or draft.mode != "direct" or draft.customer_id is None or not draft.body:
                    raise VersionConflictError("direct-message draft is missing")
                customer_id, page = draft.customer_id, draft.page
                self._registry.queue_admin_direct_message(
                    customer_id=customer_id,
                    body=draft.body,
                    created_by=user_id,
                    idempotency_key=f"telegram-admin-direct:{update_id}:{customer_id}",
                )
                self._registry.clear_admin_message_draft(user_id)
                return [TelegramOutboundMessage(
                    chat_id,
                    "Сообщение поставлено в очередь на отправку.",
                    self._admin_customer_message(chat_id, customer_id, page).reply_markup,
                )]
            if len(parts) == 5 and parts[:3] == ["admin", "message", "cancel"]:
                customer_id, page = int(parts[3]), int(parts[4])
                self._registry.clear_admin_message_draft(user_id)
                return [self._admin_customer_message(chat_id, customer_id, page)]
            if len(parts) == 3 and parts[:2] == ["admin", "nodes"]:
                self._registry.clear_admin_message_draft(user_id)
                return [self._admin_nodes_message(chat_id, int(parts[2]))]
            if len(parts) == 3 and parts[:2] == ["admin", "requests"]:
                self._registry.clear_admin_message_draft(user_id)
                return [self._admin_requests_message(chat_id, int(parts[2]))]
            if len(parts) == 3 and parts[:2] == ["admin", "customers"]:
                self._registry.clear_admin_message_draft(user_id)
                return [self._admin_customers_message(chat_id, int(parts[2]))]
            if len(parts) == 4 and parts[:2] == ["admin", "customer"]:
                self._registry.clear_admin_draft(user_id)
                self._registry.clear_admin_message_draft(user_id)
                return [self._admin_customer_message(chat_id, int(parts[2]), int(parts[3]))]
            if len(parts) == 3 and parts[:2] == ["admin", "blocked"]:
                self._registry.clear_admin_message_draft(user_id)
                return [self._admin_blocked_message(chat_id, int(parts[2]))]
            if len(parts) == 5 and parts[:2] == ["admin", "request"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                item = self._registry.get_pending_application(target_user_id)
                if item.row_version != version:
                    raise VersionConflictError("application is stale")
                self._registry.clear_admin_draft(user_id)
                return [self._admin_request_message(chat_id, target_user_id, page)]
            if len(parts) == 4 and parts[:2] == ["admin", "node"]:
                node_id, page = int(parts[2]), int(parts[3])
                policies = {policy.node_id: policy for policy in self._registry.list_node_provisioning_policies()}
                current = policies.get(node_id)
                enabled = not bool(current and current.provisioning_enabled)
                compatible = False
                if enabled:
                    if not self._list_nodes or not self._get_cached_inbound_options:
                        raise TelegramRegistryError("inbound validation unavailable")
                    compatible = self._inbound_one_supports_bot_contract(node_id, self._get_cached_inbound_options(self._list_nodes()))
                policy = self._registry.set_node_provisioning_policy(
                    node_id=node_id, provisioning_enabled=enabled,
                    total_bytes=current.total_bytes if current else 0,
                    validity_days=current.validity_days if current else 0,
                    client_enabled=current.client_enabled if current else True,
                    expected_policy_version=current.policy_version if current else 0,
                    idempotency_key=f"telegram-admin-node:{update_id}:{node_id}",
                    updated_by=f"telegram:{user_id}", node_is_compatible=compatible,
                )
                state = "включена" if policy.provisioning_enabled else "выключена"
                return [TelegramOutboundMessage(chat_id, f"TG-политика ноды {state}.", self._admin_nodes_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "new"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                item = self._registry.get_pending_application(target_user_id)
                if item.row_version != version:
                    raise VersionConflictError("application is stale")
                self._registry.set_admin_draft(
                    admin_telegram_user_id=user_id, action="new_customer_name",
                    telegram_user_id=target_user_id, expected_row_version=version, page=page,
                )
                return [self._admin_new_name_choice(chat_id, telegram_user_id=target_user_id, row_version=version, page=page, suggested_email=item.suggested_email)]
            if len(parts) == 5 and parts[:2] == ["admin", "new-use"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                item = self._registry.get_pending_application(target_user_id)
                if item.row_version != version:
                    raise VersionConflictError("application is stale")
                self._registry.set_admin_draft(
                    admin_telegram_user_id=user_id, action="new_customer_name",
                    telegram_user_id=target_user_id, expected_row_version=version, page=page,
                    value=item.suggested_email,
                )
                return [self._admin_new_customer_preview(chat_id, telegram_user_id=target_user_id, row_version=version, page=page, email_display=item.suggested_email)]
            if len(parts) == 5 and parts[:2] == ["admin", "new-input"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                self._registry.set_admin_draft(
                    admin_telegram_user_id=user_id, action="new_customer_name",
                    telegram_user_id=target_user_id, expected_row_version=version, page=page,
                )
                return [TelegramOutboundMessage(chat_id, "Отправьте новое имя/email для пользователя одним сообщением.")]
            if len(parts) == 5 and parts[:2] == ["admin", "new-confirm"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                draft = self._registry.get_admin_draft(user_id)
                if not draft or draft.action != "new_customer_name" or draft.telegram_user_id != target_user_id or draft.expected_row_version != version or not draft.value:
                    raise VersionConflictError("approval draft is missing")
                result = self._registry.approve_new_application(
                    telegram_user_id=target_user_id, expected_identity_version=version, email_display=draft.value,
                    idempotency_key=f"telegram-admin-approve:{update_id}:{target_user_id}", approved_by=f"telegram:{user_id}",
                )
                self._registry.clear_admin_draft(user_id)
                return [TelegramOutboundMessage(chat_id, f"Заявка одобрена: {result.email_display}. Подготовка на {len(result.target_node_ids)} нодах поставлена в очередь.", self._admin_requests_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "existing"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                self._registry.set_admin_draft(
                    admin_telegram_user_id=user_id, action="existing_customer_email",
                    telegram_user_id=target_user_id, expected_row_version=version, page=page,
                )
                return [TelegramOutboundMessage(chat_id, "Отправьте точный существующий service username/email одним сообщением.")]
            if len(parts) == 6 and parts[:2] == ["admin", "existing-confirm"]:
                target_user_id, version, customer_id, page = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
                draft = self._registry.get_admin_draft(user_id)
                customer = self._registry.get_customer(customer_id)
                if not draft or draft.action != "existing_customer_email" or draft.telegram_user_id != target_user_id or draft.expected_row_version != version or draft.value != customer.email_display:
                    raise VersionConflictError("existing customer draft is missing")
                result = self._registry.approve_existing_application(
                    telegram_user_id=target_user_id, customer_id=customer_id, expected_identity_version=version,
                    idempotency_key=f"telegram-admin-existing:{update_id}:{target_user_id}", approved_by=f"telegram:{user_id}",
                )
                self._registry.clear_admin_draft(user_id)
                return [TelegramOutboundMessage(chat_id, f"Заявка привязана к {result.email_display}.", self._admin_requests_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "existing-discovered-confirm"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                draft = self._registry.get_admin_draft(user_id)
                if (
                    not draft or draft.action != "existing_customer_email"
                    or draft.telegram_user_id != target_user_id or draft.expected_row_version != version
                    or not draft.value or self._discover_existing is None
                ):
                    raise VersionConflictError("existing customer draft is missing")
                discovered = self._discover_existing(draft.value)
                result = self._registry.adopt_discovered_existing_application(
                    telegram_user_id=target_user_id,
                    email_display=draft.value,
                    bindings=tuple(
                        DiscoveredExistingBinding(
                            node_id=item.node_id, inbound_id=item.inbound_id,
                            remote_client_id=item.remote_client_id, remote_sub_id=item.remote_sub_id,
                            remote_email=item.remote_email, enabled=item.enabled,
                        )
                        for item in discovered
                    ),
                    expected_identity_version=version,
                    idempotency_key=f"telegram-admin-adopt-existing:{update_id}:{target_user_id}",
                    approved_by=f"telegram:{user_id}",
                )
                self._registry.clear_admin_draft(user_id)
                return [TelegramOutboundMessage(chat_id, f"Заявка привязана к {result.email_display}. Найдено нод: {result.confirmed_binding_count}.", self._admin_requests_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "reject"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                self._registry.reject_application(telegram_user_id=target_user_id, expected_identity_version=version, idempotency_key=f"telegram-admin-reject:{update_id}:{target_user_id}", rejected_by=f"telegram:{user_id}")
                return [TelegramOutboundMessage(chat_id, "Заявка отклонена.", self._admin_requests_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "block"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                self._registry.block_identity(telegram_user_id=target_user_id, expected_identity_version=version, idempotency_key=f"telegram-admin-block:{update_id}:{target_user_id}", blocked_by=f"telegram:{user_id}")
                return [TelegramOutboundMessage(chat_id, "Заявка заблокирована.", self._admin_requests_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "unblock"]:
                target_user_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                self._registry.unblock_identity(telegram_user_id=target_user_id, expected_identity_version=version, idempotency_key=f"telegram-admin-unblock:{update_id}:{target_user_id}", unblocked_by=f"telegram:{user_id}")
                return [TelegramOutboundMessage(chat_id, "Заявка разблокирована. Доступ автоматически не выдан.", self._admin_blocked_message(chat_id, page).reply_markup)]
            if len(parts) == 5 and parts[:2] == ["admin", "customer-delete"]:
                customer_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                customer = self._registry.get_customer(customer_id)
                if customer.row_version != version:
                    raise VersionConflictError("customer is stale")
                self._registry.set_admin_draft(admin_telegram_user_id=user_id, action="delete_customer_confirmation", customer_id=customer_id, expected_row_version=version, page=page)
                return [TelegramOutboundMessage(chat_id, f"Чтобы удалить {customer.email_display}, отправьте точный service username/email одним сообщением.")]
            if len(parts) == 5 and parts[:2] == ["admin", "customer-delete-confirm"]:
                customer_id, version, page = int(parts[2]), int(parts[3]), int(parts[4])
                draft = self._registry.get_admin_draft(user_id)
                customer = self._registry.get_customer(customer_id)
                if not draft or draft.action != "delete_customer_confirmation" or draft.customer_id != customer_id or draft.expected_row_version != version or draft.value != customer.email_display:
                    raise VersionConflictError("delete confirmation is missing")
                preview = self._registry.preview_customer_operation(customer_id=customer_id, operation_type="delete")
                if preview.expected_customer_version != version:
                    raise VersionConflictError("customer is stale")
                self._registry.queue_customer_operation(customer_id=customer_id, operation_type="delete", expected_customer_version=preview.expected_customer_version, target_snapshot_digest=preview.target_snapshot_digest, idempotency_key=f"telegram-admin-delete:{update_id}:{customer_id}", created_by=f"telegram:{user_id}")
                self._registry.clear_admin_draft(user_id)
                return [TelegramOutboundMessage(chat_id, "Удаление поставлено в очередь.", self._admin_customers_message(chat_id, page).reply_markup)]
            if len(parts) == 6 and parts[:2] == ["admin", "customer-op"]:
                customer_id, version, operation, page = int(parts[2]), int(parts[3]), parts[4], int(parts[5])
                preview = self._registry.preview_customer_operation(customer_id=customer_id, operation_type=operation)
                if preview.expected_customer_version != version:
                    raise VersionConflictError("customer is stale")
                verb = "Приостановить" if operation == "suspend" else "Возобновить"
                return [TelegramOutboundMessage(chat_id, f"{verb} пользователя? Будет затронуто нод: {len(preview.targets)}.", {"inline_keyboard": [[{"text": f"✓ {verb}", "callback_data": f"admin:customer-op-confirm:{customer_id}:{version}:{operation}:{page}"}], [{"text": "Отмена", "callback_data": f"admin:customer:{customer_id}:{page}"}]]})]
            if len(parts) == 6 and parts[:2] == ["admin", "customer-op-confirm"]:
                customer_id, version, operation, page = int(parts[2]), int(parts[3]), parts[4], int(parts[5])
                preview = self._registry.preview_customer_operation(customer_id=customer_id, operation_type=operation)
                if preview.expected_customer_version != version:
                    raise VersionConflictError("customer is stale")
                self._registry.queue_customer_operation(customer_id=customer_id, operation_type=operation, expected_customer_version=preview.expected_customer_version, target_snapshot_digest=preview.target_snapshot_digest, idempotency_key=f"telegram-admin-customer-{operation}:{update_id}:{customer_id}", created_by=f"telegram:{user_id}")
                verb = "Приостановка" if operation == "suspend" else "Возобновление"
                return [TelegramOutboundMessage(chat_id, f"{verb} поставлена в очередь.", self._admin_customers_message(chat_id, page).reply_markup)]
            if len(parts) == 6 and parts[:2] == ["admin", "cn"]:
                customer_id, node_id, action, page = int(parts[2]), int(parts[3]), parts[4], int(parts[5])
                customer = self._registry.get_customer(customer_id)
                if action == "add":
                    self._registry.queue_customer_node_add(customer_id=customer_id, node_id=node_id, expected_customer_version=customer.row_version, idempotency_key=f"telegram-admin-node-add:{update_id}:{customer_id}:{node_id}", created_by=f"telegram:{user_id}")
                    return [TelegramOutboundMessage(chat_id, "Добавление на ноду поставлено в очередь.", self._admin_customer_message(chat_id, customer_id, page).reply_markup)]
                operation = f"{action}_node"
                preview = self._registry.preview_customer_node_operation(customer_id=customer_id, node_id=node_id, operation_type=operation)
                return [TelegramOutboundMessage(chat_id, f"Подтвердить действие на ноде {preview.targets[0].node_name}?", {"inline_keyboard": [[{"text": "✓ Подтвердить", "callback_data": f"admin:cn-confirm:{customer_id}:{node_id}:{action}:{page}"}], [{"text": "Отмена", "callback_data": f"admin:customer:{customer_id}:{page}"}]]})]
            if len(parts) == 6 and parts[:2] == ["admin", "cn-confirm"]:
                customer_id, node_id, action, page = int(parts[2]), int(parts[3]), parts[4], int(parts[5])
                operation = f"{action}_node"
                preview = self._registry.preview_customer_node_operation(customer_id=customer_id, node_id=node_id, operation_type=operation)
                self._registry.queue_customer_node_operation(customer_id=customer_id, node_id=node_id, operation_type=operation, expected_customer_version=preview.expected_customer_version, target_snapshot_digest=preview.target_snapshot_digest, idempotency_key=f"telegram-admin-node-{action}:{update_id}:{customer_id}:{node_id}", created_by=f"telegram:{user_id}")
                return [TelegramOutboundMessage(chat_id, "Операция на ноде поставлена в очередь.", self._admin_customer_message(chat_id, customer_id, page).reply_markup)]
        except (ValueError, LifecycleUnavailableError, NodePolicyUnavailableError, VersionConflictError, IdempotencyConflictError, TelegramRegistryError):
            return [TelegramOutboundMessage(chat_id, "Команда не выполнена: данные устарели или нода не готова.", self._admin_home_menu())]
        return [TelegramOutboundMessage(chat_id, "Команда администратора не распознана.", self._admin_home_menu())]

    @staticmethod
    def _approved_menu(*, suspended: bool = False) -> dict[str, Any]:
        rows = [[{"text": "◎ Получить доступ", "callback_data": "subscription:get"}]]
        if suspended:
            rows.append([{"text": "✉ Написать администратору", "callback_data": "support:appeal"}])
        else:
            rows.extend([
                [{"text": "⊞ Подключение", "callback_data": "setup:menu"}],
                [{"text": "↻ Сменить ссылку", "callback_data": "subscription:rotate"}],
                [{"text": "⚙ Уведомления", "callback_data": "preferences:menu"}],
                [{"text": "? Помощь", "callback_data": "help"}],
            ])
        return {"inline_keyboard": rows}

    def _subscription_url(
        self, *, user_id: int, chat_id: int, rotate: bool = False
    ) -> tuple[str | None, TelegramOutboundMessage | None]:
        access = self._registry.get_customer_access(user_id)
        decision = resolve_effective_access(
            access_status=access.access_status,
            customer_id=access.customer_id,
            email_display=access.email_display,
            customer_status=access.customer_status,
            blocked_from_status=access.blocked_from_status,
        )
        if decision.state == "suspended":
            return None, TelegramOutboundMessage(
                chat_id,
                "Доступ временно приостановлен. Если это ошибка, напишите администратору.",
                self._approved_menu(suspended=True),
            )
        if not decision.can_receive_subscription:
            return None, TelegramOutboundMessage(chat_id, "Сейчас доступ ещё не готов.", self._approved_menu())
        if not self._list_nodes or not self._get_links_filtered:
            return None, TelegramOutboundMessage(chat_id, "Доступ готовится. Пожалуйста, проверьте статус позже.", self._approved_menu())
        try:
            links = self._get_links_filtered(self._list_nodes(), access.email_display, None)
        except Exception:
            links = []
        if not links:
            return None, TelegramOutboundMessage(chat_id, "Доступ готовится. Пожалуйста, проверьте статус позже.", self._approved_menu())
        try:
            token = regenerate_token(self._registry.database_path, "email", access.email_display) if rotate else None
            if not token:
                token = ensure_tokens(self._registry.database_path, "email", [access.email_display]).get(access.email_display)
        except Exception:
            token = None
        if not token or not self._public_base_url:
            return None, TelegramOutboundMessage(chat_id, "Ссылку пока нельзя выдать. Пожалуйста, попробуйте позже.", self._approved_menu())
        return f"{self._public_base_url}/api/v1/sub/{token}", None

    def _subscription_message(self, *, user_id: int, chat_id: int, rotate: bool = False) -> TelegramOutboundMessage:
        url, unavailable = self._subscription_url(user_id=user_id, chat_id=chat_id, rotate=rotate)
        if unavailable is not None:
            return unavailable
        assert url is not None
        return TelegramOutboundMessage(
            chat_id,
            f"Ваша ссылка доступа:\n{url}",
            self._approved_menu(),
        )

    @staticmethod
    def _setup_menu(chat_id: int) -> TelegramOutboundMessage:
        return TelegramOutboundMessage(
            chat_id,
            "Подключение\n\nВыберите устройство. Затем добавьте ссылку или QR-код в совместимое приложение. Не пересылайте их другим людям.",
            {"inline_keyboard": [
                [{"text": "Android", "callback_data": "setup:android"}, {"text": "iPhone / iPad", "callback_data": "setup:ios"}],
                [{"text": "Компьютер", "callback_data": "setup:desktop"}],
                [{"text": "⊞ Показать QR", "callback_data": "setup:qr"}],
                [{"text": "← Меню", "callback_data": "menu:home"}],
            ]},
        )

    @staticmethod
    def _setup_guide(chat_id: int, platform: str) -> TelegramOutboundMessage:
        headings = {"android": "Android", "ios": "iPhone / iPad", "desktop": "Компьютер"}
        heading = headings.get(platform)
        if heading is None:
            return TelegramOutboundMessage(chat_id, "Выберите устройство из списка.", TelegramRegistrationService._approved_menu())
        return TelegramOutboundMessage(
            chat_id,
            f"Подключение: {heading}\n\n1. Установите совместимое приложение для подписок.\n2. В нём выберите добавление по URL или сканирование QR.\n3. Получите ссылку кнопкой «◎ Получить доступ» либо покажите QR здесь.\n4. Не пересылайте ссылку и QR: это ваш личный доступ.",
            {"inline_keyboard": [
                [{"text": "⊞ Показать QR", "callback_data": "setup:qr"}],
                [{"text": "← Устройства", "callback_data": "setup:menu"}],
                [{"text": "← Меню", "callback_data": "menu:home"}],
            ]},
        )

    def _setup_qr_message(self, *, user_id: int, chat_id: int) -> TelegramOutboundMessage:
        url, unavailable = self._subscription_url(user_id=user_id, chat_id=chat_id)
        if unavailable is not None:
            return unavailable
        assert url is not None
        try:
            png = build_subscription_qr_png(url)
        except TelegramQrError:
            return TelegramOutboundMessage(chat_id, "QR пока не удалось подготовить. Попробуйте ещё раз позже.", self._approved_menu())
        return TelegramOutboundMessage(
            chat_id,
            "Ваш QR-код доступа. Не пересылайте его другим людям.",
            {"inline_keyboard": [[{"text": "← Подключение", "callback_data": "setup:menu"}]]},
            photo_png=png,
            photo_filename="access-qr.png",
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

    def _preferences_message(self, user_id: int, chat_id: int) -> TelegramOutboundMessage:
        preferences = self._registry.get_notification_preferences(user_id)
        state = "включены" if preferences.background_notifications_enabled else "выключены"
        action = "Выключить" if preferences.background_notifications_enabled else "Включить"
        return TelegramOutboundMessage(
            chat_id,
            f"Фоновые уведомления: {state}. Ответы на ваши команды приходят всегда.",
            {"inline_keyboard": [
                [{"text": action, "callback_data": "preferences:toggle-background"}],
                [{"text": "← Меню", "callback_data": "menu:home"}],
            ]},
        )

    @staticmethod
    def _help_message(chat_id: int) -> TelegramOutboundMessage:
        return TelegramOutboundMessage(
            chat_id,
            "Помощь\n\n"
            "◎ Получить доступ — выдаёт вашу текущую ссылку.\n"
            "↻ Сменить ссылку — сразу отключает предыдущую.\n"
            "⚙ Уведомления — включает или выключает фоновые сообщения.\n\n"
            "Если доступ приостановлен, в меню появится кнопка для сообщения администратору.",
            {"inline_keyboard": [[{"text": "← Меню", "callback_data": "menu:home"}]]},
        )

    def handle_update(self, update: dict[str, Any]) -> list[TelegramOutboundMessage]:
        update_id = update.get("update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id <= 0:
            return []
        actor = _private_actor(update)
        if actor is None:
            return []
        user_id, chat_id, sender, text, callback_data, phone_number = actor
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
            phone_number=phone_number,
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
            if callback_data == "setup:menu":
                return [self._setup_menu(chat_id)]
            if callback_data in {"setup:android", "setup:ios", "setup:desktop"}:
                return [self._setup_guide(chat_id, callback_data.removeprefix("setup:"))]
            if callback_data == "setup:qr":
                return [self._setup_qr_message(user_id=user_id, chat_id=chat_id)]
            if callback_data == "subscription:rotate":
                return [TelegramOutboundMessage(
                    chat_id,
                    "Старая ссылка сразу перестанет работать. Подтвердить смену?",
                    {"inline_keyboard": [[{"text": "✓ Подтвердить смену", "callback_data": "subscription:rotate:confirm"}], [{"text": "Отмена", "callback_data": "menu:home"}]]},
                )]
            if callback_data == "support:appeal":
                return [TelegramOutboundMessage(chat_id, "Напишите одним сообщением, почему доступ нужно восстановить. Это попадёт администратору на рассмотрение.")]
            if callback_data == "preferences:menu" or text and text.strip().startswith("/settings"):
                return [self._preferences_message(user_id, chat_id)]
            if callback_data == "preferences:toggle-background":
                self._registry.toggle_background_notifications(user_id)
                return [self._preferences_message(user_id, chat_id)]
            if callback_data == "menu:home":
                return [self._approved_status(user_id, chat_id)]
            if callback_data == "help":
                return [self._help_message(chat_id)]
            if text and text.strip().startswith("/status"):
                return [self._approved_status(user_id, chat_id)]
            if text and text.strip().startswith("/subscription"):
                return [self._subscription_message(user_id=user_id, chat_id=chat_id)]
            decision = resolve_effective_access(
                access_status=access.access_status,
                customer_id=access.customer_id,
                email_display=access.email_display,
                customer_status=access.customer_status,
                blocked_from_status=access.blocked_from_status,
            )
            if text and decision.can_submit_appeal:
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
