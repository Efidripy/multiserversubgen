# Chapter 06: Figma Variant4 UI Completion Plan

Date: 2026-06-06
Project: `multiserversubgen`
Branch: existing dirty worktree
Previous chapter: `docs/CHAPTER-05-SPRINT-CLOSEOUT.md`

## Goal

Close the remaining visual debt between the current dashboard implementation and the Variant4 Figma export without changing the API layer.

This chapter is a view-layer plan only. The service contracts established in Chapters 03-05 remain locked:

- do not change `frontend/src/api/authService.ts`;
- do not change `frontend/src/api/dashboard.ts`;
- do not change `frontend/src/api/nodes.ts`;
- do not change `frontend/src/api/client.ts` transport behavior;
- do not remove dashboard envelope normalization;
- do not remove Network Error fallback states;
- do not make hidden dashboard fan-out implicit again.

## Inputs Analyzed

- Live reference: `https://asset-plasma-68641749.figma.site/variant4`
- Figma Make source URL: `https://www.figma.com/make/UoAQOpTCfiJWPksKoyaINb/Variant4--Copy-?p=f&t=4ikjwgOMLXaSKbua-0&preview-route=%2Fvariant4`
- Local export: `docs/Variant4`
- Current dashboard code:
  - `frontend/src/App.tsx`
  - `frontend/src/App.css`
  - `frontend/src/components/DashboardSummary.tsx`
  - `frontend/src/components/RegisteredFleetPanel.tsx`
  - `frontend/src/components/NodeManager.tsx`
  - `frontend/src/components/ServerStatus.tsx`

Playwright opened both reference URLs. The live reference renders as `Minimalist sidebar component (Copy)`. The Figma Make URL opens the project preview shell. The local export remains the technical source for class names, layout geometry, and component structure.

## Reference Structure

The relevant Variant4 export is not the small demo `Dashboard.tsx`; the actual dashboard donor is `FullDashboard.tsx`.

Primary donor files:

