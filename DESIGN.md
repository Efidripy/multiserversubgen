# Design System — MultiServer Subscription Manager

## Product Context
- **What this is:** A professional VPN panel manager for 3x-ui servers — multi-node client/inbound/traffic management dashboard
- **Who it's for:** VPN service operators managing multiple 3x-ui panel servers and hundreds/thousands of clients
- **Space/industry:** Network infrastructure management tooling
- **Project type:** Data-dense internal web app / operations dashboard

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian — precision-first, data-dense, information over decoration
- **Decoration level:** Intentional — subtle depth and ambient color, never decorative for its own sake
- **Mood:** The tool should feel like a professional operator's panel: fast, trustworthy, scannable at a glance. Never "playful" or "corporate SaaS". More Bloomberg Terminal than Google Workspace.
- **Anti-patterns explicitly avoided:** gradient-on-every-button, bubbly uniform border-radius, generic card grids, AI-slop blue/purple gradients

## Typography
- **Display/Hero:** Sora — geometric, distinct from body, used for page titles and logo
- **Body/UI:** IBM Plex Sans — excellent readability, technical feel, strong at small sizes
- **Data/Tables:** IBM Plex Sans with `font-variant-numeric: tabular-nums` — critical for number alignment
- **Code/Mono:** JetBrains Mono / Fira Code — for UUIDs, IPs, config data
- **Loading:** Google Fonts CDN (IBM Plex Sans 400/500/600/700 + Sora 500/600/700)

### Type Scale
```
xs:     0.68rem / 10.9px — labels, badges
sm:     0.75rem / 12px   — table metadata, hints
base:   0.80rem / 12.8px — table body, buttons
md:     0.85rem / 13.6px — body text
lg:     0.90rem / 14.4px — section headers
xl:     1.00rem / 16px   — card titles
2xl:    1.15rem / 18.4px — page headers
```

## Color System

### Dark Theme (default)
```
bg.primary:   #0d1a2d  — page background
bg.secondary: #162032  — cards, panels, modals
bg.tertiary:  #1d2d42  — hover states, inputs, chips

text.primary:   #dde7f2  — main content
text.secondary: #7a96b2  — labels, metadata
text.tertiary:  #4d6678  — hints, disabled, placeholders

border:  #2a3d55  — dividers, card borders

accent:  #0dcfba  — teal — primary interactive color
success: #30c172  — green
warning: #f0b429  — amber
danger:  #ff5040  — red
info:    #3b9cff  — blue
```

### All *Text tokens → #ffffff (white)
This was previously broken (near-black on dark-ish backgrounds). Always white for button text on colored backgrounds.

### Light Theme
```
bg.primary:   #f0f4f9
bg.secondary: #ffffff
bg.tertiary:  #e8eef6

text.primary:   #0f1f33
text.secondary: #4a607a
text.tertiary:  #7a93ad

border: #c8d8ea
accent: #0891b2  — darker teal for light bg contrast
```

### Preset 3 (Black)
```
bg: #000000 / #0a0a0a / #111111
text: #f0f0f0 / #a0a0a0 / #666666
border: #222222
accent: #e0e0e0 (near-white)
```

## Spacing
- **Base unit:** 4px
- **Density:** Compact in tables (4-8px), comfortable in cards (14-22px)
- **Scale:** 4 / 8 / 10 / 12 / 14 / 16 / 20 / 24 / 32 / 40
- **Gap conventions:** gap-1 (4px) in action buttons, gap-2 (8px) in chips/filters, gap-3 (12px) in cards

## Layout
- **Approach:** Grid-disciplined — sidebar fixed 272px, content flex
- **Max content width:** Uncapped (full-width tables need it)
- **Border radius hierarchy:**
  - Tables/cells: 0 (flat, data-dense)
  - Chips/tags/badges: 4-6px (subtle rounding)
  - Buttons: 8-10px (btn-sm), 12px (btn)
  - Cards/panels: 14-16px
  - Modals: 18px
  - Pills/status: 999px

## Component Library (CSS classes)

### Chips (stat chips, filter chips)
```css
.chip               — base neutral chip
.chip.is-accent     — teal tinted
.chip.is-success    — green tinted
.chip.is-warning    — amber tinted
.chip.is-danger     — red tinted
.chip.is-info       — blue tinted
.chip.is-active     — solid accent
.chip.is-clickable  — adds pointer + hover
```

### Stats
```css
.stat-strip         — flex container for stat items
.stat-strip__item   — individual stat with color variants
```

### Actions
```css
.action-bar         — bulk selection bar
.filter-strip       — horizontal filter chip row
.filter-strip__btn  — individual filter button
```

### Indicators
```css
.health-badge.is-good / .is-fair / .is-poor
.latency-badge.is-fast / .is-ok / .is-slow
.status-dot.is-online / .is-offline / .is-unknown
.node-tag           — node category tag
```

### Loading
```css
.skeleton           — shimmer loading placeholder
.skeleton-row       — full-width row placeholder
.table-loading-bar  — animated 2px progress line
```

### Alerts
```css
.inline-alert.is-error / .is-success / .is-warning / .is-info
— bordered left-accent style, never solid background
```

## Motion
- **Approach:** Minimal-functional — only transitions that aid comprehension
- **Easing:** cubic-bezier(0.34, 1.56, 0.64, 1) for toasts/overlays (spring), ease for state changes
- **Duration:** micro 100-150ms (hover), short 200-250ms (show/hide), medium 300ms (page fade)
- **Toast enter:** slide from right + spring scale (toastIn animation)
- **Page enter:** opacity + translateY(5px) (appFadeIn animation)
- **Status dot online:** pulse animation 2s infinite

## Interaction States Spec

Every major UI component must have:

| Component | Loading | Empty | Error | Success |
|-----------|---------|-------|-------|---------|
| Client table | spinner-accent + loading bar | EmptyState with action | inline-alert.is-error | toast success |
| Node table | spinner | EmptyState + Add Node action | inline-alert | toast |
| Inbound table | spinner | EmptyState + Add action | inline-alert | toast |
| Traffic table | spinner | EmptyState | inline-alert | — |
| Login form | button disabled | — | inline-alert.is-error | redirect |

## Accessibility
- `accent-color: var(--accent)` on checkboxes
- `:focus-visible` ring using accent color
- All colored buttons: white text (#ffffff) regardless of background
- Warning amber (#f0b429): white text — border-based differentiation for colorblind users
- ARIA: role="status" on spinners, aria-label on icon-only buttons

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-30 | Initial design system created | Applied from design-consultation + design-review skills |
| 2026-05-30 | accentText/successText/warningText/infoText → #ffffff | Was near-black, invisible on dark semi-transparent buttons |
| 2026-05-30 | bg.tertiary #334155 → #1d2d42 | Was too bright/gray for a tertiary bg in a navy-based theme |
| 2026-05-30 | Removed gradient from neutral buttons | gradient-on-everything is AI slop anti-pattern |
| 2026-05-30 | Toast redesign: border-left + icon + progress bar | Solid colored bg was too aggressive, border style is more refined |
| 2026-05-30 | EmptyState component created | "No items found." is not a design — every empty state needs warmth + action |
| 2026-05-30 | .chip / .stat-strip / .action-bar CSS classes | Replaces 90+ instances of colors.accent + '22' inline hack |
