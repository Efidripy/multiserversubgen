import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

type Theme = 'light' | 'dark';

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
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
    success: string;
    warning: string;
    danger: string;
    info: string;
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
    primary: '#ffffff',
    secondary: '#f6f8fa',
    tertiary: '#e1e4e8',
  },
  text: {
    primary: '#24292e',
    secondary: '#586069',
    tertiary: '#6a737d',
  },
  border: '#d1d5da',
  accent: '#0366d6',
  success: '#28a745',
  warning: '#ffd33d',
  danger: '#d73a49',
  info: '#0366d6',
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
  success: '#22c55e',
  warning: '#f59e0b',
  danger: '#ef4444',
  info: '#0ea5e9',
};

interface ThemeProviderProps {
  children: ReactNode;
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({ children }) => {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('app_theme');
    return (saved as Theme) || 'dark';
  });

  const colors = theme === 'light' ? lightTheme : darkTheme;

  useEffect(() => {
    localStorage.setItem('app_theme', theme);
    document.body.style.backgroundColor = colors.bg.primary;
    document.body.style.color = colors.text.primary;
  }, [theme, colors]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'light' ? 'dark' : 'light');
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, colors }}>
      {children}
    </ThemeContext.Provider>
  );
};