- `docs/Variant4/src/app/components/variant4/Root.tsx`
- `docs/Variant4/src/app/components/variant4/Sidebar.tsx`
- `docs/Variant4/src/app/components/variant4/Topbar.tsx`
- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`
- `docs/Variant4/src/app/components/variant4/RegisteredFleet.tsx`

Secondary references:

- `docs/Variant4/src/styles/theme.css`
- `docs/Variant4/src/app/components/ui/StatsCard.tsx`
- `docs/Variant4/src/app/components/ui/ServerStatusCard.tsx`

The shadcn/ui files in `docs/Variant4/src/app/components/ui/` should not be ported wholesale. The project already uses Bootstrap plus scoped CSS and has `UIIcon`. Use the export as a visual contract, not as a dependency mandate.

## Current State

The current implementation already has several correct foundations:

- `App.tsx` composes dashboard with `dashboard-command-grid`, `DashboardSummary`, `ServerStatus dashboardMode`, `NodeManager dashboardMode`, and `RegisteredFleetPanel`.
- `ServerStatus` dashboard mode uses `includeCounts={false}`, `includeCollectorStatus={false}`, and `includePanelUpdateChecks={false}` from `App.tsx`.
- `NodeManager` dashboard mode uses `includeCounts={false}`.
- `DashboardSummary` catches summary load failures and renders normalized fallback summary data.
- `RegisteredFleetPanel` catches fleet load failures and renders scoped empty/error states.
- `App.css` already contains a late Variant4-style CSS slice for dashboard summary, lane panels, server cards, node dashboard mode, and registered fleet.

The remaining debt is therefore visual composition and CSS consistency, not API wiring.

## UI Gap Inventory

### 1. Dashboard Shell Geometry

Current discrepancy:

- The export root is a full-height command shell: `flex h-screen bg-[#0a0e1a] relative overflow-hidden`.
- Current layout still carries the general app shell and route content padding.
- The current `dashboard-command-grid` reserves a normal grid column for the fleet panel, while the export uses main content with dynamic right padding and a fixed right rail.

Required view changes:

- Re-scope `app-main--dashboard-shell` and `app-content--dashboard-shell` to match the export background `#0a0e1a` and reduce generic app padding.
- Change dashboard content geometry toward the donor pattern:
  - main content column with `p-6`;
  - when fleet is open on xl screens, reserve about `429px` right padding;
  - keep mobile behavior as overlay.
- Avoid adding global decorative radial blobs beyond what already exists. Keep background quiet.

Donor source:

- `docs/Variant4/src/app/components/variant4/Root.tsx`
- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`

Target files:

- `frontend/src/App.css`
- `frontend/src/App.tsx` only if class hooks are missing.

### 2. Sidebar And Topbar Match

Current discrepancy:

- Donor sidebar is 240px expanded, 64px collapsed, mono uppercase navigation, v3.1 badge, active left cyan-magenta rail, and compact footer actions.
- Current sidebar dashboard styles are close but still use general app logo treatments, wider 272px base width, 11-14px radius in many places, and no exact donor collapsed shell.
- Donor topbar is sticky on the command shell, has centered uppercase title with a 16px route icon, and action buttons styled as dark square/compact mono controls.
- Current topbar is primarily mobile/tablet, hidden on desktop by media rules, and dashboard actions are still Bootstrap button styled with inline colors.

Required view changes:

- Tighten `.sidebar--dashboard-shell` to donor density:
  - expanded width close to 240px;
  - collapsed width close to 64px if collapse support is already present;
  - nav item radius 8px;
  - active state left rail using cyan to magenta;
  - footer buttons as stacked mono controls.
- Add or expose the dashboard topbar on desktop only if it does not duplicate existing desktop header semantics.
- Style topbar dashboard buttons through CSS classes, not inline Bootstrap button styles.
- Keep existing tab routing and notification/log handlers unchanged.

Donor source:

- `docs/Variant4/src/app/components/variant4/Sidebar.tsx`
- `docs/Variant4/src/app/components/variant4/Topbar.tsx`

Target files:

- `frontend/src/App.css`
- `frontend/src/App.tsx`

### 3. Mission Control Header

Current discrepancy:

- Donor Mission Control is a single compact card:
  - background `#0f1420`;
  - border `cyan-500/20`;
  - radius 8px;
  - padding 20px;
  - mono title and inline hero stats.
- Current `dashboard-summary` has a larger 22px radius, heavier radial background, and combines hero plus dashboard lanes in one large compound module.

Required view changes:

- Reduce `dashboard-summary` shell radius and padding to donor scale.
- Use mono typography consistently inside the dashboard command surface.
- Keep hero stat values inline and compact, not card-like.
- Preserve `heroDescription`, `heroStats`, and fallback summary data.

Donor source:

- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`

Target files:

- `frontend/src/components/DashboardSummary.tsx`
- `frontend/src/App.css`

### 4. Fleet Overview Flow

Current discrepancy:

- Donor flow after Mission Control is:
  - `FLEET OVERVIEW` title row with timestamp and refresh icon;
  - six KPI cards in a 3-column grid;
  - country/status chips;
  - `Top by traffic` card.
- Current `DashboardSummary` splits overview and traffic into two lanes and adds a "Traffic lane" section title/copy that is not in the donor.
- Current chips use real `online_by_node` names, which is correct behavior, but the visual treatment should look like donor rounded pills.

Required view changes:

- Refactor `DashboardSummary` markup to create a donor-like `Fleet Overview` section after the hero.
- Keep existing data sources:
  - `summary.nodes_total`;
  - `summary.clients_total`;
  - `summary.online_clients_total`;
  - `summary.traffic`;
  - `summary.online_by_node`;
  - `summary.top_clients`.
- Keep `onNavigate` and client search behavior unchanged.
- Remove or visually collapse the extra "Traffic lane" copy.
- Keep KPI cards as existing semantic buttons when `onNavigate` exists.

Donor source:

- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`
- `docs/Variant4/src/app/components/ui/StatsCard.tsx` only as a card anatomy reference.

Target files:

- `frontend/src/components/DashboardSummary.tsx`
- `frontend/src/App.css`

### 5. Node Intake Strip

Current discrepancy:

- Donor has a compact `NODE INTAKE` strip between Fleet Overview and Server Status with a gradient `Add node` action.
- Current dashboard passes `showIntake={false}` to `NodeManager`, so this strip is absent from the dashboard path.
- The old intake form exists and should not be duplicated.

Required view changes:

- Add a dashboard-only compact intake strip that opens the existing NodeManager add flow.
- Prefer extending `NodeManager` with a view-only `showIntakeStrip` or `dashboardIntake` prop if the existing state can be reused cleanly.
- Do not add new node API calls.
- Do not move node creation logic out of `NodeManager` in this visual phase.

Donor source:

- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`

Target files:

- `frontend/src/App.tsx`
- `frontend/src/components/NodeManager.tsx`
- `frontend/src/App.css`

### 6. Server Status Control Header

Current discrepancy:

- Donor Server Status header includes:
  - title;
  - online count;
  - active pill;
  - auto-refresh checkbox;
  - interval select;
  - refresh button;
  - fleet toggle button;
  - sort tabs;
  - batch operation row;
  - fleet summary stat chips.
- Current dashboard mode hides the full header and shows only a small refresh control. Sort tabs, stats, and action layout are mostly gated behind `!dashboardMode`.

Required view changes:

- Add a dashboard-mode control header that mirrors the donor visually but keeps API fan-out rules intact.
- Safe to expose existing local controls:
  - refresh;
  - auto-refresh;
  - interval select;
  - sort tabs;
  - fleet toggle callback from `App.tsx` if wired as a view prop.
- Keep destructive or broad batch actions in full operational mode unless explicitly approved later.
- Keep `includeCounts={false}`, `includeCollectorStatus={false}`, and `includePanelUpdateChecks={false}` in dashboard mode.

Donor source:

- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`

Target files:

- `frontend/src/components/ServerStatus.tsx`
- `frontend/src/App.tsx`
- `frontend/src/App.css`

### 7. Server Card Density And Action Row

Current discrepancy:

- Donor server cards are dense dark cards:
  - `#0a0e1a` surface;
  - 8px radius;
  - cyan border hover;
  - compact status and latency pills;
  - CPU/RAM/Disk bars with gradient fills;
  - two-column footer stats;
  - Xray core row;
  - icon-only operations row.
- Current server cards are functionally rich but still use generic `server-card`, inline style colors, Bootstrap chips/buttons, larger radius, and a reduced dashboard action surface.

Required view changes:

- Restyle `.server-status--dashboard .server-card` and children to donor density.
- Convert inline color reliance in dashboard mode to CSS classes where possible.
- Keep offline fallback block visible and scoped.
- Keep all handlers and service calls unchanged.
- If dashboard action icons are expanded, use existing handlers and `UIIcon` where possible; avoid adding new icon packages.

Donor source:

- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`
- `docs/Variant4/src/app/components/ui/ServerStatusCard.tsx` only as a metric anatomy reference.

Target files:

- `frontend/src/components/ServerStatus.tsx`
- `frontend/src/App.css`
- `frontend/src/components/UIIcon.tsx` only if a missing local icon is essential.

### 8. Registered Fleet Right Rail

Current discrepancy:

- Donor Registered Fleet is a fixed right panel:
  - width 420px;
  - `top: 0`, `bottom: 25px`, `pt-24`;
  - collapsed tab fixed at right edge;
  - vertical in-panel collapse rail;
  - hidden scrollbar but scrollable list;
  - compact cards with status dot, version, scheme/address, latency/status/RW, error row, and six icon-only actions.
- Current `RegisteredFleetPanel` is a sticky grid column and collapsed tab, with a reduced action row and larger radius.
- Current error/empty states are correct and must stay.

Required view changes:

- Rework only CSS geometry to match fixed right rail on xl screens.
- Keep mobile overlay behavior and backdrop.
- Hide fleet scrollbars using scoped rules similar to donor `#fleet-scroll-container`.
- Add compact action row parity only with safe existing callbacks; for missing operations, render disabled icon buttons or omit until backend action ownership is confirmed.
- Keep `getRegisteredFleetOverview()` error handling and `onSummaryChange` unchanged.

Donor source:

- `docs/Variant4/src/app/components/variant4/RegisteredFleet.tsx`
- `docs/Variant4/src/styles/theme.css`

Target files:

- `frontend/src/components/RegisteredFleetPanel.tsx`
- `frontend/src/App.css`

### 9. Radius, Palette, Typography, And Scrollbars

Current discrepancy:

- Donor command surface uses mostly 8px radius, mono typography, dark surfaces `#0a0e1a` and `#0f1420`, cyan borders, cyan/magenta accents, and hidden scrollbars.
- Current CSS mixes 14-22px radii, IBM Plex Sans/Sora, Bootstrap surfaces, inline colors, and visible/standard scroll areas.

Required view changes:

- Add a scoped dashboard command token block in `App.css`:
  - `--dashboard-bg: #0a0e1a`;
  - `--dashboard-panel: #0f1420`;
  - `--dashboard-panel-inner: #0a0e1a`;
  - `--dashboard-border: rgba(6, 182, 212, 0.20)`;
  - `--dashboard-border-strong: rgba(34, 211, 238, 0.30)`;
  - dashboard radius token close to 8px.
- Apply tokens under dashboard shell selectors only.
- Do not globally retheme non-dashboard modules in this phase.
- Add scoped hidden scrollbar utilities for fleet and dashboard overflow containers.

Donor source:

- `docs/Variant4/src/styles/theme.css`
- `docs/Variant4/src/app/components/variant4/FullDashboard.tsx`

Target files:

- `frontend/src/App.css`

## Legacy Debt To Remove

- Dashboard-mode Bootstrap button styling with inline `style={{ backgroundColor: ... }}` where scoped CSS classes can express the same state.
- `dashboard-summary` oversized 22px card radius and compound hero-plus-lanes wrapper.
- Separate "Traffic lane" presentation that does not exist in the donor.
- Sticky registered fleet grid column on desktop; replace with fixed right rail geometry.
- Single edit-only fleet action row where donor expects compact icon action density.
- Hidden dashboard server status header that removes donor control hierarchy.
- Generic `panel-block` visual inheritance inside donor-mapped dashboard lanes.
- Emoji-only controls in dashboard-critical action rows when an existing `UIIcon` equivalent exists.
- Large mixed-radius dashboard surfaces that fight the donor 8px card language.
- Any future temptation to import the whole shadcn/ui export instead of translating the view contract into existing project CSS.

## Surgical Implementation Order

1. CSS token alignment.
   - Add scoped dashboard command tokens and hidden-scrollbar helpers in `App.css`.
   - No TSX behavior changes.

2. Shell and topbar/sidebar density.
   - Tighten dashboard shell padding, background, sidebar, and topbar selectors.
   - Verify no mobile overlap.

3. DashboardSummary composition.
   - Split the visual composition into donor-like Mission Control and Fleet Overview blocks.
   - Preserve all summary loading/fallback logic.

4. RegisteredFleetPanel geometry.
   - Convert desktop rail to fixed right panel.
   - Preserve mobile overlay and existing error/empty states.

5. Node intake strip.
   - Add compact dashboard strip that reuses existing add-node flow.
   - Do not add new service calls.

6. ServerStatus dashboard header.
   - Add dashboard-mode header, sort tabs, and stats chips.
   - Keep destructive batch operations out of dashboard mode unless separately approved.

7. Server cards.
   - Tune density, status pills, metric bars, offline block, and icon-only operations.
   - Keep all existing handlers and fallback paths.

8. Responsive pass.
   - Check 1440px desktop, 1280px laptop, 768px tablet, and 390px mobile.
   - Ensure text does not overflow buttons/pills/cards.
   - Ensure the fixed fleet rail does not cover content when open.

9. Validation.
   - Run `cd frontend && npm run build`.
   - Run `cd frontend && npm run lint`.
   - Run browser smoke with backend unavailable to verify Network Error fallback still renders.
   - Run workspace mix gate if executable code changes are made.

## Non-Negotiable Guards

- `authService`, `dashboard`, `nodes`, and transport behavior stay unchanged.
- `normalizeDashboardSummary()` and node/dashboard envelope normalization stay unchanged.
- `Network Error` remains a supported render state.
- Dashboard mode keeps explicit light-load flags.
- No wholesale shadcn/ui import.
- No new icon package.
- No global CSS rewrite outside dashboard-scoped selectors.

## Ready For UI Coding

Ready: yes.

The next phase can implement this as a visual-only slice if it follows the order above and treats API/fallback logic as locked.
