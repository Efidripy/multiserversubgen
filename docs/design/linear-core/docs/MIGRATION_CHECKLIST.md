# Migration checklist

## Visual

- [ ] Используются только Linear Core tokens.
- [ ] Нет Ember/Vision цветов и декоративных градиентов.
- [ ] Все соседние карточки выровнены по высоте.
- [ ] Все контролы в строке одинаковой высоты.
- [ ] Topbar содержит только icon + section title слева.
- [ ] Main navigation содержит ровно восемь продуктовых разделов.
- [ ] Registered fleet отсутствует в main nav.

## Functional

- [ ] Sidebar expanded/collapsed работает на desktop и mobile.
- [ ] Search/command palette работает.
- [ ] Notifications/profile dropdown работают.
- [ ] Filters реально влияют на список либо явно помечены mock-state.
- [ ] Modal cancel не вызывает success.
- [ ] Drawers закрываются overlay/close control.
- [ ] Bulk selection и actions доступны с клавиатуры.
- [ ] Node/list/table переключения сохраняют состояние.

## Screens

- [ ] Dashboard
- [ ] Inbound
- [ ] Clients
- [ ] Statistics
- [ ] Monitoring
- [ ] Backups
- [ ] Subscriptions
- [ ] Telegram

## Responsive

- [ ] 1440 px desktop
- [ ] 1024 px tablet
- [ ] 768 px narrow tablet
- [ ] 390 px mobile
- [ ] Нет перекрытия footer/sidebar/content.
- [ ] Широкие таблицы прокручиваются, а не сжимаются до нечитаемости.

## Quality

- [ ] Build/typecheck/lint проходят.
- [ ] Нет dead buttons.
- [ ] Нет layout shift при переключении данных и состояний.
- [ ] Focus-visible присутствует.
- [ ] Тексты и значения не обрезаны без tooltip.
