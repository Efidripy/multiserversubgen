# Extractable components

## Layout

## Sidebar
- Source: `frontend/src/components/Sidebar.tsx`
- Category: layout
- Description: Collapsible left navigation with brand, nav items, user, language switch (ChoiceChips RU/EN), footer actions, logout
- Extractable props: activeItem (string, default "dashboard"), collapsed (boolean, default false)
- Hardcoded: nav labels, lucide icons, footer actions

## Topbar
- Source: `frontend/src/App.tsx` (header.app-topbar)
- Category: layout
- Description: Section title with icon and network-activity dot, notifications bell with unread badge, LOG toggle, fleet pill
- Extractable props: title (string), unreadCount (number, default 0), showFleetPill (boolean, default true)
- Hardcoded: icons, button labels

## Basic

## ChoiceChips
- Source: `frontend/src/components/ChoiceChips.tsx`
- Category: basic
- Description: Segmented control
- Extractable props: value (string)
- Hardcoded: styles

## SelectMenu
- Source: `frontend/src/components/SelectMenu.tsx`
- Category: basic
- Description: Dropdown select
- Extractable props: value (string)
- Hardcoded: styles

## StatusPill (pattern)
- Source: `frontend/src/components/ServerStatus.tsx`
- Category: basic
- Description: Online/offline status badge for nodes
- Extractable props: status ("online"|"offline")
- Hardcoded: colors
