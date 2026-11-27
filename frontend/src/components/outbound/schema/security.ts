import type { FieldDef, Outbound } from '../types';
const securityFieldsFor = (name: string): FieldDef[] => [
  { path: ['streamSettings', `${name}Settings`, 'serverName'], label: 'serverName', kind: 'text' },
  { path: ['streamSettings', `${name}Settings`, 'fingerprint'], label: 'fingerprint', kind: 'combobox',
    options: ['chrome', 'firefox', 'safari', 'ios', 'android', 'edge', 'random'] },
  { path: ['streamSettings', `${name}Settings`, 'alpn'], label: 'alpn', kind: 'list' },
];
export const securityFields: Record<string, FieldDef[]> = {
  none: [], tls: securityFieldsFor('tls'), reality: [...securityFieldsFor('reality'),
    ...['publicKey', 'shortId', 'spiderX'].map(name => ({ path: ['streamSettings', 'realitySettings', name], label: name, kind: 'text' as const }))],
};
export const securityDefaults: Record<string, Outbound> = { none: {}, tls: {}, reality: {} };
