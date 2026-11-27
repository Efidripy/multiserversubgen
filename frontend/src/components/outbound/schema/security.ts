import type { FieldDef, Outbound } from '../types';

export const fingerprints = ['chrome', 'firefox', 'safari', 'ios', 'android', 'edge', '360', 'qq',
  'random', 'randomized', 'randomizednoalpn', 'unsafe'];
const fields = (name: string, entries: [string, string, FieldDef['kind'], string[]?][]): FieldDef[] =>
  entries.map(([key, label, kind, options]) => ({ path: ['streamSettings', `${name}Settings`, key], label, kind, options }));
export const securityFields: Record<string, FieldDef[]> = {
  none: [],
  tls: fields('tls', [
    ['serverName', 'SNI', 'text'], ['fingerprint', 'fingerprint', 'combobox', fingerprints],
    ['alpn', 'ALPN', 'list'], ['echConfigList', 'ECH', 'text'], ['verifyPeerCertByName', 'Verify Peer Name', 'text'],
    ['pinnedPeerCertSha256', 'Pinned SHA256', 'text'], ['useSystemCA', 'Use System CA', 'boolean'],
  ]),
  reality: fields('reality', [
    ['serverName', 'SNI', 'text'], ['fingerprint', 'fingerprint', 'combobox', fingerprints],
    ['shortId', 'Short ID', 'text'], ['spiderX', 'Spider X', 'text'], ['publicKey', 'Public Key', 'text'],
    ['mldsa65Verify', 'MLDSA65 Verify', 'text'],
  ]),
};
export const securityDefaults: Record<string, Outbound> = {
  none: {}, tls: { serverName: '', fingerprint: '', alpn: [], echConfigList: '', verifyPeerCertByName: '',
    pinnedPeerCertSha256: '' },
  reality: { serverName: '', fingerprint: 'chrome', shortId: '', spiderX: '', publicKey: '', mldsa65Verify: '' },
};
