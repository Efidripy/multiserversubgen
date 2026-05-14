import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

type Theme = 'light' | 'dark';
type StylePreset = '1' | '3';
type ThemeMode = '1' | '2' | '3';

interface ThemeContextType {
  theme: Theme;
  stylePreset: StylePreset;
  themeMode: ThemeMode;
  toggleTheme: () => void;
  cycleThemeMode: () => void;
  setThemeMode: (mode: ThemeMode) => void;
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
const THEME_MODE_STORAGE_KEY = 'app_theme_mode';

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
const normalizeTheme = (value: string | null): Theme => (value === 'light' ? 'light' : 'dark');
const normalizeThemeMode = (value: string | null): ThemeMode => (value === '1' || value === '2' || value === '3' ? value : '2');

        // Get initial theme from window.APP_CONFIG if available
        const getInitialThemeFromConfig = (): Theme => {
          try {
            const config = (window as any).APP_CONFIG;
            if (config?.theme === 'light' || config?.theme === 'dark') {
              return config.theme as Theme;
            }
          } catch (e) {
            // Ignore errors, fall back to default
          }
          return 'dark';
        };

const resolveThemeMode = (theme: Theme, stylePreset: StylePreset): ThemeMode => {
  if (theme === 'light') return '1';
  return stylePreset === '3' ? '3' : '2';
};

const resolveThemeConfig = (mode: ThemeMode): { theme: Theme; stylePreset: StylePreset } => {
  if (mode === '1') return { theme: 'light', stylePreset: '1' };
  if (mode === '2') return { theme: 'dark', stylePreset: '1' };
  return { theme: 'dark', stylePreset: '3' };
};

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
  const [themeMode, setThemeModeState] = useState<ThemeMode>(() => {
    const explicitMode = localStorage.getItem(THEME_MODE_STORAGE_KEY);
    if (explicitMode) return normalizeThemeMode(explicitMode);
    const savedTheme = normalizeTheme(localStorage.getItem('app_theme'));
    const savedPreset = normalizeStylePreset(localStorage.getItem('app_style_preset'));
    return resolveThemeMode(savedTheme, savedPreset);
  });

  const initialConfig = resolveThemeConfig(themeMode);
  const [theme, setTheme] = useState<Theme>(() => {
  // Try to get theme from window.APP_CONFIG first
  const configTheme = getInitialThemeFromConfig();
  return configTheme || initialConfig.theme;
  });
  const [stylePreset, setStylePresetState] = useState<StylePreset>(() => {
    return initialConfig.stylePreset;
  });

  const colors = getColors(theme, stylePreset);

  useEffect(() => {
    const modeConfig = resolveThemeConfig(themeMode);
    if (theme !== modeConfig.theme) {
      setTheme(modeConfig.theme);
      return;
    }
    if (stylePreset !== modeConfig.stylePreset) {
      setStylePresetState(modeConfig.stylePreset);
    }
  }, [themeMode, theme, stylePreset]);

  useEffect(() => {
    localStorage.setItem('app_theme', theme);
    localStorage.setItem('app_style_preset', stylePreset);
    localStorage.setItem(THEME_MODE_STORAGE_KEY, themeMode);
    document.body.style.backgroundColor = colors.bg.primary;
    document.body.style.color = colors.text.primary;
    document.body.classList.toggle('theme-light', theme === 'light');
    document.body.classList.toggle('theme-dark', theme === 'dark');
    document.body.classList.remove('style-preset-1', 'style-preset-3');
    document.body.classList.add(`style-preset-${stylePreset}`);
    document.body.classList.remove('theme-mode-1', 'theme-mode-2', 'theme-mode-3');
    document.body.classList.add(`theme-mode-${themeMode}`);
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
  }, [theme, colors, stylePreset, themeMode]);

  const setThemeMode = (mode: ThemeMode) => {
    const normalizedMode = normalizeThemeMode(mode);
    setThemeModeState(normalizedMode);
  };

  const cycleThemeMode = () => {
    setThemeModeState((prev) => (prev === '1' ? '2' : prev === '2' ? '3' : '1'));
  };

  const toggleTheme = () => {
    if (themeMode === '3') {
      setThemeMode('1');
      return;
    }
    setThemeMode(themeMode === '1' ? '2' : '1');
  };

  const setStylePreset = (preset: StylePreset) => {
    const normalizedPreset = normalizeStylePreset(preset);
    setThemeMode(resolveThemeMode(theme, normalizedPreset));
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        stylePreset,
        themeMode,
        toggleTheme,
        cycleThemeMode,
        setThemeMode,
        setStylePreset,
        colors,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
};

/** Convert a 6-digit hex colour + alpha to an rgba() string. */
function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}
