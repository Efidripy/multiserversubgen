import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

type Theme = 'light' | 'dark';
type StylePreset = '1' | '3';

interface ThemeContextType {
  theme: Theme;
  stylePreset: StylePreset;
  toggleTheme: () => void;
  setStylePreset: (preset: StylePreset) => void;
  colors: {
    bg: {
      primary: string;
      secondary: string;
      tertiary: string;
    };
    text: {
      primary: string;
      secondary: string;
      tertiary: string;
    };
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
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
};

const lightTheme = {
  bg: {
    primary: '#f2f6fb',
    secondary: '#ffffff',
    tertiary: '#eef3f9',
  },
  text: {
    primary: '#12243a',
    secondary: '#4d637d',
    tertiary: '#74879f',
  },
  border: '#d5e1ee',
  accent: '#0ea5b7',
  accentText: '#ffffff',
  success: '#28b463',
  successText: '#ffffff',
  warning: '#d39a1f',
  warningText: '#12243a',
  danger: '#e24a3b',
  dangerText: '#ffffff',
  info: '#2f7fd6',
  infoText: '#ffffff',
};

const darkTheme = {
  bg: {
    primary: '#0f172a',
    secondary: '#1e293b',
    tertiary: '#334155',
  },
  text: {
    primary: '#f1f5f9',
    secondary: '#94a3b8',
    tertiary: '#64748b',
  },
  border: '#334155',
  accent: '#14b8a6',
  accentText: '#04131b',
  success: '#38c172',
  successText: '#04110a',
  warning: '#f0b429',
  warningText: '#221506',
  danger: '#ff4d3a',
  dangerText: '#ffffff',
  info: '#3b9cff',
  infoText: '#041221',
};

const normalizeStylePreset = (value: string | null): StylePreset => (value === '3' ? '3' : '1');

function getColors(theme: Theme, stylePreset: StylePreset) {
  if (stylePreset === '3' && theme === 'dark') {
    return {
      bg: {
        primary: '#000000',
        secondary: '#0a0a0a',
        tertiary: '#121212',
      },
      text: {
        primary: '#ffffff',
        secondary: '#b3b3b3',
        tertiary: '#7a7a7a',
      },
      border: '#262626',
      accent: '#ffffff',
      accentText: '#000000',
      success: '#4ade80',
      successText: '#041109',
      warning: '#facc15',
      warningText: '#221a03',
      danger: '#ef4444',
      dangerText: '#ffffff',
      info: '#d4d4d8',
      infoText: '#050505',
    };
  }

  return theme === 'light' ? lightTheme : darkTheme;
}

interface ThemeProviderProps {
  children: ReactNode;
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({ children }) => {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('app_theme');
    return (saved as Theme) || 'dark';
  });
  const [stylePreset, setStylePresetState] = useState<StylePreset>(() => {
    return normalizeStylePreset(localStorage.getItem('app_style_preset'));
  });

  const colors = getColors(theme, stylePreset);

  useEffect(() => {
    localStorage.setItem('app_theme', theme);
    localStorage.setItem('app_style_preset', stylePreset);
    document.body.style.backgroundColor = colors.bg.primary;
    document.body.style.color = colors.text.primary;
    document.body.classList.toggle('theme-light', theme === 'light');
    document.body.classList.toggle('theme-dark', theme === 'dark');
    document.body.classList.remove('style-preset-1', 'style-preset-3');
    document.body.classList.add(`style-preset-${stylePreset}`);
    // Set CSS custom properties for use in App.css
    const root = document.documentElement;
    root.style.setProperty('--bg-primary', colors.bg.primary);
    root.style.setProperty('--bg-secondary', colors.bg.secondary);
    root.style.setProperty('--bg-tertiary', colors.bg.tertiary);
    root.style.setProperty('--text-primary', colors.text.primary);
    root.style.setProperty('--text-secondary', colors.text.secondary);
    root.style.setProperty('--text-tertiary', colors.text.tertiary);
    root.style.setProperty('--border-color', colors.border);
    root.style.setProperty('--accent', colors.accent);
    root.style.setProperty('--accent-text', colors.accentText);
    root.style.setProperty('--success', colors.success);
    root.style.setProperty('--success-text', colors.successText);
    root.style.setProperty('--warning', colors.warning);
    root.style.setProperty('--warning-text', colors.warningText);
    root.style.setProperty('--danger', colors.danger);
    root.style.setProperty('--danger-text', colors.dangerText);
    root.style.setProperty('--info', colors.info);
    root.style.setProperty('--info-text', colors.infoText);
    // Pre-computed semi-transparent accent variants used in App.css
    root.style.setProperty('--accent-focus-ring', hexToRgba(colors.accent, 0.22));
    root.style.setProperty('--accent-row-hover', hexToRgba(colors.accent, 0.06));
  }, [theme, colors, stylePreset]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'light' ? 'dark' : 'light');
  };

  const setStylePreset = (preset: StylePreset) => {
    setStylePresetState(normalizeStylePreset(preset));
  };

  return (
    <ThemeContext.Provider value={{ theme, stylePreset, toggleTheme, setStylePreset, colors }}>
      {children}
    </ThemeContext.Provider>
  );
};

/** Convert a 6-digit hex colour + alpha to an rgba() string. */
function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}
