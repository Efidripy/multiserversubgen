import type { FieldDef, Outbound, Path } from '../types';

const field = (path: Path, label: string, kind: FieldDef['kind'] = 'text', options?: string[]): FieldDef =>
  ({ path, label, kind, options });
const setting = (name: string, label: string, kind: FieldDef['kind'] = 'text', options?: string[]) =>
  field(['settings', name], label, kind, options);
const child = (name: string, label: string, kind: FieldDef['kind'] = 'text', options?: string[]) =>
  field([name], label, kind, options);
const server = (base: Path): FieldDef[] => [
  field([...base, 'address'], 'Server Address'), field([...base, 'port'], 'Port', 'number'),
];
const sniffing = (base: Path): FieldDef => ({
  path: base, label: 'Sniffing', kind: 'toggle', defaults: { enabled: true }, fields: [
    field([...base, 'enabled'], 'Enabled', 'boolean'),
    ...([
      ['destOverride', 'Destination Override', 'list'], ['metadataOnly', 'Metadata Only', 'boolean'],
      ['routeOnly', 'Route Only', 'boolean'], ['ipsExcluded', 'Excluded IPs', 'list'],
      ['domainsExcluded', 'Excluded Domains', 'list'],
    ] as const).map(([name, label, kind]) => ({
      ...field([...base, name], label, kind),
      showIf: (o: Outbound) => base.reduce((v, key) => v?.[key], o)?.enabled === true,
    })),
  ],
});
const vision = (o: Outbound) => o.settings?.flow === 'xtls-rprx-vision';
const peerFields = (psk: string): FieldDef[] => [
  child('endpoint', 'Endpoint'), child('publicKey', 'Public Key'), child(psk, 'Pre-shared Key'),
  child('allowedIPs', 'Allowed IPs', 'list'), child('keepAlive', 'Keep Alive', 'number'),
];
const strategy = ['AsIs', 'UseIP', 'UseIPv6v4', 'UseIPv6', 'UseIPv4v6', 'UseIPv4',
  'ForceIP', 'ForceIPv6v4', 'ForceIPv6', 'ForceIPv4v6', 'ForceIPv4'];
const finalRulesLabel = 'Final Rules';
const finalRules: FieldDef = {
  path: ['settings', 'finalRules'], label: finalRulesLabel, kind: 'array', defaults: { action: 'allow' }, fields: [
    child('action', 'Action', 'select', ['allow', 'block']),
    child('network', 'Network', 'select', ['', 'tcp', 'udp', 'tcp,udp']),
    child('port', 'Port'), child('ip', 'IP / CIDR / geoip', 'list'),
    { ...child('delay', 'Block Delay'), showIf: (_o, ctx) => ctx?.value?.action === 'block' },
    { ...child('logLevel', 'Log Level', 'combobox'), showIf: (_o, ctx) => ctx?.value?.action === 'block' },
  ],
};
const wgPeer = { endpoint: '', publicKey: '', preSharedKey: '', allowedIPs: ['0.0.0.0/0', '::/0'], keepAlive: 0 };
const awgPeer = { endpoint: '', publicKey: '', presharedKey: '', allowedIPs: ['0.0.0.0/0', '::/0'], keepAlive: 25 };
const servers = ['settings', 'servers', 0];
const vnext = ['settings', 'vnext', 0];
const ssMethods = ['aes-256-gcm', 'chacha20-poly1305', 'chacha20-ietf-poly1305', 'xchacha20-ietf-poly1305',
  '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm', '2022-blake3-chacha20-poly1305'];

