type ChoiceValue = string | number | boolean;

interface ThemeColors {
  accent: string;
  border: string;
  bg: {
    tertiary: string;
  };
  text: {
    primary: string;
  };
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
  colors: ThemeColors;
  size?: 'sm' | 'md';
  className?: string;
}

export function ChoiceChips<T extends ChoiceValue>({
  options,
  value,
  onChange,
  colors,
  size = 'sm',
  className = '',
}: ChoiceChipsProps<T>) {
  const buttonClassName = size === 'md' ? 'btn' : 'btn btn-sm';

  return (
    <div className={`d-flex flex-wrap gap-2 ${className}`.trim()}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            className={buttonClassName}
            title={option.title}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            style={{
              backgroundColor: active ? colors.accent : colors.bg.tertiary,
              borderColor: active ? colors.accent : colors.border,
              color: active ? '#ffffff' : colors.text.primary,
              whiteSpace: 'nowrap',
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
