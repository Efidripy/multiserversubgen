"""Small, explicit RU/EN catalogue for Telegram user-facing conversations."""

from __future__ import annotations


def normalize_telegram_locale(value: object) -> str:
    """Collapse Telegram language codes to the two supported product locales."""

    return "en" if isinstance(value, str) and value.lower().startswith("en") else "ru"


_MESSAGES: dict[str, dict[str, str]] = {
    "subscription_prefix": {
        "ru": "Персональная ссылка доступа, скопируйте и вставьте её в ваше приложение-клиент:",
        "en": "Personal access link. Copy it and paste it into your client application:",
    },
    "access_choice": {
        "ru": "Получить доступ\n\nВыберите удобное действие: скопировать персональную ссылку, показать QR-код, проверить готовность или сменить ссылку.",
        "en": "Get access\n\nChoose an action: copy your personal link, show a QR code, check readiness, or replace the link.",
    },
    "unavailable": {"ru": "Сейчас это действие недоступно.", "en": "This action is not available right now."},
    "pending_wait": {"ru": "Заявка уже ожидает проверки. Пожалуйста, дождитесь ответа.", "en": "Your request is already awaiting review. Please wait for a response."},
    "required_intro": {
        "ru": "Здравствуйте.\n\n⚠️ ВНИМАНИЕ\n\nЧтобы отправить заявку, напишите одним сообщением немного о себе и причине обращения. Без такого сообщения заявка не будет отправлена.",
        "en": "Hello.\n\n⚠️ ATTENTION\n\nTo send a request, write one message briefly introducing yourself and the reason for contacting us. A request cannot be sent without it.",
    },
    "intro_required": {"ru": "Представление обязательно. Отправьте одним сообщением немного о себе и причине обращения.", "en": "An introduction is required. Send one message briefly introducing yourself and your reason for contacting us."},
    "intro_not_required": {"ru": "Сейчас представление не требуется.", "en": "An introduction is not required right now."},
    "status_waiting": {"ru": "Заявка ещё ожидает решения администратора.", "en": "The request is still awaiting an administrator decision."},
    "suspended": {"ru": "Доступ временно приостановлен. Если это ошибка, напишите администратору.", "en": "Access is temporarily suspended. If this is an error, write to the administrator."},
    "provisioning": {"ru": "Доступ ещё готовится на всех назначенных нодах. Проверьте статус позже.", "en": "Access is still being prepared on all assigned nodes. Check the status later."},
    "not_ready": {"ru": "Сейчас доступ ещё не готов.", "en": "Access is not ready yet."},
    "link_later": {"ru": "Ссылку пока нельзя выдать. Пожалуйста, попробуйте позже.", "en": "The link cannot be issued yet. Please try again later."},
    "setup_menu": {
        "ru": "Подключение\n\nВыберите устройство и следуйте инструкции для совместимого приложения. Ссылку или QR-код можно получить отдельной кнопкой «◎ Получить доступ». Не пересылайте их другим людям.",
        "en": "Connection\n\nChoose your device and follow the instructions for a compatible app. Get a link or QR code with the separate “◎ Get access” button. Do not forward them to anyone.",
    },
    "setup_guide": {
        "ru": "Подключение: {heading} · инструкция {version}\n\n1. Нажмите название приложения ниже — Telegram откроет его официальный источник.\n2. Установите приложение и выберите импорт по ссылке или QR-коду.\n3. Вернитесь в бот: «◎ Получить доступ» → ссылка или QR-код.\n4. Не пересылайте ссылку или QR-код: это ваш персональный доступ.",
        "en": "Connection: {heading} · guide {version}\n\n1. Tap an app name below — Telegram opens its official source.\n2. Install the app and choose import by URL or QR code.\n3. Return to the bot: “◎ Get access” → link or QR.\n4. Do not forward the link or QR: it is your personal access.",
    },
    "qr_failed": {"ru": "QR пока не удалось подготовить. Попробуйте ещё раз позже.", "en": "The QR code could not be prepared yet. Please try again later."},
    "qr_caption": {"ru": "Ваш QR-код доступа. Не пересылайте его другим людям.", "en": "Your access QR code. Do not forward it to anyone."},
    "status_access": {"ru": "Статус доступа: {status}.{traffic}", "en": "Access status: {status}.{traffic}"},
    "traffic_empty": {"ru": "\nДанные о трафике пока не поступали.", "en": "\nTraffic data has not arrived yet."},
    "traffic_known": {"ru": "\nТрафик за всё время: {traffic}.\nПоследнее обновление данных: {updated}.", "en": "\nLifetime traffic: {traffic}.\nLast data update: {updated}."},
    "diagnostics_provisioning": {"ru": "Проверка готовности\n\nРегистрация ещё не завершилась на всех назначенных нодах. Доступ появится автоматически после успешного завершения всего набора.", "en": "Readiness check\n\nRegistration is not complete on every assigned node. Access appears automatically after the entire set completes successfully."},
    "diagnostics_ready": {"ru": "Проверка готовности\n\nДоступ готов. Можно получить ссылку или QR-код и импортировать его в выбранное приложение.", "en": "Readiness check\n\nAccess is ready. Get a link or QR code and import it into your chosen app."},
    "diagnostics_suspended": {"ru": "Проверка готовности\n\nДоступ приостановлен. Через меню можно отправить сообщение администратору.", "en": "Readiness check\n\nAccess is suspended. You can send a message to the administrator from the menu."},
    "diagnostics_other": {"ru": "Проверка готовности\n\nСейчас доступ недоступен. Попробуйте позже или откройте помощь.", "en": "Readiness check\n\nAccess is unavailable right now. Try later or open Help."},
    "rotation": {"ru": "⚠️ ВНИМАНИЕ\n\nСтарая ссылка сразу перестанет работать. Подтвердить смену?", "en": "⚠️ ATTENTION\n\nThe old link stops working immediately. Confirm replacement?"},
    "appeal_prompt": {"ru": "Напишите одним сообщением, почему доступ нужно восстановить. Это попадёт администратору на рассмотрение.", "en": "Write one message explaining why access should be restored. It will be sent to the administrator for review."},
    "support_prompt": {"ru": "Тема: {label}.\n\n⚠️ Обращение ещё не отправлено. Теперь отправьте одним сообщением описание проблемы — после этого оно попадёт администратору. Максимум 1000 символов.", "en": "Topic: {label}.\n\n⚠️ The request has not been sent yet. Now send one message describing the issue; it will then be sent to the administrator. Maximum 1000 characters."},
    "support_open": {"ru": "У вас уже есть открытое обращение. Дождитесь ответа администратора.", "en": "You already have an open support request. Please wait for the administrator’s response."},
    "support_unavailable": {"ru": "Новое обращение пока недоступно. Попробуйте позже.", "en": "A new support request is not available yet. Please try later."},
    "support_invalid": {"ru": "Не удалось принять обращение. Проверьте, что сообщение непустое и не длиннее 1000 символов.", "en": "The request could not be accepted. Make sure the message is not empty and is no longer than 1000 characters."},
    "support_sent": {"ru": "Обращение принято и передано администратору.", "en": "Your request was accepted and sent to the administrator."},
    "appeal_invalid": {"ru": "Не удалось принять сообщение. Попробуйте короче.", "en": "The message could not be accepted. Please try a shorter one."},
    "appeal_sent": {"ru": "Сообщение принято и передано администратору.", "en": "Your message was accepted and sent to the administrator."},
    "introduction_invalid": {"ru": "⚠️ ВНИМАНИЕ\n\nНапишите непустое сообщение о себе и причине обращения, но не длиннее допустимого размера.", "en": "⚠️ ATTENTION\n\nWrite a non-empty message about yourself and your reason for contacting us, within the allowed length."},
    "application_sent": {"ru": "Спасибо. Заявка отправлена и ожидает проверки администратора.", "en": "Thank you. Your request was sent and is awaiting administrator review."},
    "introduction_saved": {"ru": "Спасибо. Заявка по-прежнему ожидает проверки.", "en": "Thank you. The request is still awaiting review."},
    "start_first": {"ru": "Для начала отправьте /start.", "en": "Send /start to begin."},
    "language_menu": {"ru": "Язык интерфейса", "en": "Interface language"},
    "language_saved": {"ru": "Язык интерфейса: русский.", "en": "Interface language: English."},
    "link_preparing": {"ru": "Доступ готовится. Пожалуйста, проверьте статус позже.", "en": "Access is being prepared. Please check the status later."},
    "preferences": {"ru": "Фоновые уведомления: {background}.\nНапоминания о сроке: {expiry}.\nНапоминания о трафике: {traffic}.\n\nОтветы на ваши команды приходят всегда.", "en": "Background notifications: {background}.\nExpiry reminders: {expiry}.\nTraffic reminders: {traffic}.\n\nReplies to your commands are always delivered."},
    "preference_background_action": {"ru": "{action} фоновые уведомления", "en": "{action} background notifications"},
    "preference_expiry_action": {"ru": "{action} напоминания о сроке", "en": "{action} expiry reminders"},
    "preference_traffic_action": {"ru": "{action} напоминания о трафике", "en": "{action} traffic reminders"},
    "status_active": {"ru": "активен", "en": "active"},
    "status_suspended": {"ru": "приостановлен", "en": "suspended"},
    "status_suspend_partial": {"ru": "частично приостановлен", "en": "partially suspended"},
    "status_provisioning": {"ru": "готовится", "en": "being prepared"},
    "status_unknown": {"ru": "недоступен", "en": "unavailable"},
    "help": {"ru": "Помощь\n\n◎ Получить доступ — ссылка, QR-код, проверка готовности и смена ссылки.\n↻ Смена ссылки сразу отключает предыдущую.\n⚙ Уведомления — включает или выключает фоновые сообщения.\n\nЕсли доступ приостановлен, в меню появится кнопка для сообщения администратору.", "en": "Help\n\n◎ Get access — link, QR code, readiness check and link replacement.\n↻ Replacing a link immediately disables the previous one.\n⚙ Notifications — turn background messages on or off.\n\nIf access is suspended, the menu shows a button to message the administrator."},
    "support_menu": {"ru": "Поддержка\n\nВыберите тему обращения. Затем отправьте одно сообщение с описанием проблемы.", "en": "Support\n\nChoose a topic, then send one message describing the issue."},
    "qr_deleted": {"ru": "QR-код удалён из чата.", "en": "The QR code was removed from the chat."},
    "qr_unknown": {"ru": "Не удалось определить QR-сообщение. Откройте новый QR-код при необходимости.", "en": "The QR message could not be identified. Open a new QR code if needed."},
}

