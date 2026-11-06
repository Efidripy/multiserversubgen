# Components

React 18 + Vite, Tailwind v4 (utilities only, no preflight) plus BEM-like classes in `frontend/src/App.css`. No external UI kit; icons from lucide-react via `UIIcon`. Colors for inline styles come from `frontend/src/contexts/ThemeContext.tsx`.

Shared primitives:
- ChoiceChips: segmented control (used for language switch, filters)
- SelectMenu: custom dropdown select
- Toast: toast provider and notifications
- UIIcon: name -> lucide icon map

### `frontend/src/components/ChoiceChips.tsx`

```tsx
type ChoiceValue = string | number | boolean;

interface ThemeColors {
  accent: string;
  accentText: string;
  border: string;
  bg: { tertiary: string };
  text: { primary: string };
}

interface ChoiceOption<T extends ChoiceValue> {
  value: T;
  label: string;
  title?: string;
}

interface ChoiceChipsProps<T extends ChoiceValue> {
  options: ChoiceOption<T>[];
  value: T;
  onChange: (value: T) => void;
  colors?: ThemeColors;
  size?: 'sm' | 'md';
  className?: string;
  disabled?: boolean;
}

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

export function ChoiceChips<T extends ChoiceValue>({
  options,
  value,
  onChange,
  size = 'sm',
  className = '',
  disabled = false,
}: ChoiceChipsProps<T>) {
  const safeOptions = Array.isArray(options) ? options : [];

  return (
    <div className={`flex flex-wrap gap-1 ${className}`.trim()} role="group">
      {safeOptions.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            className={cn(
              'inline-flex items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-2.5 text-[11px] font-medium uppercase tracking-wider text-slate-400 transition-colors hover:border-cyan-300/35 hover:text-slate-100',
              size === 'md' ? 'h-9 px-3 text-xs' : 'h-7',
              active && 'border-cyan-300/50 bg-cyan-400/10 text-cyan-200',
              disabled && 'cursor-not-allowed opacity-50 hover:border-cyan-500/20 hover:text-slate-400',
            )}
            title={option.title}
            aria-pressed={active}
            disabled={disabled}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

```

### `frontend/src/components/SelectMenu.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

export interface SelectMenuOption {
  value: string | number;
  label: string;
}

interface SelectMenuProps {
  value: string | number;
  options: SelectMenuOption[];
  onChange: (value: string | number) => void;
  ariaLabel: string;
  className?: string;
}

