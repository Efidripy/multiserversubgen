# Component recipes

## Button

- Primary: light neutral fill, dark text; только одно primary-действие на локальную область.
- Secondary: transparent/dark fill + border.
- Danger: rose text/border, слабая tinted-заливка.
- Icon button: квадрат, тот же height, tooltip обязателен.

## Inputs / Select / Segmented control

Все контролы в строке строго одинаковой внешней высоты. Внутренние padding и border входят в height через `box-sizing: border-box`.

## Table

- Sticky header при длинном списке.
- Строка 36–40 px desktop.
- Checkbox слева, действия справа.
- Row hover меняет surface, не размер.
- Bulk selection показывает фиксированную action bar, не сдвигая таблицу.

## Metric card

Иконка, label, value, supporting text, trend. Карточки одной группы имеют одинаковую высоту и grid-auto-rows.

## Server node card

Обязательно: name/version/IP/status, CPU/RAM/Disk с абсолютными значениями, NET/LOAD/TCP RTT, uptime/swap/last seen, Core version, быстрые действия.

## Traffic chart

Сверху: выбор node, comparison, range в одной строке одинаковой высоты. Затем график. Под временной осью — компактная сводка current/previous + legend. Сравнительная линия пунктирная.

## User traffic ranking

Top-10, текущий и прошлый период наложенными горизонтальными полосами, value и delta. Без лишней CTA-кнопки.

## Modal

Overlay + centered surface. Header, body, footer. Escape/overlay закрывают. Cancel не вызывает success. Для сложных форм разрешён stepper.

## Drawer

Справа, 320–420 px. Overlay, close handle, tabs внутри. Выбор узла из fleet закрывает fleet и открывает details drawer.

## Registered fleet

Не пункт основного меню. Открывается правой edge-handle. Внутри список узлов с URL, online/XUI/RW, быстрыми действиями и общей проверкой.

## Loading / Empty / Error

Каждое состояние сохраняет минимальную высоту блока. Skeleton не должен менять сетку. Error показывает причину и retry. Empty содержит короткое объяснение и одно действие.
