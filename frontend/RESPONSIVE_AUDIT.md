# Responsive Audit — multiserversubgen v3.1

Дата: 2026-05-30 | Скриншоты: 10 разрешений (426–3840px)

---

## Сводка

| Ширина | Статус | Критич | Важных | Мелких |
|--------|--------|--------|--------|--------|
| 426px  | 🔴 Сломан | 2 | 2 | 1 |
| 640px  | 🔴 Сломан | 1 | 2 | 1 |
| 854px  | 🟡 Проблемы | 0 | 2 | 1 |
| 960px  | 🟡 Проблемы | 0 | 2 | 1 |
| 1280px | 🟡 Проблемы | 0 | 1 | 0 |
| 1366px | ✅ OK | 0 | 0 | 0 |
| 1440px | ✅ OK | 0 | 0 | 0 |
| 1600px | ✅ OK | 0 | 0 | 0 |
| 1920px | ✅ OK | 0 | 0 | 0 |
| 2560px | ✅ OK | 0 | 0 | 0 |
| 3840px | 🟡 Мелко | 0 | 0 | 2 |

---

## 🔴 КРИТИЧЕСКИЕ

### BUG-01 — Контент сдвинут вправо на ~200px (426px, 640px)
**Что видно:** Левая половина экрана чёрная, контент начинается с середины.  
**Почему:** `html { overflow-x: hidden }` скрывает скролл но не убирает сдвиг. Причина — `.app-main` получает `margin-left: 272px` от базового правила и мобильный override (`margin-left: 0`) не срабатывает. Возможно есть inline `style` в App.tsx.  
**Файлы:** `src/App.css`, `src/App.tsx`  
**Фикс:**
```css
@media (max-width: 767px) {
  .app-main {
    margin-left: 0 !important;
    width: 100vw !important;
    max-width: 100vw !important;
  }
  .app-layout {
    overflow-x: hidden;
    max-width: 100vw;
  }
}
```
Проверить App.tsx — нет ли `<div style={{ marginLeft: ... }}>` на `.app-main`.

---

### BUG-02 — KPI label тексты обрезаются (426px)
**Что видно:** "ЗАРЕГИСТРИРОВ..." "ДОСТУПНО СЕЙЧ..." "ОНЛАЙН КЛИЕНТ..."  
**Почему:** UPPERCASE + letter-spacing лейблы слишком длинные для узкой карточки.  
**Файлы:** `src/App.css`, `src/i18n/locales/ru.json`  
**Фикс — сократить тексты в локалях:**
- `"ЗАРЕГИСТРИРОВАНО УЗЛОВ"` → `"УЗЛОВ"`
- `"ДОСТУПНО СЕЙЧАС"` → `"ОНЛАЙН"`
- `"ПРОБЛЕМЫ АВТОРИЗАЦИИ"` → `"АВТОРИЗАЦИЯ"`
- `"ОФФЛАЙН УЗЛЫ"` → `"ОФФЛАЙН"`
- `"ОНЛАЙН КЛИЕНТЫ"` → `"КЛИЕНТОВ"`

---

## 🟡 ВАЖНЫЕ

### BUG-03 — "Fleet Overview" показывается как "eet Overview" (854px, 960px)
**Что видно:** Первые 2 символа "Fl" спрятаны за сайдбаром.  
**Почему:** padding `16px 14px` при сайдбаре 220px — мало. Заголовок начинается слишком близко к краю сайдбара.  
**Файл:** `src/App.css` — `@media (min-width: 768px) and (max-width: 1023px)`  
**Фикс:**
```css
@media (min-width: 768px) and (max-width: 1023px) {
  .app-content { padding: 16px 16px 16px 24px; }
}
```

---

### BUG-04 — Fleet Overview карточки переносятся некрасиво (960px: 4+2, 1280px: 5+1)
**Что видно:**
- 960px: 4 карточки в ряду + 2 внизу
- 1280px: 5 карточек + TOTAL TRAFFIC один в ряду