/** Themed replacement for a native <select>: button + listbox popover. */
export function SelectMenu({ value, options, onChange, ariaLabel, className }: SelectMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event: Event) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={cn('relative min-w-0', className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((previous) => !previous)}
        className="inline-flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 text-left font-mono text-xs text-slate-200 transition-colors hover:border-cyan-300/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/40"
      >
        <span className="truncate">{selected?.label ?? ''}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform', open && 'rotate-180')} aria-hidden="true" />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label={ariaLabel}
          className="absolute left-0 z-30 m-0 mt-1 max-h-64 min-w-full list-none overflow-y-auto rounded-md border border-cyan-500/25 bg-[#0f1420] p-1 shadow-xl"
        >
          {options.map((option) => (
            <li key={String(option.value)} role="option" aria-selected={option.value === value}>
              <button
                type="button"
                onClick={() => { onChange(option.value); setOpen(false); }}
                className={cn(
                  'block w-full whitespace-nowrap rounded px-2.5 py-1.5 text-left font-mono text-xs transition-colors',
                  option.value === value ? 'bg-cyan-400/15 text-cyan-200' : 'text-slate-300 hover:bg-cyan-400/10 hover:text-cyan-100',
                )}
              >
                {option.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

```

### `frontend/src/components/Toast.tsx`

```tsx
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useTranslation } from 'react-i18next';
import { NODE_REFRESH_INCOMPLETE_EVENT } from '../services/forceRefresh';

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
  const { t } = useTranslation();
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

  useEffect(() => {
    const handleIncomplete = () => toast(t('common.nodeRefreshIncomplete'), 'warning');
    window.addEventListener(NODE_REFRESH_INCOMPLETE_EVENT, handleIncomplete);
    return () => window.removeEventListener(NODE_REFRESH_INCOMPLETE_EVENT, handleIncomplete);
  }, [toast, t]);

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

```

### `frontend/src/components/UIIcon.tsx`

```tsx
import React from 'react';

export type IconName =
  | 'logo'
  | 'dashboard'
  | 'servers'
  | 'inbounds'
  | 'clients'
  | 'traffic'
  | 'monitoring'
  | 'backup'
  | 'subscriptions'
  | 'user'
  | 'bell'
  | 'menu'
  | 'sun'
  | 'moon'
  | 'refresh'
  | 'plus'
  | 'download'
  | 'upload'
  | 'trash'
  | 'edit'
  | 'copy'
  | 'search'
  | 'warning'
  | 'clock'
  | 'check'
  | 'x'
  | 'link'
  | 'folder'
  | 'spinner'
  | 'statusOn'
  | 'statusOff'
  | 'snowflake'
  | 'duplicate'
  | 'note'
  | 'ip'
  | 'group'
  | 'clear'
  | 'attach';

interface UIIconProps {
  name: IconName;
  size?: number;
  className?: string;
}

export const UIIcon: React.FC<UIIconProps> = ({ name, size = 18, className }) => {
  const props = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.9,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    'aria-hidden': true,
  };

  switch (name) {
    case 'logo':
      return (
        <svg {...props}>
          <path d="M3 12h2m2-4v8m4-11v14m4-12v10m4-6v2" />
        </svg>
      );
    case 'dashboard':
      return (
        <svg {...props}>
          <rect x="3" y="3" width="8" height="8" rx="2" />
          <rect x="13" y="3" width="8" height="5" rx="2" />
          <rect x="13" y="10" width="8" height="11" rx="2" />
          <rect x="3" y="13" width="8" height="8" rx="2" />
        </svg>
      );
    case 'servers':
      return (
        <svg {...props}>
          <rect x="3" y="4" width="18" height="7" rx="2" />
          <rect x="3" y="13" width="18" height="7" rx="2" />
          <path d="M7 8h.01M7 17h.01M10 8h2M10 17h2" />
        </svg>
      );
    case 'inbounds':
      return (
        <svg {...props}>
          <path d="M8 5h4a4 4 0 0 1 0 8H8" />
          <path d="M16 11h-4a4 4 0 0 0 0 8h4" />
          <path d="M10 9l4 6" />
        </svg>
      );
    case 'clients':
      return (
        <svg {...props}>
          <path d="M16 19a4 4 0 0 0-8 0" />
          <circle cx="12" cy="10" r="3.5" />
          <path d="M21 19a3.5 3.5 0 0 0-3-3.4M3 19a3.5 3.5 0 0 1 3-3.4" />
        </svg>
      );
    case 'traffic':
      return (
        <svg {...props}>
          <path d="M3 17h18" />
          <path d="M7 15V9M12 15V6M17 15v-3" />
          <path d="M5 7l3-2 4 2 5-3 2 2" />
        </svg>
      );
    case 'monitoring':
      return (
        <svg {...props}>
          <path d="M3 12h3l2.2-5L12 18l2.5-7H21" />
        </svg>
      );
    case 'backup':
      return (
        <svg {...props}>
          <rect x="4" y="4" width="16" height="16" rx="3" />
          <path d="M8 9h8M8 13h8M8 17h5" />
        </svg>
      );
    case 'subscriptions':
      return (
        <svg {...props}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M3 9h18M8 13h8M8 16h5" />
        </svg>
      );
    case 'user':
      return (
        <svg {...props}>
          <circle cx="12" cy="8" r="3.2" />
          <path d="M5 19a7 7 0 0 1 14 0" />
        </svg>
      );
    case 'bell':
      return (
        <svg {...props}>
          <path d="M15 18H9" />
          <path d="M18 16H6l1.3-2.1a7 7 0 0 0 1-3.6V9a3.7 3.7 0 0 1 7.4 0v1.3a7 7 0 0 0 1 3.6Z" />
        </svg>
      );
    case 'menu':
      return (
        <svg {...props}>
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      );
    case 'sun':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2.3M12 19.7V22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2 12h2.3M19.7 12H22M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6" />
        </svg>
      );
    case 'moon':
      return (
        <svg {...props}>
          <path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a7 7 0 0 0 10 10Z" />
        </svg>
      );
    case 'refresh':
      return (
        <svg {...props}>
          <path d="M20 11a8 8 0 1 0 2 5.3" />
          <path d="M20 4v7h-7" />
        </svg>
      );
    case 'plus':
      return (
        <svg {...props}>
          <path d="M12 5v14M5 12h14" />
        </svg>
      );
    case 'download':
      return (
        <svg {...props}>
          <path d="M12 4v11" />
          <path d="m8 11 4 4 4-4" />
          <path d="M4 20h16" />
        </svg>
      );
    case 'upload':
      return (
        <svg {...props}>
          <path d="M12 20V9" />
          <path d="m8 13 4-4 4 4" />
          <path d="M4 4h16" />
        </svg>
      );
    case 'trash':
      return (
        <svg {...props}>
          <path d="M4 7h16" />
          <path d="M10 11v6M14 11v6" />
          <path d="M6 7l1 13h10l1-13M9 7V4h6v3" />
        </svg>
      );
    case 'edit':
      return (
        <svg {...props}>
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" />
        </svg>
      );
    case 'copy':
      return (
        <svg {...props}>
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <rect x="4" y="4" width="11" height="11" rx="2" />
        </svg>
      );
    case 'search':
      return (
        <svg {...props}>
          <circle cx="11" cy="11" r="6" />
          <path d="m20 20-4-4" />
        </svg>
      );
    case 'warning':
      return (
        <svg {...props}>
          <path d="m12 4 8 14H4Z" />
          <path d="M12 9v4M12 16h.01" />
        </svg>
      );
    case 'clock':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 8v5l3 2" />
        </svg>
      );
    case 'check':
      return (
        <svg {...props}>
          <path d="m5 13 4 4L19 7" />
        </svg>
      );
    case 'x':
      return (
        <svg {...props}>
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      );
    case 'link':
      return (
        <svg {...props}>
          <path d="M10 13a5 5 0 0 1 0-7l1-1a5 5 0 0 1 7 7l-1 1" />
          <path d="M14 11a5 5 0 0 1 0 7l-1 1a5 5 0 0 1-7-7l1-1" />
        </svg>
      );
    case 'folder':
      return (
        <svg {...props}>
          <path d="M3 6h6l2 2h10v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
        </svg>
      );
    case 'spinner':
      return (
        <svg {...props}>
          <path d="M21 12a9 9 0 1 1-3-6.7" />
        </svg>
      );
    case 'statusOn':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8" />
          <path d="m8.5 12.5 2.2 2.2L15.5 10" />
        </svg>
      );
    case 'statusOff':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8" />
          <path d="M9.5 9.5l5 5M14.5 9.5l-5 5" />
        </svg>
      );
    case 'snowflake':
      return (
        <svg {...props}>
          <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93 4.93 19.07" />
          <path d="M12 6l-2-2m2 2 2-2M12 18l-2 2m2-2 2 2M6 12l-2-2m2 2-2 2M18 12l2-2m-2 2 2 2" />
        </svg>
      );
    case 'duplicate':
      return (
        <svg {...props}>
          <rect x="8" y="8" width="12" height="12" rx="2" />
          <path d="M4 16V6a2 2 0 0 1 2-2h10" />
        </svg>
      );
    case 'note':
      return (
        <svg {...props}>
          <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
          <path d="M14 3v5h5M8 13h8M8 17h5" />
        </svg>
      );
    case 'ip':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 3a14 14 0 0 1 0 18M3 12h18M3.6 7h16.8M3.6 17h16.8" />
        </svg>
      );
    case 'group':
      return (
        <svg {...props}>
          <path d="M3 5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
          <path d="M13 5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2Z" />
          <path d="M3 15a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
          <path d="M13 17h8M17 13v8" />
        </svg>
      );
    case 'clear':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9" />
          <path d="m15 9-6 6M9 9l6 6" />
        </svg>
      );
    case 'attach':
      return (
        <svg {...props}>
          <path d="M8 7H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3" />
          <path d="M12 12V3" />
          <path d="m9 6 3-3 3 3" />
        </svg>
      );
    default:
      return null;
  }
};

```
