import type { FieldDef, Outbound } from '../../types';

export const field = (path: string, kind: FieldDef['kind'] = 'text', options?: string[]): FieldDef =>
  ({ path: path.split('.'), label: path.split('.').at(-1) || path, kind, options });
export const section = (label: string, fields: FieldDef[], showIf?: (value: Outbound) => boolean): FieldDef =>
  ({ path: [], label, kind: 'section', fields, showIf });
export const array = (path: string, fields: FieldDef[]): FieldDef => ({ ...field(path, 'array'), fields, defaults: {} });
