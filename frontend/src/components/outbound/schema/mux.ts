import type { FieldDef } from '../types';
export const muxFields: FieldDef[] = [
  { path: ['mux', 'enabled'], label: 'mux.enabled', kind: 'boolean' },
  { path: ['mux', 'concurrency'], label: 'mux.concurrency', kind: 'number' },
];
