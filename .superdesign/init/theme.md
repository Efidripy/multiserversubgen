# Theme

## Part 1. Token summary (current "classic" design)

Single dark theme ("Theme 3, dark OLED"). No light mode.

Colors:
- background #0a0e1a, card/sidebar/popover #0f1420, muted/tertiary #111827, input #0a0e1a
- foreground #f8fafc; text secondary #a0a0a0 / slate-400; tertiary #666 / muted-foreground #64748b
- primary/accent/ring #22d3ee (cyan), primary-foreground #06111f
- border rgba(34,211,238,0.20) (cyan hairline)
- success #4ade80, warning #facc15, danger #f87171 / destructive #fb7185, info #d4d4d8
- accent gradient used on primary CTAs: cyan-400 -> fuchsia-400

Type: --font-sans "IBM Plex Sans", Segoe UI, system-ui; --font-mono "JetBrains Mono". Base 16px; UI mostly 10-14px, uppercase tracked labels (tracking 0.16em) for section titles.
Radius: --radius 8px; sm 4, md 6, lg 8, xl 10.
Spacing: Tailwind default scale (p-3 / sm:p-4 / lg:p-6 page padding).
Shadows: inset 0 1px 0 rgba(148,163,184,0.04) on panels; 0 10px 24px rgba(34,211,238,0.16) on CTAs.
Breakpoints: Tailwind defaults (sm 640, md 768, lg 1024, xl 1280).
Buttons: global :active press feedback translateY(2px) scale(.97).

## Part 2. Raw sources

### `frontend/src/contexts/ThemeContext.tsx`

```tsx
import React, { createContext, useContext, useEffect, ReactNode } from 'react';

// Theme 3 only — dark OLED. Theme switching removed.
type Theme = 'dark';
type StylePreset = '3';
type ThemeMode = '3';

interface ThemeContextType {
  theme: Theme;
  stylePreset: StylePreset;
  themeMode: ThemeMode;
  colors: {
    bg: { primary: string; secondary: string; tertiary: string };
    text: { primary: string; secondary: string; tertiary: string };
    border: string;
    accent: string;
    accentText: string;
    success: string;
    successText: string;
    warning: string;
    warningText: string;
    danger: string;
    dangerText: string;
    info: string;
    infoText: string;
  };
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useTheme must be used within ThemeProvider');
  return context;
};

const COLORS: ThemeContextType['colors'] = {
  bg: {
    primary:   '#0a0e1a',
    secondary: '#0f1420',
    tertiary:  '#111827',
  },
  text: {
    primary:   '#f0f0f0',
    secondary: '#a0a0a0',
    tertiary:  '#666666',
  },
  border:      'rgba(34, 211, 238, 0.20)',
  accent:      '#22d3ee',
  accentText:  '#06111f',
  success:     '#4ade80',
  successText: '#000000',
  warning:     '#facc15',
  warningText: '#000000',
  danger:      '#f87171',
  dangerText:  '#000000',
  info:        '#d4d4d8',
  infoText:    '#000000',
};

function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

export const ThemeProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  useEffect(() => {
    document.body.style.backgroundColor = COLORS.bg.primary;
    document.body.style.color = COLORS.text.primary;
    document.body.classList.remove('theme-light', 'style-preset-1', 'theme-mode-1', 'theme-mode-2');
    document.body.classList.add('theme-dark', 'style-preset-3', 'theme-mode-3');

    const root = document.documentElement;
    root.style.setProperty('--bg-primary',    COLORS.bg.primary);
    root.style.setProperty('--bg-secondary',  COLORS.bg.secondary);
    root.style.setProperty('--bg-tertiary',   COLORS.bg.tertiary);
    root.style.setProperty('--text-primary',  COLORS.text.primary);
    root.style.setProperty('--text-secondary',COLORS.text.secondary);
    root.style.setProperty('--text-tertiary', COLORS.text.tertiary);
    root.style.setProperty('--border-color',  COLORS.border);
    root.style.setProperty('--accent',        COLORS.accent);
    root.style.setProperty('--accent-text',   COLORS.accentText);
    root.style.setProperty('--success',       COLORS.success);
    root.style.setProperty('--success-text',  COLORS.successText);
    root.style.setProperty('--warning',       COLORS.warning);
    root.style.setProperty('--warning-text',  COLORS.warningText);
    root.style.setProperty('--danger',        COLORS.danger);
    root.style.setProperty('--danger-text',   COLORS.dangerText);
    root.style.setProperty('--info',          COLORS.info);
    root.style.setProperty('--info-text',     COLORS.infoText);

    root.style.setProperty('--accent-focus-ring', hexToRgba(COLORS.accent, 0.22));
    root.style.setProperty('--accent-row-hover',  hexToRgba(COLORS.accent, 0.06));
    root.style.setProperty('--btn-accent-bg',     hexToRgba(COLORS.accent,   0.14));
    root.style.setProperty('--btn-accent-bdr',    hexToRgba(COLORS.accent,   0.42));
    root.style.setProperty('--btn-success-bg',    hexToRgba(COLORS.success,  0.13));
    root.style.setProperty('--btn-success-bdr',   hexToRgba(COLORS.success,  0.38));
    root.style.setProperty('--btn-warning-bg',    hexToRgba(COLORS.warning,  0.13));
    root.style.setProperty('--btn-warning-bdr',   hexToRgba(COLORS.warning,  0.38));
    root.style.setProperty('--btn-danger-bg',     hexToRgba(COLORS.danger,   0.13));
    root.style.setProperty('--btn-danger-bdr',    hexToRgba(COLORS.danger,   0.38));
    root.style.setProperty('--btn-info-bg',       hexToRgba(COLORS.info,     0.13));
    root.style.setProperty('--btn-info-bdr',      hexToRgba(COLORS.info,     0.38));

    localStorage.removeItem('app_theme');
    localStorage.removeItem('app_style_preset');
    localStorage.removeItem('app_theme_mode');
  }, []);

  return (
    <ThemeContext.Provider value={{ theme: 'dark', stylePreset: '3', themeMode: '3', colors: COLORS }}>
      {children}
    </ThemeContext.Provider>
  );
};

```

