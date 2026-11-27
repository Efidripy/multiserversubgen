export type Outbound = Record<string, any>;
export type Path = (string | number)[];
export type ItemContext = { path: Path; value: Outbound; index: number } | undefined;
export type FieldDef = {
  path: Path | ((outbound: Outbound, itemContext: ItemContext) => Path);
  label: string;
  kind: 'text' | 'number' | 'boolean' | 'select' | 'combobox' | 'list' | 'numberList' | 'keyValue' | 'array' | 'section' | 'toggle' | 'json';
  options?: string[] | ((outbound: Outbound) => string[]);
  placeholder?: string;
  showIf?: (outbound: Outbound, itemContext: ItemContext) => boolean;
  clearValue?: unknown | ((value: unknown) => boolean);
  fields?: FieldDef[];
  defaults?: unknown | ((outbound: Outbound) => unknown);
  read?: (value: unknown, outbound: Outbound, path: Path) => unknown;
  write?: (value: unknown, outbound: Outbound, path: Path) => unknown;
  onChange?: (outbound: Outbound, value: unknown, path: Path, previous: Outbound) => Outbound;
  uiOnly?: boolean;
  generate?: 'password' | 'shortId' | 'x25519';
};
