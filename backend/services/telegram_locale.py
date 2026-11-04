"""Small, explicit RU/EN catalogue for Telegram user-facing conversations."""

from __future__ import annotations


def normalize_telegram_locale(value: object) -> str:
    """Collapse Telegram language codes to the two supported product locales."""

    return "en" if isinstance(value, str) and value.lower().startswith("en") else "ru"


_MESSAGES: dict[str, dict[str, str]] = {
    "subscription_prefix": {
        "ru": "🔑 Ваша личная ссылка\n\nЧто с ней делать:\n1️⃣ Нажмите «📋 Скопировать ссылку».\n2️⃣ Откройте приложение и добавьте в него ссылку.\n3️⃣ Включите подключение в приложении.\n\nНет приложения? Нажмите «📖 Как подключить».\nНе передавайте ссылку другим: это ваш ключ.\n\nСсылка:",
        "en": "🔑 Your personal link\n\nWhat to do:\n1️⃣ Tap “📋 Copy link”.\n2️⃣ Open the app and add the link.\n3️⃣ Turn on the connection in the app.\n\nNo app yet? Tap “📖 How to connect”.\nDo not share the link: it is your key.\n\nLink:",
    },
    "access_choice": {
        "ru": "🔑 Мой доступ\n\nЗдесь ваша ссылка для подключения. Она работает как ключ.\n\n🔗 Подключаете устройство, на котором открыт бот: получите ссылку.\n📷 Подключаете другое устройство: покажите QR-код и наведите на него камеру.\n👋 Нужно дать доступ другу на время: сделайте ссылку для гостя.\n🔄 Кто-то узнал вашу ссылку: замените её.",
        "en": "🔑 My access\n\nHere is your connection link. It works like a key.\n\n🔗 Connecting the device with this bot open: get the link.\n📷 Connecting another device: show the QR code and scan it.\n👋 Giving a friend temporary access: make a guest link.\n🔄 Someone learned your link: replace it.",
    },
    "unavailable": {"ru": "😕 Сейчас это не получилось. Попробуйте ещё раз через минуту. Если повторится, откройте «🆘 Помощь».", "en": "😕 That did not work right now. Please try again in a minute. If it happens again, open “🆘 Help”."},
    "pending_wait": {"ru": "⏳ Ваша заявка уже у администратора. Ответ придёт сюда, в бот.", "en": "Your request is already awaiting review. Please wait for a response."},
    "required_intro": {
        "ru": "👋 Здравствуйте!\n\nЧтобы получить доступ, напишите одним сообщением, кто вы и зачем вам доступ. Администратор прочитает, а ответ придёт сюда, в бот.",
        "en": "Hello.\n\nTo send a request, write one message about yourself and why you are contacting us. Then the request will go to an administrator.",
    },
    "intro_required": {"ru": "Напишите одним сообщением, кто вы и зачем вам доступ. Без этого заявка не отправится.", "en": "An introduction is required. Send one message briefly introducing yourself and your reason for contacting us."},
    "intro_not_required": {"ru": "Сейчас представление не требуется.", "en": "An introduction is not required right now."},
    "status_waiting": {"ru": "⏳ Заявка ещё у администратора. Ответ придёт сюда, в бот.", "en": "The request is still awaiting an administrator decision."},
    "suspended": {"ru": "⏸ Доступ приостановлен. Если это ошибка, нажмите «💬 Написать администратору».", "en": "⏸ Access is suspended. If this is an error, tap “💬 Message administrator”."},
    "provisioning": {"ru": "⏳ Готовим ваш доступ. Ничего делать не нужно, загляните чуть позже.", "en": "⏳ We are preparing your access. You do not need to do anything; check again a little later."},
    "not_ready": {"ru": "⏳ Доступ ещё готовится. Ничего делать не нужно, загляните чуть позже.", "en": "⏳ Access is still being prepared. You do not need to do anything; check again later."},
    "link_later": {"ru": "😕 Ссылку сейчас выдать не получается. Попробуйте ещё раз через несколько минут.", "en": "😕 We cannot provide the link right now. Please try again in a few minutes."},
    "setup_menu": {
        "ru": "📖 Как подключить\n\nНа каком устройстве нужен доступ? Выберите его, и бот покажет, что нажимать.",
        "en": "📖 How to connect\n\nWhich device needs access? Choose it and the bot will show what to tap.",
    },
    "setup_guide": {
        "ru": "📖 Инструкция\n\n1️⃣ Установите приложение: нажмите на его название ниже. Если сомневаетесь, берите первое.\n2️⃣ Вернитесь сюда: «🔑 Мой доступ», затем «🔗 Получить ссылку».\n3️⃣ Нажмите «📋 Скопировать ссылку».\n4️⃣ В приложении нажмите «+» и выберите добавление из буфера обмена.\n5️⃣ Включите подключение большой кнопкой.\n\nЕсли что-то не получается: «🆘 Помощь».",
        "en": "📖 Instructions\n\n1️⃣ Install an app: tap its name below. If unsure, choose the first one.\n2️⃣ Return here: “🔑 My access”, then “🔗 Get link”.\n3️⃣ Tap “📋 Copy link”.\n4️⃣ In the app, tap “+” and add from the clipboard.\n5️⃣ Turn on the connection with the large button.\n\nIf something does not work: “🆘 Help”.",
    },
    "qr_failed": {"ru": "😕 QR-код сейчас не получился. Попробуйте ещё раз через минуту.", "en": "😕 The QR code could not be created. Please try again in a minute."},
    "qr_caption": {"ru": "📷 Ваш QR-код\n\nНа другом устройстве откройте приложение, выберите добавление по QR-коду и наведите камеру на этот экран.\n\nНе показывайте код другим: это ваш ключ.", "en": "📷 Your QR code\n\nOn another device, open the app, choose adding by QR code, and point the camera at this screen.\n\nDo not show the code to others: it is your key."},
    "guest_qr_caption": {"ru": "📷 QR-код для гостя\n\nРаботает до {expires_at}. Гость наводит на него камеру в приложении. Им можно поделиться: после этого срока он отключится сам.", "en": "📷 Guest QR code\n\nWorks until {expires_at}. The guest scans it in the app. You can share it; it turns off after this time."},
    "status_access": {"ru": "{status}\n{traffic}{hint}", "en": "{status}\n{traffic}{hint}"},
    "traffic_empty": {"ru": "📊 Данных о трафике пока нет", "en": "📊 No traffic data yet"},
    "traffic_known": {"ru": "📊 Использовано за всё время: {traffic} · обновлено {updated}", "en": "📊 Used all time: {traffic} · updated {updated}"},
    "diagnostics_provisioning": {"ru": "⏳ Доступ ещё готовится. Ничего делать не нужно, загляните чуть позже.", "en": "⏳ Access is still being prepared. You do not need to do anything; check again later."},
    "diagnostics_ready": {"ru": "✅ Доступ готов. Получите ссылку или QR-код и добавьте его в приложение.", "en": "✅ Access is ready. Get the link or QR code and add it to the app."},
    "diagnostics_suspended": {"ru": "⏸ Доступ приостановлен. Чтобы написать администратору, вернитесь в меню и нажмите «💬 Написать администратору».", "en": "Access is suspended. You can send a message to the administrator from the menu."},
    "diagnostics_other": {"ru": "😕 Сейчас доступ не работает. Попробуйте позже или откройте «🆘 Помощь».", "en": "Access is unavailable right now. Try later or open Help."},
    "diagnostics_menu": {
        "ru": "🔧 Что не так?\n\nВыберите, что похоже на вашу ситуацию. Бот подскажет, что сделать.",
        "en": "🔧 What is wrong?\n\nChoose the situation that looks like yours. The bot will suggest what to do.",
    },
    "diagnostics_import": {
        "ru": "🔧 Приложение не принимает ссылку\n\n1️⃣ Вернитесь в «🔑 Мой доступ» и снова нажмите «📋 Скопировать ссылку».\n2️⃣ Добавьте ссылку в приложение заново.\n\nНе помогло? Нажмите «💬 Написать в поддержку».",
        "en": "🔧 The app does not accept the link\n\n1️⃣ Return to “🔑 My access” and tap “📋 Copy link” again.\n2️⃣ Add the link to the app again.\n\nStill no luck? Tap “💬 Contact support”.",
    },
    "diagnostics_connection": {
        "ru": "🔧 Не подключается\n\n1️⃣ В приложении обновите список серверов.\n2️⃣ Выключите и снова включите подключение.\n3️⃣ Попробуйте другую сеть: например, мобильный интернет вместо Wi-Fi.\n\nНе помогло? Нажмите «💬 Написать в поддержку».",
        "en": "🔧 Will not connect\n\n1️⃣ Refresh the server list in the app.\n2️⃣ Turn the connection off and on again.\n3️⃣ Try another network, such as mobile data instead of Wi-Fi.\n\nStill no luck? Tap “💬 Contact support”.",
    },
    "diagnostics_routes": {
        "ru": "🔧 Работает, но не всё открывается\n\n1️⃣ В приложении обновите список серверов.\n2️⃣ Выключите и снова включите подключение.\n\nНе помогло? Нажмите «💬 Написать в поддержку» и укажите, что именно не открывается.",
        "en": "🔧 Works, but some things do not open\n\n1️⃣ Refresh the server list in the app.\n2️⃣ Turn the connection off and on again.\n\nStill no luck? Tap “💬 Contact support” and tell us what does not open.",
    },
    "guest_link_menu": {
        "ru": "👋 Ссылка для гостя\n\nВременная ссылка для другого человека, например друга. Гость получит тот же доступ, что и вы. Когда срок закончится, ссылка отключится сама.\n\nНовая ссылка для гостя сразу отключает прошлую.\n\nНа какое время её сделать?",
        "en": "👋 Guest link\n\nA temporary link for another person, such as a friend. The guest gets the same access as you. The link turns off when its time ends.\n\nA new guest link immediately turns off the previous one.\n\nHow long should it work?",
    },
    "guest_link_ready": {
        "ru": "👋 Ссылка для гостя готова\n\nРаботает до {expires_at}.\nНажмите «📋 Скопировать ссылку» и отправьте её человеку, которому доверяете.\n\nСсылка:\n{url}",
        "en": "👋 Guest link is ready\n\nWorks until {expires_at}.\nTap “📋 Copy link” and send it to someone you trust.\n\nLink:\n{url}",
    },
    "guest_link_revoked": {"ru": "✅ Ссылка для гостя отключена.", "en": "✅ The guest link was turned off."},
    "devices": {"ru": "📱 Мои устройства\n\nУ каждого устройства может быть своя ссылка. Если потеряете телефон, отключите только его, остальные продолжат работать.", "en": "📱 My devices\n\nEach device can have its own link. If you lose a phone, turn off only that link; the others will keep working."},
    "link_device_choice": {"ru": "🔗 Для какого устройства нужна ссылка?\n\nВыберите из списка. Подключаете что-то новое: нажмите «➕ Новое устройство».", "en": "🔗 Which device needs a link?\n\nChoose from the list. Connecting something new? Tap “➕ New device”."},
    "rotate_device_choice": {"ru": "🔄 Какую ссылку заменить?\n\nСтарая сразу перестанет работать. На том устройстве нужно будет добавить новую.", "en": "🔄 Which link should be replaced?\n\nThe old one stops working immediately. Add the new one on that device."},
    "rotation_device": {"ru": "🔄 Заменить ссылку?\n\nСтарая ссылка сразу перестанет работать. На этом устройстве связь пропадёт, пока вы не добавите новую.", "en": "🔄 Replace the link?\n\nThe old link stops working immediately. This device will be disconnected until you add the new one."},
    "rotation_all": {"ru": "🔄 Заменить все ссылки?\n\nВсе ваши ссылки сразу перестанут работать. Связь пропадёт на всех устройствах, пока вы не добавите новые.", "en": "🔄 Replace all links?\n\nAll your links stop working immediately. Every device will be disconnected until you add the new ones."},
    "device_rename_prompt": {"ru": "✏️ Напишите новое название устройства, например «Телефон мамы». До 80 символов.", "en": "Send a new device name. Up to 80 characters."},
    "device_rename_invalid": {"ru": "😕 Название не подошло. Нужно от 1 до 80 символов.", "en": "The name was not accepted. Use 1 to 80 characters."},
    "device_actions": {"ru": "📱 {label}\n\nЧто сделать с этим устройством?", "en": "📱 {label}\n\nWhat would you like to do with this device?"},
    "device_revoke_confirm": {"ru": "🚫 Отключить ссылку этого устройства?\n\nОно сразу потеряет связь. Другие устройства продолжат работать.", "en": "🚫 Turn off this device link?\n\nIt will lose connection immediately. Other devices will keep working."},
    "device_revoked": {"ru": "✅ Ссылка отключена. Это устройство больше не подключится.", "en": "✅ The link was turned off. This device will not connect again."},
    "service_status_normal": {"ru": "📡 Всё работает, сбоев сейчас нет.", "en": "📡 Everything is working; there are no issues right now."},
    "service_status_notice": {"ru": "📡 Важное сообщение:\n\n{body}", "en": "📡 Important message:\n\n{body}"},
    "quality_menu": {"ru": "⭐ Как сейчас работает связь?", "en": "⭐ How is the connection working right now?"},
    "quality_platform": {"ru": "На каком устройстве вы это заметили?", "en": "Which device did you notice this on?"},
    "quality_sent": {"ru": "🙏 Спасибо! Мы получили вашу оценку.", "en": "🙏 Thank you! We received your rating."},
    "rotation": {"ru": "🔄 Заменить ссылку?\n\nСтарая ссылка сразу перестанет работать. На этом устройстве связь пропадёт, пока вы не добавите новую.", "en": "🔄 Replace the link?\n\nThe old link stops working immediately. This device will be disconnected until you add the new one."},
    "appeal_prompt": {"ru": "💬 Напишите одним сообщением, почему доступ нужно вернуть. Администратор прочитает и примет решение.", "en": "Write one message explaining why access should be restored. It will be sent to the administrator for review."},
    "support_prompt": {"ru": "💬 Тема: {label}\n\nТеперь одним сообщением опишите, что случилось. Пока вы его не отправите, мы ничего не получим. До 1000 символов.", "en": "Topic: {label}.\n\nThe request has not been sent yet. Send one message describing the issue; it will then go to the administrator. Maximum 1000 characters."},
    "support_open": {"ru": "⏳ Ваш прошлый вопрос ещё у нас. Дождитесь ответа, и можно будет написать снова.", "en": "You already have an open support request. Please wait for the administrator’s response."},
    "support_unavailable": {"ru": "😕 Сейчас написать в поддержку нельзя. Попробуйте позже.", "en": "A new support request is not available yet. Please try later."},
    "support_invalid": {"ru": "😕 Сообщение не подошло. Напишите текст не длиннее 1000 символов.", "en": "The request could not be accepted. Make sure the message is not empty and is no longer than 1000 characters."},
    "support_sent": {"ru": "✅ Сообщение отправлено. Ответ придёт сюда, в бот.", "en": "Your request was accepted and sent to the administrator."},
    "appeal_invalid": {"ru": "😕 Сообщение не подошло. Попробуйте покороче.", "en": "The message could not be accepted. Please try a shorter one."},
    "appeal_sent": {"ru": "✅ Сообщение отправлено администратору.", "en": "Your message was accepted and sent to the administrator."},
    "introduction_invalid": {"ru": "😕 Сообщение не подошло. Напишите, кто вы и зачем вам доступ, и сделайте текст покороче.", "en": "Write a non-empty message about yourself and your reason for contacting us, within the allowed length."},
    "application_sent": {"ru": "✅ Спасибо! Заявка отправлена. Ответ придёт сюда, в бот.", "en": "Thank you. Your request was sent and is awaiting administrator review."},
    "introduction_saved": {"ru": "✅ Спасибо! Заявка всё ещё у администратора. Ответ придёт сюда, в бот.", "en": "Thank you. The request is still awaiting review."},
    "start_first": {"ru": "Чтобы начать, отправьте /start.", "en": "Send /start to begin."},
    "language_menu": {"ru": "🌐 Выберите язык", "en": "🌐 Choose a language"},
    "language_saved": {"ru": "✅ Язык: русский.", "en": "Interface language: English."},
    "link_preparing": {"ru": "⏳ Ссылка ещё готовится. Ничего делать не нужно, загляните чуть позже.", "en": "⏳ The link is still being prepared. You do not need to do anything; check again later."},
    "preferences": {"ru": "🔔 Уведомления\n\nБот может сам писать вам о важном. Выберите, что оставить.\n\nСообщения от бота: {background}\nСкоро закончится срок: {expiry}\nИспользовано много трафика: {traffic}\nПредупреждать о трафике при: {traffic_thresholds}\n\nОтветы на ваши нажатия приходят всегда.", "en": "Background notifications: {background}.\nExpiry reminders: {expiry}.\nTraffic reminders: {traffic}.\nTraffic thresholds: {traffic_thresholds}.\n\nReplies to your commands are always delivered."},
    "traffic_thresholds": {"ru": "📊 Когда предупреждать о трафике?\n\nМожно выбрать несколько вариантов.", "en": "Choose traffic reminder thresholds. You can select more than one."},
    "preference_background_action": {"ru": "{action} сообщения от бота", "en": "{action} background notifications"},
    "preference_expiry_action": {"ru": "{action} напоминания о сроке", "en": "{action} expiry reminders"},
    "preference_traffic_action": {"ru": "{action} напоминания о трафике", "en": "{action} traffic reminders"},
    "status_active": {"ru": "активен", "en": "active"},
    "status_suspended": {"ru": "приостановлен", "en": "suspended"},
    "status_suspend_partial": {"ru": "частично приостановлен", "en": "partially suspended"},
    "status_provisioning": {"ru": "готовится", "en": "being prepared"},
    "status_unknown": {"ru": "недоступен", "en": "unavailable"},
    "help": {"ru": "🆘 Помощь\n\nЧто нужно?\n📖 Ещё не подключались: пошаговая инструкция.\n🔧 Подключались, но не работает: бот подскажет, что проверить.\n📡 Хотите узнать, нет ли сбоя: проверьте сервис.\n⭐ Хотите рассказать, как работает связь: оцените её.\n💬 Не помогло: напишите нам.", "en": "🆘 Help\n\nWhat do you need?\n📖 Not connected yet: follow the step-by-step guide.\n🔧 Connected, but it does not work: the bot will suggest what to check.\n📡 Want to know if there is an outage: check the service.\n⭐ Want to tell us how the connection works: rate it.\n💬 Still no help: write to us."},
    "support_menu": {"ru": "💬 Поддержка\n\nО чём ваш вопрос? Выберите тему, затем одним сообщением опишите, что случилось.", "en": "Support\n\nChoose a topic, then send one message describing the issue."},
    "qr_deleted": {"ru": "✅ QR-код удалён.", "en": "✅ The QR code was deleted."},
    "qr_too_old": {"ru": "Telegram не даёт боту удалять сообщения старше 48 часов. Удалите этот QR-код вручную: зажмите сообщение и выберите «Удалить».", "en": "Telegram does not let bots delete messages older than 48 hours. Please delete this QR code manually: press and hold the message and choose Delete."},
    "qr_unknown": {"ru": "😕 Не нашли этот QR-код. Если он нужен, откройте его ещё раз.", "en": "The QR message could not be identified. Open a new QR code if needed."},
}

