import type { FieldDef } from '../types';
export const sockoptFields = (tags: string[]): FieldDef[] => [
  { path: ['streamSettings', 'sockopt', 'dialerProxy'], label: 'dialerProxy', kind: 'select', options: tags },
];
