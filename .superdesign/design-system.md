# Sub Manager: design system context

## Product
Sub Manager is a self-hosted admin panel for a multi-server VPN business built on 3x-ui / Xray nodes. One or a few admins run it daily on desktop and phone. Interface languages: Russian (primary) and English.

Jobs to be done, in priority order:
1. See at a glance whether every node is alive, how many clients are online, and whether traffic or subscriptions are about to run out.
2. Manage clients across many servers at once: add, edit, extend, set traffic limits, copy subscription links and QR codes.
3. Manage inbounds (VLESS Reality, VMess, Trojan, Shadowsocks) per node.
4. Watch traffic and monitoring charts, read server logs, run node operations (restart Xray, update), backups.
5. Configure subscription pages, Xray JSON templates, Happ routing, and the Telegram bot (broadcasts, client linking).

## Navigation (sidebar order)
Dashboard, Inbounds, Clients, Traffic, Monitoring, Backup (admin), Subscriptions (admin), Telegram (admin).
Sidebar footer: user name, language switch (RU | EN), and directly below it the design switch ("Старый дизайн" | "Новый дизайн"), then shortcuts, activity log, API docs, logout.
Topbar: section title with icon, network-activity dot, notifications bell with unread badge, activity LOG toggle, and on Dashboard a "Registered fleet 4/5 online" pill.

## Real content to use
Nodes: fra-01 Frankfurt DE, ams-02 Amsterdam NL, hel-01 Helsinki FI, waw-01 Warsaw PL, ist-01 Istanbul TR (offline 14 min).
Per node: inbounds count, online clients, CPU %, RAM %, uptime, Xray version, traffic in/out.
Totals: 1.84 TB traffic in 30 days, 312 clients online, 4 of 5 nodes online, 1 248 clients total, 37 expiring within 7 days.
Client row: email/name, inbound, node(s), traffic used / limit (e.g. 38.2 / 100 GB), expiry date, online state, enabled toggle.

## Current ("classic") visual system — must stay untouched
Dark only. Background #0a0e1a, panels #0f1420, cyan accent #22d3ee, cyan hairline borders rgba(34,211,238,.2), IBM Plex Sans, JetBrains Mono for numbers, radius 8px, uppercase tracked section labels, cyan-to-fuchsia gradient on primary CTA.

## New design
A new, parallel design is being created; the classic one keeps working and users switch between them. New design directions are free to change palette, typography, layout, density, radii and motion. They must keep: every function and data field above, Russian copy, the sidebar footer order (language switch, then design switch), accessible contrast (WCAG AA), tabular numbers in tables, and responsive behaviour for 375 / 768 / 1440 px.

Avoid generic AI looks: purple-blue gradient heroes, glassmorphism, identical rounded cards with soft grey shadows, neon on near-black, cream + terracotta + serif, emoji icons.

Icons: lucide-react line icons (layout-dashboard, network, users, activity, chart, archive, link, send, bell, refresh, server, cpu, power).