_BUTTONS: dict[str, dict[str, str]] = {
    "close": {"ru": "✖️ Закрыть", "en": "✖️ Close"},
    "get_access": {"ru": "🔑 Мой доступ", "en": "🔑 My access"},
    "get_link": {"ru": "🔗 Получить ссылку", "en": "🔗 Get link"},
    "show_link": {"ru": "🔗 Показать ссылку", "en": "🔗 Show link"},
    "show_qr": {"ru": "📷 Показать QR-код", "en": "📷 Show QR code"},
    "check_ready": {"ru": "⏳ Проверить готовность", "en": "⏳ Check readiness"},
    "rotate": {"ru": "🔄 Заменить ссылку", "en": "🔄 Replace link"},
    "guest_link": {"ru": "👋 Ссылка для гостя", "en": "👋 Guest link"},
    "devices": {"ru": "📱 Мои устройства", "en": "📱 My devices"},
    "my_links": {"ru": "📱 Мои устройства", "en": "📱 My devices"},
    "status": {"ru": "📡 Работает ли сервис", "en": "📡 Is the service working"},
    "quality": {"ru": "⭐ Оценить связь", "en": "⭐ Rate the connection"},
    "diagnostics": {"ru": "🔧 Не работает? Разберёмся", "en": "🔧 Not working? Let's fix it"},
    "traffic_thresholds": {"ru": "📊 Когда предупреждать о трафике", "en": "📊 When to warn about traffic"},
    "revoke": {"ru": "🚫 Отключить ссылку", "en": "🚫 Turn off link"},
    "rename": {"ru": "✏️ Переименовать", "en": "✏️ Rename"},
    "rename_symbol": {"ru": "✏️", "en": "✏️"},
    "new_device": {"ru": "➕ Новое устройство", "en": "➕ New device"},
    "rotate_all": {"ru": "🔄 Заменить все ссылки", "en": "🔄 Replace all links"},
    "confirm": {"ru": "✅ Да, подтверждаю", "en": "✅ Yes, confirm"},
    "menu": {"ru": "⬅️ Назад", "en": "⬅️ Back"},
    "connection": {"ru": "📖 Как подключить", "en": "📖 How to connect"},
    "notifications": {"ru": "🔔 Уведомления", "en": "🔔 Notifications"},
    "help": {"ru": "🆘 Помощь", "en": "🆘 Help"},
    "support": {"ru": "💬 Написать в поддержку", "en": "💬 Contact support"},
    "language": {"ru": "🌐 Язык", "en": "🌐 Language"},
    "delete_qr": {"ru": "🗑 Удалить QR-код", "en": "🗑 Delete QR code"},
    "repeat_guide": {"ru": "🔄 Показать инструкцию ещё раз", "en": "🔄 Show the guide again"},
    "back_help": {"ru": "⬅️ Назад", "en": "⬅️ Back"},
    "write_admin": {"ru": "💬 Написать администратору", "en": "💬 Message administrator"},
    "copy_link": {"ru": "📋 Скопировать ссылку", "en": "📋 Copy link"},
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
