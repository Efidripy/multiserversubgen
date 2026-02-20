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
    primary: '#0d1117',
    secondary: '#161b22',
    tertiary: '#21262d',
  },
  text: {
    primary: '#c9d1d9',
    secondary: '#8b949e',
    tertiary: '#6e7681',
  },
  border: '#30363d',
  accent: '#58a6ff',
  success: '#3fb950',
  warning: '#d29922',
  danger: '#f85149',
  info: '#1f6feb',
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
