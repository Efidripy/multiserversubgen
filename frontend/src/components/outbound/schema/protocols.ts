import type { FieldDef, Outbound, Path } from '../types';
const server = (o: Outbound): Path => Array.isArray(o.settings?.vnext) ? ['settings', 'vnext', 0]
  : Array.isArray(o.settings?.servers) ? ['settings', 'servers', 0] : ['settings'];
const user = (o: Outbound): Path => {
  const base = server(o);
  const item = base.length === 1 ? o.settings : o.settings?.[base[1]]?.[0];
  return Array.isArray(item?.users) ? [...base, 'users', 0] : base;
};
const s = (name: string, kind: FieldDef['kind'] = 'text', options?: string[]): FieldDef =>
  ({ path: o => [...server(o), name], label: name, kind, options });
const u = (name: string, options?: string[]): FieldDef =>
  ({ path: o => [...user(o), name], label: name, kind: options ? 'combobox' : 'text', options });
const basic = [s('address'), s('port', 'number')];
export const protocolFields: Record<string, FieldDef[]> = {
  freedom: [{ path: ['settings', 'domainStrategy'], label: 'domainStrategy', kind: 'combobox', options: ['AsIs', 'UseIP', 'UseIPv4', 'UseIPv6'] }],
  blackhole: [{ path: ['settings', 'response', 'type'], label: 'response.type', kind: 'combobox', options: ['none', 'http'] }],
  dns: basic,
  vmess: [...basic, u('id'), u('security', ['auto', 'aes-128-gcm', 'chacha20-poly1305', 'none', 'zero'])],
  vless: [...basic, u('id'), u('flow', ['xtls-rprx-vision']), u('encryption')],
  trojan: [...basic, s('password')],
  shadowsocks: [...basic, s('password'), s('method', 'combobox', ['aes-128-gcm', 'aes-256-gcm', 'chacha20-poly1305',
    '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm'])],
  socks: [...basic, u('user'), u('pass')],
  http: [...basic, u('user'), u('pass')],
  wireguard: [
    { path: ['settings', 'secretKey'], label: 'secretKey', kind: 'text' },
    { path: ['settings', 'address'], label: 'address', kind: 'list' },
    ...(['publicKey', 'endpoint', 'allowedIPs', 'preSharedKey', 'keepAlive'] as const).map(name => ({
      path: ['settings', 'peers', 0, name], label: name,
      kind: name === 'allowedIPs' ? 'list' as const : name === 'keepAlive' ? 'number' as const : 'text' as const,
    })),
    { path: ['settings', 'mtu'], label: 'mtu', kind: 'number' },
    { path: ['settings', 'reserved'], label: 'reserved', kind: 'numberList' },
  ],
  hysteria: [...basic, { path: ['streamSettings', 'hysteriaSettings', 'auth'], label: 'auth', kind: 'text' }],
  masque: basic,
  loopback: basic,
  amneziawg: basic,
};
export const protocolDefaults: Record<string, Outbound> = Object.fromEntries(Object.keys(protocolFields).map(key => [key, {}]));