_BUTTONS: dict[str, dict[str, str]] = {
    "get_access": {"ru": "◎ Получить доступ", "en": "◎ Get access"},
    "get_link": {"ru": "⊙ Получить ссылку", "en": "⊙ Get link"},
    "show_qr": {"ru": "⊞ Показать QR-код", "en": "⊞ Show QR code"},
    "check_ready": {"ru": "⌁ Проверить готовность", "en": "⌁ Check readiness"},
    "rotate": {"ru": "↻ Сменить ссылку", "en": "↻ Replace link"},
    "confirm": {"ru": "✓ Подтвердить", "en": "✓ Confirm"},
    "menu": {"ru": "← Меню", "en": "← Menu"},
    "connection": {"ru": "⊞ Подключение", "en": "⊞ Connection"},
    "notifications": {"ru": "⚙ Уведомления", "en": "⚙ Notifications"},
    "help": {"ru": "? Помощь", "en": "? Help"},
    "support": {"ru": "✉ Написать в поддержку", "en": "✉ Contact support"},
    "language": {"ru": "◉ Язык", "en": "◉ Language"},
    "delete_qr": {"ru": "⌫ Удалить QR", "en": "⌫ Delete QR"},
    "devices": {"ru": "← Устройства", "en": "← Devices"},
    "repeat_guide": {"ru": "↻ Повторить инструкцию", "en": "↻ Repeat guide"},
    "back_help": {"ru": "← Помощь", "en": "← Help"},
    "write_admin": {"ru": "✉ Написать администратору", "en": "✉ Message administrator"},
}

_CATEGORIES: dict[str, dict[str, str]] = {
    "link": {"ru": "Ссылка не открывается", "en": "Link does not open"},
    "connection": {"ru": "Подключение не работает", "en": "Connection does not work"},
    "device": {"ru": "Сменил устройство", "en": "Changed device"},
    "directions": {"ru": "Мало или нет направлений", "en": "Few or no routes work"},
    "other": {"ru": "Другое", "en": "Other"},
}


def tr(locale: object, key: str, **values: object) -> str:
    language = normalize_telegram_locale(locale)
    try:
        template = _MESSAGES[key][language]
    except KeyError as exc:  # programmer error: never silently leak the other locale
        raise KeyError(f"unknown Telegram locale message: {key}") from exc
    return template.format(**values)


def button(locale: object, key: str) -> str:
    language = normalize_telegram_locale(locale)
    try:
        return _BUTTONS[key][language]
    except KeyError as exc:
        raise KeyError(f"unknown Telegram locale button: {key}") from exc


def support_category(locale: object, category: str) -> str | None:
    item = _CATEGORIES.get(category)
    return item[normalize_telegram_locale(locale)] if item else None