**Почему:** `auto-fit minmax(160px, 1fr)` — карточки перетекают свободно.  
**Файл:** `src/App.css` — `.kpi-grid`  
**Фикс — фиксированные колонки по брейкпоинту:**
```css
/* Планшет: 2 ряда × 3 колонки */
@media (min-width: 768px) and (max-width: 1279px) {
  .kpi-grid { grid-template-columns: repeat(3, 1fr); }
}
/* Десктоп: 1 ряд × 6 колонок */
@media (min-width: 1280px) {
  .kpi-grid { grid-template-columns: repeat(6, 1fr); }
}
/* Мобиль: 1 ряд × 2 колонки */
@media (max-width: 767px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}
```

---

### BUG-05 — Header stat labels переносятся в 2 строки (960px)
**Что видно:** "ПРОБЛЕМЫ АВТОРИЗАЦИИ" в 2 строки — карточки разной высоты.  
**Файл:** `src/App.css` — `.app-shell-stat__label`  
**Фикс:**
```css
.app-shell-stat__label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
```
Плюс BUG-02 сокращает тексты — убивает проблему в корне.

---

### BUG-06 — Topbar кнопка "Включить push в браузере" обрезается (426–640px)
**Что видно:** Кнопка не помещается, текст обрезан.  
**Файл:** `src/App.tsx` или `src/App.css`  
**Фикс:**
```css
@media (max-width: 640px) {
  /* Скрыть текст, оставить только иконку */
  .app-topbar-push-text { display: none; }
  /* Или скрыть кнопку полностью */
  .app-topbar-push-btn { display: none; }
}
```

---

## 🟢 МЕЛКИЕ УЛУЧШЕНИЯ

### BUG-07 — 3840px: всё слишком мелкое для 4K
**Что видно:** Сайдбар 272px, текст, карточки — всё крошечное на 4K экране.  
**Файл:** `src/App.css`  
**Фикс:**
```css
@media (min-width: 2560px) {
  html { font-size: 18px; }
  .sidebar { width: 320px; min-width: 320px; }
  .app-main { margin-left: 320px; }
  body.style-preset-3 .app-main { margin-left: 320px; }
}
@media (min-width: 3200px) {
  html { font-size: 20px; }
  .sidebar { width: 360px; min-width: 360px; }
  .app-main { margin-left: 360px; }
}
```

---

## Порядок фиксов (спринты)

### Спринт 1 — Мобиль ✅
- [x] **BUG-01** — Корень: `body.style-preset-3 .app-main { margin-left: 248px }` имеет выше специфичность. Фикс: добавили `body.style-preset-3 .app-main { margin-left: 0 !important }` в мобильный breakpoint + `overflow-x: hidden` на `.app-layout`
- [x] **BUG-02** — Сократили label тексты в ru.json + en.json: "Зарегистрировано узлов"→"Узлов", "Проблемы авторизации"→"Авторизация" и т.д.
- [x] **BUG-06** — Класс `topbar-push-btn` на кнопке + `display: none` на <640px

### Спринт 2 — Планшет/Ноутбук ✅
- [x] **BUG-03** — padding 768–1023px: `16px 16px 16px 24px`
- [x] **BUG-04** — kpi-grid: 2col mobile / 3col tablet / 6col desktop
- [x] **BUG-05** — `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` на `.app-shell-stat__label`

### Спринт 3 — 4K ✅
- [x] **BUG-07** — `@media (min-width: 2560px)` → `font-size: 18px`, sidebar 320px; `@media (min-width: 3200px)` → `font-size: 20px`, sidebar 360px

---

## Не трогать — работает хорошо

- ✅ 1366–1920px — дашборд чистый и профессиональный
- ✅ ЗАРЕГИСТРИРОВАННЫЙ ПАРК: VERSION + ДОСТУП видны на 1920px+
- ✅ TOP BY TRAFFIC секция чистая на всех десктоп разрешениях
- ✅ Fleet Overview иконки и числа красивые
- ✅ 2560px: контент max-width центрируется правильно
- ✅ Сайдбар масштабируется по брейкпоинтам (220→260→272px)
