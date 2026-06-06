# Dashboard Figma Migration

Дата фиксации: `2026-06-04`

Этот документ фиксирует текущее состояние главного экрана `Dashboard` после логина и целевую donor/Figma-схему `Variant4`.

## Source Of Truth

- Текущая архитектурная схема dashboard:
  [DASHBOARD-CURRENT-ARCHITECTURE-2026-06-04.html](/E:/GitHub/repos/multiserversubgen/docs/DASHBOARD-CURRENT-ARCHITECTURE-2026-06-04.html)
- Целевая donor/Figma-схема `Variant4`:
  [DASHBOARD-TARGET-FIGMA-VARIANT4-2026-06-04.html](/E:/GitHub/repos/multiserversubgen/docs/DASHBOARD-TARGET-FIGMA-VARIANT4-2026-06-04.html)
- Сравнительная карта `current -> target -> gap`:
  [DASHBOARD-CURRENT-VS-FIGMA-VARIANT4-2026-06-04.html](/E:/GitHub/repos/multiserversubgen/docs/DASHBOARD-CURRENT-VS-FIGMA-VARIANT4-2026-06-04.html)

## Migration Direction

Наша цель: привести текущий `Dashboard` к donor/Figma `Variant4`, не переделывая пока остальные вкладки приложения.

Это означает:

- сохраняем scope только на `Dashboard` после логина;
- продолжаем `shell-first migration`;
- не трогаем остальные табы, кроме минимальной совместимости;
- используем donor `Variant4` как целевой visual/structural reference;
- не тащим donor-код 1-в-1, а переносим композицию и поведение в текущую архитектуру проекта.

## Current State

Сейчас `Dashboard` уже разделяется на два слоя:

1. новый dashboard-shell
2. legacy-внутренности, вставленные в новый shell

Что уже migrated в новом стиле:

- `frontend/src/App.tsx` в части `dashboard`-композиции
- `frontend/src/components/DashboardSummary.tsx`
- `frontend/src/components/RegisteredFleetPanel.tsx`
- `frontend/src/App.css` в dashboard-scoped блоках

Что пока остаётся legacy inside new shell:

- `frontend/src/components/ServerStatus.tsx`
- `frontend/src/components/NodeManager.tsx`

## Gap Map

Что уже близко к donor `Variant4`:

- общий dashboard-shell в `App.tsx`
- верхний `DashboardSummary`
- `Sidebar` и `topbar` в dashboard-only режиме
- `RegisteredFleetPanel` как command rail

Что находится в переходной стадии:

- lower lane headers и общая command-center рамка
- degraded / error / empty states в нижней части экрана
- плотность `NodeManager` в dashboard-only режиме

Что остаётся главным остаточным долгом:

- внутренний ритм карточек `ServerStatus`
- финальная donor-чистота `NodeManager`
- desktop-balance между `summary / lower lanes / fleet rail`

## Target State

Целевой donor `Variant4` устроен как отдельная command-center ветка:

- отдельный root shell
- свой sidebar/topbar chrome
- dashboard-local mission-control header
- fleet overview как центральный блок
- встроенный `Registered Fleet` rail
- lower dashboard content как часть одной command-center композиции

Для нашего проекта это не означает полный fork интерфейса. Это означает, что текущий `Dashboard` должен постепенно принять эту структуру внутри текущего приложения.

## Practical Rule

Пока идёт миграция:

- `DashboardSummary` и `RegisteredFleetPanel` считаются основой нового направления;
- `ServerStatus` и `NodeManager` считаются временно допустимыми legacy-подсистемами внутри нового shell;
- все новые dashboard-правки должны сверяться с donor `Variant4`, а не с legacy layout;
- любые крупные переделки вне `Dashboard` откладываются.

## Next Work

Следующий этап миграции:

1. продолжать visual refinement `Dashboard`;
2. упростить и адаптировать `ServerStatus` для dashboard-only view;
3. упростить и адаптировать `NodeManager` для dashboard-only view;
4. выровнять пропорции `summary / lower lanes / fleet rail` ближе к `Variant4`.
