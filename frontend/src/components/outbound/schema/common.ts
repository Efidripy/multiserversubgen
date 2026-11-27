import type { FieldDef } from '../types';
export const protocols = ['freedom', 'blackhole', 'dns', 'vmess', 'vless', 'trojan', 'shadowsocks', 'socks', 'http',
  'wireguard', 'hysteria', 'masque', 'loopback', 'amneziawg'];
export const common: FieldDef[] = [
  { path: ['protocol'], label: 'protocol', kind: 'select', options: protocols },
  { path: ['tag'], label: 'tag', kind: 'text' },
  { path: ['sendThrough'], label: 'sendThrough', kind: 'text' },
  { path: ['targetStrategy'], label: 'Target Strategy', kind: 'select', showIf: o => o.protocol !== 'freedom',
    clearValue: '', options: ['AsIs', 'UseIP', 'UseIPv6v4', 'UseIPv6', 'UseIPv4v6', 'UseIPv4',
      'ForceIP', 'ForceIPv6v4', 'ForceIPv6', 'ForceIPv4v6', 'ForceIPv4'] },
];
