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
  border:      'transparent',
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