export const protocolFields: Record<string, FieldDef[]> = {
  freedom: [
    field(['streamSettings', 'sockopt', 'domainStrategy'], 'Strategy', 'select', strategy),
    setting('redirect', 'Redirect'), setting('userLevel', 'User Level', 'number'),
    setting('proxyProtocol', 'Proxy Protocol', 'number'),
    { path: ['settings', 'fragment'], label: 'Fragment', kind: 'toggle', defaults: {}, fields: [
      field(['settings', 'fragment', 'packets'], 'Packets', 'combobox', ['tlshello', '1-3', '1-5']),
      ...['length', 'interval', 'maxSplit'].map(name => field(['settings', 'fragment', name],
        name === 'maxSplit' ? 'Max Split' : name === 'length' ? 'Length' : 'Interval')),
    ] },
    { path: ['settings', 'noises'], label: 'Noises', kind: 'toggle', defaults: [], fields: [
      { path: ['settings', 'noises'], label: 'Noise', kind: 'array',
        defaults: { type: 'rand', packet: '10-20', delay: '10-16', applyTo: 'ip' }, fields: [
          child('type', 'Type', 'select', ['rand', 'base64', 'str', 'hex']), child('packet', 'Packet'),
          child('delay', 'Delay'), child('applyTo', 'Apply To', 'select', ['ip', 'ipv4', 'ipv6']),
        ] },
    ] }, finalRules,
  ],
  blackhole: [
    { ...field(['settings', 'response', 'type'], 'Response Type', 'select', ['', 'none', 'http', 'custom']), clearValue: '' },
    { ...field(['settings', 'response', 'customResponseData'], 'Custom Response Data'),
      showIf: o => o.settings?.response?.type === 'custom' },
  ],
  dns: [
    setting('rewriteNetwork', 'Rewrite Network', 'select', ['', 'udp', 'tcp']),
    setting('rewriteAddress', 'Rewrite Address'), setting('rewritePort', 'Rewrite Port', 'number'),
    setting('userLevel', 'User Level', 'number'),
    { path: ['settings', 'rules'], label: 'Rules', kind: 'array', defaults: { action: 'direct' }, fields: [
      child('action', 'Action', 'select', ['direct', 'drop', 'return', 'hijack']), child('qType', 'QType'),
      child('domain', 'Domain', 'list'), child('rCode', 'RCode', 'number'),
    ] },
  ],
  vmess: [
    ...server(vnext), field([...vnext, 'users', 0, 'id'], 'ID'),
    field([...vnext, 'users', 0, 'security'], 'Security', 'select', ['aes-128-gcm', 'chacha20-poly1305', 'auto']),
  ],
  vless: [
    { path: o => Array.isArray(o.settings?.vnext) ? [...vnext, 'address'] : ['settings', 'address'],
      label: 'address', kind: 'text' },
    { path: o => Array.isArray(o.settings?.vnext) ? [...vnext, 'port'] : ['settings', 'port'],
      label: 'Port', kind: 'number' },
    { path: o => Array.isArray(o.settings?.vnext) ? [...vnext, 'users', 0, 'id'] : ['settings', 'id'],
      label: 'id', kind: 'text' },
    setting('encryption', 'Encryption'),
    setting('flow', 'Flow', 'select', ['', 'xtls-rprx-vision', 'xtls-rprx-vision-udp443']),
    { ...setting('testpre', 'Test Pre', 'number'), showIf: vision },
    { ...setting('testseed', 'Test Seed', 'numberList'), showIf: vision },
    { ...field(['settings', 'reverse', 'tag'], 'Reverse Tag'), clearValue: '' },
    { ...sniffing(['settings', 'reverse', 'sniffing']), showIf: o => !!o.settings?.reverse?.tag },
  ],
  trojan: [...server(servers), field([...servers, 'password'], 'Password')],
  shadowsocks: [
    ...server(servers), field([...servers, 'password'], 'Password'),
    field([...servers, 'method'], 'Encryption', 'combobox', ssMethods),
    field([...servers, 'uot'], 'UDP over TCP', 'boolean'), field([...servers, 'UoTVersion'], 'UoT Version', 'number'),
  ],
  socks: [
    ...server(servers), field([...servers, 'users', 0, 'user'], 'Username'),
    field([...servers, 'users', 0, 'pass'], 'Password'),
  ],
  http: [
    ...server(servers), field([...servers, 'users', 0, 'user'], 'Username'),
    field([...servers, 'users', 0, 'pass'], 'Password'), setting('headers', 'Headers', 'keyValue'),
  ],
  wireguard: [
    setting('secretKey', 'Private Key'), setting('address', 'Address', 'list'), setting('mtu', 'MTU', 'number'),
    setting('noKernelTun', 'No Kernel Tun', 'boolean'), setting('reserved', 'Reserved', 'numberList'),
    setting('remoteDNS', 'Remote DNS', 'list'),
    { path: ['settings', 'peers'], label: 'Peers', kind: 'array', defaults: wgPeer, fields: peerFields('preSharedKey') },
  ],
  hysteria: [...server(['settings']), setting('version', 'Version', 'number')],
  masque: [...server(['settings']), setting('remoteDNS', 'Remote DNS', 'list')],
  loopback: [setting('inboundTag', 'Inbound Tag'), sniffing(['settings', 'sniffing'])],
  amneziawg: [
    setting('mtu', 'MTU', 'number'), setting('listenPort', 'Listen Port', 'number'), setting('secretKey', 'Private Key'),
    field(['settings', 'address', 0], 'Address'), setting('dns', 'DNS'), setting('headerProtectionKey', 'Header Protection Key'),
    { path: ['settings'], label: 'Obfuscation', kind: 'section', fields: [
      ...['jc', 'jmin', 'jmax', 's1', 's2', 's3', 's4'].map(name => setting(name, name.toUpperCase(), 'number')),
      ...['h1', 'h2', 'h3', 'h4', 'i1', 'i2', 'i3', 'i4', 'i5'].map(name => setting(name, name.toUpperCase())),
      setting('contentPaddingAddition', 'Content Padding Addition'),
      setting('randomTrailers', 'Random Trailers', 'boolean'), setting('disableCookies', 'Disable Cookies', 'boolean'),
    ] },
    { path: ['settings', 'peers'], label: 'Peers', kind: 'array', defaults: awgPeer, fields: peerFields('presharedKey') },
  ],
};
export const protocolDefaults: Record<string, Outbound> = {
  freedom: {}, blackhole: {}, dns: { rewritePort: 53, userLevel: 0 },
  vmess: { vnext: [{ address: '', port: 443, users: [{ id: '', security: 'auto' }] }] },
  vless: { address: '', port: 443, id: '', encryption: 'none' },
  trojan: { servers: [{ address: '', port: 443, password: '' }] },
  shadowsocks: { servers: [{ address: '', port: 443, password: '', method: '2022-blake3-aes-128-gcm',
    uot: false, UoTVersion: 1 }] },
  socks: { servers: [{ address: '', port: 1080, users: [{ user: '', pass: '' }] }] },
  http: { servers: [{ address: '', port: 8080, users: [{ user: '', pass: '' }] }] },
  wireguard: { address: [], mtu: 1420, noKernelTun: false, peers: [wgPeer] },
  hysteria: { address: '', port: 443, version: 2 }, masque: { address: '', port: 443 }, loopback: {},
  amneziawg: { mtu: 0, listenPort: 0, jc: 0, jmin: 40, jmax: 100, s1: 15, s2: 80, s3: 12, s4: 12,
    randomTrailers: false, disableCookies: true, address: [], peers: [] },
};
