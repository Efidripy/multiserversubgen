import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useTranslation } from 'react-i18next';

export type ToastLevel = 'success' | 'error' | 'warning' | 'info';

interface ToastItem {
  id: string;
  message: string;
  level: ToastLevel;
  duration: number;
  createdAt: number;
}

interface ToastContextValue {
  toast: (message: string, level?: ToastLevel) => void;
}

export const ToastContext = React.createContext<ToastContextValue>({ toast: () => {} });
export const useToast = () => React.useContext(ToastContext);

const ICONS: Record<ToastLevel, string> = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
};

const DURATIONS: Record<ToastLevel, number> = {
  success: 3200,
  info: 3500,
  warning: 4500,
  error: 6000,
};

function ToastItem({ item, onDismiss, colors }: {
  item: ToastItem;
  onDismiss: (id: string) => void;
  colors: ReturnType<typeof useTheme>['colors'];
}) {
  const [progress, setProgress] = useState(100);
  const [leaving, setLeaving] = useState(false);
  const { t } = useTranslation();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const step = 50;
    const decrement = (step / item.duration) * 100;
    intervalRef.current = setInterval(() => {
      setProgress(p => Math.max(0, p - decrement));
    }, step);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [item.duration]);

  const handleDismiss = () => {
    setLeaving(true);
    setTimeout(() => onDismiss(item.id), 200);
  };

  const accentColor = {
    success: colors.success,
    error: colors.danger,
    warning: colors.warning,
    info: colors.info,
  }[item.level];

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: colors.bg.secondary,
      border: `1px solid ${accentColor}44`,
      borderLeft: `3px solid ${accentColor}`,
      borderRadius: '10px',
      boxShadow: `0 4px 16px rgba(0,0,0,0.22), 0 0 0 1px ${accentColor}18`,
      overflow: 'hidden',
      opacity: leaving ? 0 : 1,
      transform: leaving ? 'translateX(16px)' : 'translateX(0)',
      transition: 'opacity 0.2s ease, transform 0.2s ease',
      animation: 'toastIn 0.22s cubic-bezier(0.34, 1.56, 0.64, 1) both',
      maxWidth: '360px',
      minWidth: '220px',
      backdropFilter: 'blur(8px)',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '10px',
        padding: '11px 14px',
      }}>
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '26px',
          height: '26px',
          borderRadius: '50%',
          background: `${accentColor}20`,
          color: accentColor,
          fontWeight: 700,
          fontSize: '0.78rem',
          flexShrink: 0,
        }}>
          {ICONS[item.level]}
        </span>
        <span style={{
          flex: 1,
          fontSize: '0.82rem',
          lineHeight: 1.45,
          color: colors.text.primary,
          wordBreak: 'break-word',
        }}>
          {item.message}
        </span>
        <button
          onClick={handleDismiss}
          aria-label={t('common.dismissNotification')}
          style={{
            background: 'none',
            border: 'none',
            color: colors.text.tertiary,
            cursor: 'pointer',
            padding: 0,
            lineHeight: 1,
            flexShrink: 0,
            fontSize: '0.75rem',
            marginTop: '1px',
          }}
        >
          ✕
        </button>
      </div>
      <div style={{
        height: '2px',
        background: `${accentColor}22`,
        position: 'relative',
      }}>
        <div style={{
          position: 'absolute',
          left: 0,
          top: 0,
          height: '100%',
          width: `${progress}%`,
          background: accentColor,
          transition: 'width 0.05s linear',
          borderRadius: '0 1px 1px 0',
        }} />
      </div>
    </div>
  );
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { colors } = useTheme();
  const [items, setItems] = useState<ToastItem[]>([]);
  const timerRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const toast = useCallback((message: string, level: ToastLevel = 'success') => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const duration = DURATIONS[level];
    setItems(prev => [...prev.slice(-4), { id, message, level, duration, createdAt: Date.now() }]);
    timerRef.current[id] = setTimeout(() => {
      setItems(prev => prev.filter(t => t.id !== id));
      delete timerRef.current[id];
    }, duration + 250);
  }, []);

  const dismiss = (id: string) => {
    clearTimeout(timerRef.current[id]);
    delete timerRef.current[id];
    setTimeout(() => setItems(prev => prev.filter(t => t.id !== id)), 210);
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div style={{
        position: 'fixed',
        bottom: '1.5rem',
        right: '1.5rem',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        pointerEvents: 'none',
      }}>
        {items.map(item => (
          <div key={item.id} role={item.level === 'error' ? 'alert' : 'status'} aria-live={item.level === 'error' ? 'assertive' : 'polite'} style={{ pointerEvents: 'auto' }}>
            <ToastItem item={item} onDismiss={dismiss} colors={colors} />
          </div>
        ))}
      </div>
      <style>{`
        @keyframes toastIn {
          from { opacity: 0; transform: translateX(24px) scale(0.95); }
          to   { opacity: 1; transform: translateX(0) scale(1); }
        }
      `}</style>
    </ToastContext.Provider>
  );
};
