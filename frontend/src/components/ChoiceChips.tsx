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
