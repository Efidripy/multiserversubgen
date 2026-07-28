# Frontend UI Improvement Plan

Оценка готовности: **6/10** → цель **9/10** (уровень Remnawave)

---

## ✅ СДЕЛАНО

### Design Foundation
- [x] CSS custom properties система — `--accent`, `--bg-*`, `--text-*`, `--border-color`
- [x] Типографика: IBM Plex Sans + Sora
- [x] Dark theme palette: bg.primary `#0b1120`, bg.secondary `#111a2e`, bg.tertiary `#182035`
- [x] Radial gradient фон с depth
- [x] `.server-grid` CSS — overflow fix, кнопки не выезжают за границы карточек

### Component Library (App.css)
- [x] `.btn-accent`, `.btn-success-fill`, `.btn-danger-fill`, `.btn-warning-fill`, `.btn-info-fill`
- [x] `.btn-ghost-accent/success/warning/danger/info`
- [x] `.btn-neutral`
- [x] `.icon-badge` (6 вариантов + `--rounded`, `--lg`)
- [x] `.kpi-card`, `.kpi-grid`, `.trend-chip`, `.section-title`
- [x] `.seg-tab`, `.seg-tab--sm`, `.seg-tab--xs`
- [x] `.xray-icon-btn` + `--danger/warning/accent`
- [x] `.usage-badge`, `.progress-track`, `.progress-track__fill`
- [x] `.skeleton` + `@keyframes shimmer` — CSS система (не применена к компонентам)
- [x] `.drawer` full system — panel/header/body/footer/close
- [x] `.selection-bar`, `.pg-strip`, `.form-select-inline`
- [x] `.alert-danger/warning/info/success` через CSS vars
- [x] `.text-accent`, `.text-muted-2`
- [x] `body:has(.modal.d-block)` scroll lock
- [x] Bootstrap overrides: `.card`, `.form-control`, `.form-select`, `.table`, `.badge`
- [x] `.panel-block__title` / `.panel-block__hint` дефолтные цвета

### Components — Нормализованы
- [x] **DashboardSummary.tsx** — KPI cards, icon-badge, progress-track
- [x] **Sidebar.tsx** — nav groups, CSS классы
- [x] **ClientEditModal.tsx** → drawer
- [x] **InboundEditModal.tsx** → drawer + Form/Raw tabs
- [x] **ServerStatus.tsx** — xray-icon-btn, seg-tab, btn-ghost-*
- [x] **NodeManager.tsx** — seg-tab, btn-ghost-*
- [x] **Toast.tsx** — icon badge circle
- [x] **EmptyState.tsx** — icon-badge, CSS классы, useTheme убран
- [x] **ClientManager.tsx** — ПОЛНАЯ нормализация, useTheme удалён, все colors.* → CSS vars
- [x] **InboundManager.tsx** — useTheme удалён, colors.* → CSS vars

---

## 🔴 КРИТИЧНО (первый приоритет)

### 1. Loading States — Skeleton ✅
- [x] ClientManager таблица — skeleton rows вместо спиннера
- [x] InboundManager таблица — skeleton rows
- [x] NodeManager — не нужен (нет page-level loading state)

### 2. InboundManager — 4 модала → drawer ✅
- [x] "Clone Inbound" modal → drawer
- [x] "Add Inbound" modal → wide drawer (580px)
- [x] "Import JSON" modal → wide drawer
- [x] "Config View" JSON modal → wide drawer

### 3. Таблицы — визуальная доработка ✅
- [x] Status column → `.status-badge` (active/disabled/expired/depleted)
- [x] Action buttons → `.row-action-btn` компактный стиль (26px высота)
- [x] Expiry column → `.expiry-chip` с цветом по urgency (ok/soon/urgent/expired/never)
- [x] Row expand → fade-in анимация

---

## 🟡 ВАЖНО (второй приоритет)

### 4. Компоненты — убрать legacy inline styles ✅
- [x] **MonitoringDashboard.tsx** — colors.* → CSS vars (stylePreset/theme оставлен)
- [x] **TrafficStats.tsx** — colors.* → CSS vars (stylePreset оставлен)
- [x] **BackupManager.tsx** — colors.* → CSS vars, useTheme удалён
- [x] **SubscriptionManager.tsx** — colors.* → CSS vars, useTheme удалён
- [x] **AddClientMultiServer.tsx** — colors.* → CSS vars, useTheme удалён
- [x] **PerformanceMetricsDashboard.tsx** — colors.* → CSS vars, useTheme удалён

### 5. Visual Breathing Room ✅
- [x] `line-height` таблиц → 1.45 (dense: 1.35)
- [x] `padding` table cells → `10px` top/bottom, `vertical-align: middle`
- [x] `gap` panel-grid → 16px
- [x] Section headers в карточках — bottom border separator
- [x] app-content padding увеличен на широких экранах (≥1200px → 28px 36px)

### 6. Color Balance ✅
- [x] `--accent-2: #a78bfa` в :root — purple для вторичных действий
- [x] `.btn-info-fill` → использует `--accent-2` вместо синего
- [x] `.btn-ghost-info` → `--accent-2`
- [x] `.btn-ghost-accent-2`, `.row-action-btn--accent-2` — новые варианты

---

## 🟢 POLISH (финальный этап)

### 7. Mobile ✅
- [x] Sidebar collapse < 768px — уже работал, проверен
- [x] `.col-hide-mobile` колонки — уже были, проверены
- [x] `.row-action-btn` touch targets → 32px на мобиле
- [x] `.status-badge` slightly bigger на мобиле
- [x] Drawer full-width на < 520px покрывает `--wide` вариант

### 8. Micro-interactions ✅
- [x] Copy email кнопка — `copiedKey` state, ✓ на 1.5s, потом возвращается 📋
- [x] `copyWithFeedback` helper + toast комбо
- [ ] Drawer swipe-to-close — требует touch events JS (пропускаем)

### 9. Accessibility ✅
- [x] Focus rings: `.row-action-btn`, `.status-badge`, `.expiry-chip`, `.drawer__close`
- [x] `@media (prefers-reduced-motion)` — отключает анимации
- [x] `aria-label` на всех row-action-btn в ClientManager
- [x] `aria-label="Close"` на всех drawer__close (4 модала + 2 edit modal)

### 10. Light Theme ✅
- [x] `.selection-bar` light mode override
- [x] `.kpi-card` light mode — без glow анимации, белый bg
- [x] `.skeleton-cell` light mode — светлый shimmer

---

## Метрики

| Роль | Было | Сейчас | Цель |
|------|------|--------|------|
| Программист | 5/10 | 7/10 | 9/10 |
| Дизайнер | 4/10 | 6.5/10 | 9/10 |
| Пользователь | 5/10 | 6/10 | 8.5/10 |
| Художник | 4/10 | 5/10 | 8/10 |
| **Итого** | **4.5/10** | **6/10** | **8.6/10** |
