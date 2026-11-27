import type { FieldDef } from '../types';
export const protocols = ['freedom', 'blackhole', 'dns', 'vmess', 'vless', 'trojan', 'shadowsocks', 'socks', 'http',
  'wireguard', 'hysteria', 'masque', 'loopback', 'amneziawg'];
export const common: FieldDef[] = [
  { path: ['protocol'], label: 'protocol', kind: 'select', options: protocols },
  { path: ['tag'], label: 'tag', kind: 'text' },
  { path: ['sendThrough'], label: 'sendThrough', kind: 'text' },
];
