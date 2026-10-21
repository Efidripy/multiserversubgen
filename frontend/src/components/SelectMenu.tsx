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
