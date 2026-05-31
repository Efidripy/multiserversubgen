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
}

export function ChoiceChips<T extends ChoiceValue>({
  options,
  value,
  onChange,
  size = 'sm',
  className = '',
}: ChoiceChipsProps<T>) {
  return (
    <div className={`d-flex flex-wrap gap-1 ${className}`.trim()} role="group">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            className={`filter-strip__btn${active ? ' is-active' : ''}${size === 'md' ? ' filter-strip__btn--md' : ''}`}
            title={option.title}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