### `frontend/src/App.css` (token block, lines 1-82; full file is 1875 lines)

```css
@layer theme, base, components, utilities;

@import "tailwindcss/theme.css" layer(theme);
@import "tailwindcss/utilities.css" layer(utilities);

@source "./**/*.{ts,tsx}";

@custom-variant dark (&:is(.dark *));

:root {
  --font-size: 16px;
  --font-sans: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Mono", "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  --background: #0a0e1a;
  --foreground: #f8fafc;
  --card: #0f1420;
  --card-foreground: #f8fafc;
  --popover: #0f1420;
  --popover-foreground: #f8fafc;
  --primary: #22d3ee;
  --primary-foreground: #06111f;
  --secondary: #121827;
  --secondary-foreground: #dbeafe;
  --muted: #111827;
  --muted-foreground: #64748b;
  --accent: #22d3ee;
  --accent-foreground: #06111f;
  --destructive: #fb7185;
  --destructive-foreground: #fff1f2;
  --border: rgba(34, 211, 238, 0.20);
  --input: #0a0e1a;
  --input-background: #0a0e1a;
  --switch-background: #1f2937;
  --font-weight-medium: 500;
  --font-weight-normal: 400;
  --ring: #22d3ee;
  --radius: 8px;
  --sidebar: #0f1420;
  --sidebar-foreground: #cbd5e1;
  --sidebar-primary: #22d3ee;
  --sidebar-primary-foreground: #06111f;
  --sidebar-accent: #0b101b;
  --sidebar-accent-foreground: #67e8f9;
  --sidebar-border: rgba(34, 211, 238, 0.20);
  --sidebar-ring: #22d3ee;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-input-background: var(--input-background);
  --color-switch-background: var(--switch-background);
  --color-ring: var(--ring);
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 10px;
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
}
```
