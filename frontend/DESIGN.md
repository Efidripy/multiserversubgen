# Design System — multiserversubgen

> Version 2.0 · Dark-first · CSS custom properties

## Principles

1. **Data-dense, not cluttered** — operators read dozens of rows. Every pixel counts.
2. **Purposeful color** — cyan (`--accent`) = primary action only. Purple (`--accent-2`) = secondary. Never decorative.
3. **Predictable rhythm** — 4px grid. Spacing not a multiple of 4 is a violation.
4. **Drawer over modal** — editing something? Drawer from right. Never block the content being edited.
5. **CSS vars over inline styles** — theming is free, refactoring is painless.

---

## Color Tokens

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--accent` | `#0dcfba` | `#0891b2` | Primary CTA, active nav, focus rings |
| `--accent-2` | `#a78bfa` | `#7c3aed` | Info, reset-traffic, secondary |
| `--success` | `#0dbc8f` | `#0d9960` | Active, enable, positive |
| `--warning` | `#f59e0b` | `#c47b0a` | Expiring, freeze, depleted |
| `--danger` | `#ef4444` | `#dc2626` | Delete, expired, critical |
| `--bg-primary` | `#0b1120` | `#f0f4f9` | Page background |
| `--bg-secondary` | `#111a2e` | `#ffffff` | Cards, panels |
| `--bg-tertiary` | `#182035` | `#e8eef6` | Inputs, row hover |
| `--border-color` | `#1e3048` | `#c8d8ea` | All borders |
| `--text-primary` | `#e8f1fb` | `#0f1f33` | Main content |
| `--text-secondary` | `#7a93ad` | `#4a607a` | Labels, hints |
| `--text-tertiary` | `#4a6070` | `#7a93ad` | Disabled, placeholder |

---

## Spacing (4px grid)

```
4px  → micro gap, icon spacing
8px  → button padding, badge
12px → input padding
16px → standard gap
20px → panel padding
24px → drawer header, large gaps
32px → page section spacing
```

❌ Never use: 3px, 5px, 7px, 9px, 11px, 14px, 22px, 28px

---

## Border Radius

| Name | Value | Usage |
|------|-------|-------|
| `sm` | 6px | Mini chips |
| `md` | 8px | Buttons, inputs |
| `lg` | 12px | Modals |
| `xl` | 14px | Cards, server cards |
| `2xl` | 16px | Drawers |
| `full` | 9999px | Pills, badges |

❌ Never use: 7px, 9px, 10px, 18px (unless Bootstrap override)

---

## Typography

| Scale | Size | LH | Usage |
|-------|------|----|-------|
| `xs` | 0.68rem | 1.4 | Captions, labels |
| `sm` | 0.75rem | 1.45 | Table headers |
| `base` | 0.84rem | 1.5 | Body, inputs |
| `md` | 0.95rem | 1.45 | Card titles |
| `lg` | 1.1rem | 1.3 | Section headers |
| `xl` | 1.3rem | 1.2 | Page titles |

- **UI:** IBM Plex Sans
- **Headings:** Sora
- **Code/UUIDs:** JetBrains Mono

---

## Button Classes

```css
.btn-accent           /* cyan fill — primary CTA */
.btn-success-fill     /* green fill */
.btn-danger-fill      /* red fill */
.btn-warning-fill     /* orange fill */
.btn-info-fill        /* purple fill */
.btn-ghost-accent     /* cyan ghost */
.btn-ghost-warning    /* orange ghost */
.btn-ghost-danger     /* red ghost */
.btn-neutral          /* flat, no color */
.row-action-btn       /* 26×26 icon button in table rows */
```

## Status Components

```css
.status-badge--active    /* ● green pill */
.status-badge--disabled  /* ○ grey pill */
.status-badge--expired   /* ⏱ red pill */
.status-badge--depleted  /* ⬇ orange pill */

.expiry-chip--ok         /* muted days label */
.expiry-chip--soon       /* orange ≤7d */
.expiry-chip--urgent     /* red ≤3d */
.expiry-chip--expired    /* red expired */
```

---

## Anti-patterns

```tsx
// ❌ Inline JS color
style={{ backgroundColor: colors.accent }}
// ✅ Class
className="btn-accent"

// ❌ Hardcoded hex in JSX
style={{ color: '#22d3ee' }}
// ✅ CSS var
style={{ color: 'var(--accent)' }}

// ❌ Bootstrap modal for edit forms
<div className="modal d-block">
// ✅ Drawer
<div className="drawer"><div className="drawer__panel">

// ❌ Spinner as page load state
<div className="spinner-border" />
// ✅ Skeleton table
<table className="skeleton-table">
```
