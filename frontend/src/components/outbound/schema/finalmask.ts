import { getPath, setPath } from '../paths';
import type { FieldDef, ItemContext, Outbound } from '../types';

const base = ['streamSettings', 'finalmask'];
const maskType = (types: string[]) => (value: Outbound, context: ItemContext) => {
  if (!context) return false;
  const index = context.path.findIndex((part, i) => typeof part === 'number' && ['tcp', 'udp'].includes(String(context.path[i - 1])));
  return index >= 0 && types.includes(getPath(value, [...context.path.slice(0, index + 1), 'type']));
};
const settings = (name: string, label: string, kind: FieldDef['kind'], types: string[], options?: string[]): FieldDef => ({
  path: ['settings', name], label, kind, options, showIf: maskType(types),
});
const tcp = ['fragment', 'header-custom', 'sudoku', 'xmc'];
const udp = ['salamander', 'mkcp-legacy', 'xdns', 'xicmp', 'realm', 'header-custom', 'noise', 'sudoku', 'udphop'];
const maskSelector = (options: string[]): FieldDef => ({
  path: ['type'], label: 'Type', kind: 'select', options,
  onChange: (o, type, path, previous) => {
    const settingsPath = [...path.slice(0, -1), 'settings'];
    const old = getPath(o, settingsPath);
    if (old && Object.keys(old).length && !window.confirm('Replace mask settings?')) return previous;
    const defaults: Record<string, Outbound> = {
      fragment: { packets: '1-3', lengths: ['100-200'], delays: [], maxSplit: '' },
      salamander: { password: '' }, sudoku: { password: '', ascii: '', customTable: '', customTables: [], paddingMin: 0, paddingMax: 0 },
      xmc: { hostname: '', password: '', profiles: [{ username: '', uuid: '', texturesValue: '', texturesSignature: '' }] },
      xdns: { domains: [] }, udphop: { mode: 'intervalRemote', interval: '5-10' },
      'header-custom': { clients: [], servers: [], client: [], server: [] }, noise: { reset: 0, noise: [] },
    };
    return setPath(o, settingsPath, defaults[String(type)] || {});
  },
});
const packets = (isTcp: boolean, noise = false): FieldDef[] => [
  ...(!noise ? [{ path: ['kind'], label: 'Kind', kind: 'select', options: ['bytes', 'reuse', 'transform'], uiOnly: true,
    read: (_: unknown, o: Outbound, p: (string | number)[]) => {
      const item = getPath(o, p.slice(0, -1)); return item?.reuse !== undefined ? 'reuse' : item?.transform !== undefined ? 'transform' : 'bytes';
    },
    onChange: (o: Outbound, v: unknown, p: (string | number)[]) => {
      const item = getPath(o, p.slice(0, -1));
      for (const key of ['type', 'packet', 'rand', 'randRange', 'reuse', 'transform']) delete item[key];
      if (v === 'bytes') { item.type = 'array'; item.rand = 0; }
      else item[String(v)] = v === 'transform' ? {} : ''; return { ...o };
    } } as FieldDef] : []),
  { path: ['type'], label: 'Type', kind: 'select', options: ['array', 'str', 'hex', 'base64', ...(noise ? ['exp'] : [])] },
  ...(isTcp || noise ? [{ path: ['delay'], label: 'Delay', kind: noise ? 'text' : 'number' } as FieldDef] : []),
  { path: ['rand'], label: 'Rand', kind: noise ? 'text' : 'number', showIf: (_, ctx) => ctx?.value.type === 'array' && ctx?.value.reuse === undefined && ctx?.value.transform === undefined },
  { path: ['randRange'], label: 'Rand Range', kind: 'text', showIf: (_, ctx) => ctx?.value.type === 'array' && ctx?.value.reuse === undefined && ctx?.value.transform === undefined },
  { path: ['packet'], label: 'Packet', kind: 'json', showIf: (_, ctx) => ctx?.value.type === 'array' && ctx?.value.reuse === undefined && ctx?.value.transform === undefined },
  { path: ['packet'], label: 'Packet', kind: 'text', showIf: (_, ctx) => ctx?.value.type !== 'array' && ctx?.value.reuse === undefined && ctx?.value.transform === undefined },
  ...(!noise ? [
    { path: ['reuse'], label: 'Reuse', kind: 'text', showIf: (_, c) => c?.value?.reuse !== undefined } as FieldDef,
    { path: ['transform'], label: 'Transform', kind: 'json', showIf: (_, c) => c?.value?.transform !== undefined } as FieldDef,
    { path: ['capture'], label: 'Capture', kind: 'text', clearValue: '' } as FieldDef,
  ] : []),
];
const group = (name: string, isTcp: boolean): FieldDef => ({
  path: ['settings', name], label: name, kind: 'array', showIf: maskType(['header-custom']),
  defaults: isTcp ? [] : { type: 'array', rand: 0, randRange: '0-255', packet: [] },
  fields: isTcp ? [{ path: [], label: 'Packets', kind: 'array',
    defaults: { type: 'array', delay: 0, rand: 0, randRange: '0-255', packet: [] }, fields: packets(true) }] : packets(false),
});
const sudoku = ['sudoku'];
const common: FieldDef[] = [
  { ...settings('password', 'Password', 'text', ['xmc', 'sudoku', 'salamander']), generate: 'password' },
  settings('ascii', 'ASCII', 'text', sudoku),
  settings('customTable', 'Custom Table', 'text', sudoku),
  settings('customTables', 'Custom Tables', 'list', sudoku),
  settings('paddingMin', 'Padding Min', 'number', sudoku),
  settings('paddingMax', 'Padding Max', 'number', sudoku),
];
const tcpFields: FieldDef[] = [
  maskSelector(tcp),
  settings('packets', 'Packets', 'combobox', ['fragment'], ['tlshello', '1-3', '1-5']),
  settings('lengths', 'Lengths', 'list', ['fragment']),
  settings('delays', 'Delays', 'list', ['fragment']),
  settings('maxSplit', 'Max Split', 'text', ['fragment']),
  settings('hostname', 'Hostname', 'text', ['xmc']),
  ...common,
  { path: ['settings', 'profiles'], label: 'Profiles', kind: 'array', showIf: maskType(['xmc']),
    defaults: { username: '', uuid: '', texturesValue: '', texturesSignature: '' }, fields: [
      { path: ['username'], label: 'Username', kind: 'text' },
      { path: ['uuid'], label: 'UUID', kind: 'text' },
      { path: ['texturesValue'], label: 'Textures Value', kind: 'text' },
      { path: ['texturesSignature'], label: 'Textures Signature', kind: 'text' },
    ] },
  group('clients', true), group('servers', true), group('errors', true),
];
const udpFields: FieldDef[] = [
  maskSelector(udp),
  ...common,
  settings('header', 'Header', 'select', ['mkcp-legacy'], ['', 'dns', 'dtls', 'srtp', 'utp', 'wechat', 'wireguard']),
  settings('value', 'Value', 'text', ['mkcp-legacy']),
  settings('dgram', 'Dgram', 'boolean', ['xicmp']),
  settings('ips', 'IPs', 'list', ['xicmp']),
  settings('url', 'URL', 'text', ['realm']),
  settings('stunServers', 'STUN Servers', 'list', ['realm']),
  settings('ipMode', 'IP Mode', 'select', ['realm'], ['dual', 'v4', 'v6']),
  { path: ['settings', 'portMapping', 'enabled'], label: 'Port Mapping', kind: 'boolean', showIf: maskType(['realm']) },
  { path: ['settings', 'portMapping', 'timeout'], label: 'Mapping Timeout', kind: 'number', showIf: maskType(['realm']) },
  { path: ['settings', 'portMapping', 'lifetime'], label: 'Mapping Lifetime', kind: 'number', showIf: maskType(['realm']) },
  { path: ['settings', 'tlsConfig', 'serverName'], label: 'Server Name', kind: 'text', showIf: maskType(['realm']) },
  { path: ['settings', 'tlsConfig', 'alpn'], label: 'ALPN', kind: 'list', showIf: maskType(['realm']) },
  { path: ['settings', 'tlsConfig', 'fingerprint'], label: 'Fingerprint', kind: 'combobox', showIf: maskType(['realm']),
    options: ['chrome', 'firefox', 'safari', 'ios', 'android', 'edge', '360', 'qq', 'random', 'randomized', 'unsafe'] },
  { path: ['settings', 'tlsConfig', 'allowInsecure'], label: 'Allow Insecure', kind: 'boolean', showIf: maskType(['realm']) },
  { ...settings('modeUI', 'Mode', 'select', ['salamander'], ['salamander', 'gecko']), uiOnly: true,
    read: (_, o, p) => getPath(o, [...p.slice(0, -1), 'packetSize']) === undefined ? 'salamander' : 'gecko',
    onChange: (o, v, p) => setPath(o, [...p.slice(0, -1), 'packetSize'], v === 'gecko' ? '512-1200' : undefined) },
  { ...settings('packetSize', 'Packet Size', 'text', ['salamander']),
    showIf: (o, c) => maskType(['salamander'])(o, c) && !!c?.value?.settings?.packetSize },
  { ...settings('mode', 'Mode', 'multiSelect', ['udphop'], ['intervalRemote', 'perConnRemote', 'intervalLocal']),
    read: value => typeof value === 'string' ? value.split(',').filter(Boolean) : value,
    write: value => Array.isArray(value) ? value.join(',') : value },
  settings('mode', 'Mode', 'select', ['header-custom'], ['prefix', 'standalone']),
  settings('interval', 'Interval', 'text', ['udphop']),
  settings('remotePorts', 'Remote Ports', 'text', ['udphop']),
  settings('remoteIPs', 'Remote IPs', 'list', ['udphop']),
  settings('allowedSourceIPs', 'Allowed Source IPs', 'list', ['filter']),
  settings('blockedSourceIPs', 'Blocked Source IPs', 'list', ['filter']),
  { path: ['settings', 'domains'], label: 'Domains', kind: 'array', showIf: maskType(['xdns']),
    defaults: { names: [], types: [] }, fields: [
      { path: ['names'], label: 'Names', kind: 'list' },
      { path: ['types'], label: 'Record Types', kind: 'numberList' },
      { path: ['edns0'], label: 'EDNS0', kind: 'number' },
      { path: ['lenLimit'], label: 'Length Limit', kind: 'number' },
      { path: ['labelLimit'], label: 'Label Limit', kind: 'number' },
    ] },
  { path: ['settings', 'resolvers'], label: 'Resolvers', kind: 'array', showIf: maskType(['xdns']), defaults: { addrs: [] }, fields: [
    { path: ['addrs'], label: 'Addresses', kind: 'list' },
    { path: ['worker'], label: 'Workers', kind: 'number' },
    { path: ['tlsConfig'], label: 'DoH TLS', kind: 'json' },
    { path: ['quicConfig'], label: 'DoH QUIC', kind: 'json' },
  ] },
  settings('extraPoll', 'Extra Poll', 'number', ['xdns']),
  settings('reset', 'Reset', 'text', ['noise']),
  settings('script', 'Script', 'text', ['noise']),
  { path: ['settings', 'noise'], label: 'Noise', kind: 'array', showIf: maskType(['noise']),
    defaults: { type: 'array', rand: '1-8192', randRange: '0-255', delay: '10-20' }, fields: packets(false, true) },
  group('client', false), group('server', false),
];
const quic = [...base, 'quicParams'];
export const quicDefaults = {
  congestion: 'bbr', debug: false, maxIdleTimeout: 30, keepAlivePeriod: 10, disablePathMTUDiscovery: false,
  maxIncomingStreams: 1024, initStreamReceiveWindow: 8388608, maxStreamReceiveWindow: 8388608,
  initConnectionReceiveWindow: 20971520, maxConnectionReceiveWindow: 20971520,
};
const congestion = (values: string[]) => (value: Outbound) => values.includes(value.streamSettings?.finalmask?.quicParams?.congestion);
export const finalmaskFields: FieldDef[] = [{ path: base, label: 'Final Mask', kind: 'section', fields: [
  { path: [...base, 'tcp'], label: 'TCP Masks', kind: 'array',
    defaults: { type: 'fragment', settings: { packets: '1-3', lengths: ['100-200'], delays: [], maxSplit: '' } }, fields: tcpFields },
  { path: [...base, 'udp'], label: 'UDP Masks', kind: 'array', defaults: { type: 'salamander', settings: { password: '' } },
    fields: udpFields },
  { path: quic, label: 'QUIC Parameters', kind: 'toggle', defaults: quicDefaults, fields: [
    { path: [...quic, 'congestion'], label: 'Congestion', kind: 'select', options: ['reno', 'bbr', 'brutal', 'force-brutal'] },
    { path: [...quic, 'bbrProfile'], label: 'BBR Profile', kind: 'select', options: ['conservative', 'standard', 'aggressive'],
      showIf: congestion(['bbr']) },
    { path: [...quic, 'debug'], label: 'Debug', kind: 'boolean' },
    { path: [...quic, 'brutalUp'], label: 'Brutal Up', kind: 'text', showIf: congestion(['brutal', 'force-brutal']) },
    { path: [...quic, 'brutalDown'], label: 'Brutal Down', kind: 'text', showIf: congestion(['brutal', 'force-brutal']) },
    { path: [...quic, 'brutalDisableLossCompensation'], label: 'Disable Loss Compensation', kind: 'boolean',
      showIf: congestion(['brutal', 'force-brutal']) },
    { path: [...quic, 'maxIdleTimeout'], label: 'Max Idle Timeout', kind: 'number' },
    { path: [...quic, 'keepAlivePeriod'], label: 'Keep Alive Period', kind: 'number' },
    { path: [...quic, 'disablePathMTUDiscovery'], label: 'Disable Path MTU Discovery', kind: 'boolean' },
    { path: [...quic, 'disableChromeParrot'], label: 'Disable Chrome Parrot', kind: 'boolean' },
    { path: [...quic, 'disableGSO'], label: 'Disable GSO', kind: 'boolean' },
    { path: [...quic, 'disableStatelessReset'], label: 'Disable Stateless Reset', kind: 'boolean' },
    { path: [...quic, 'maxIncomingStreams'], label: 'Max Incoming Streams', kind: 'number' },
    { path: [...quic, 'initStreamReceiveWindow'], label: 'Initial Stream Receive Window', kind: 'number' },
    { path: [...quic, 'maxStreamReceiveWindow'], label: 'Max Stream Receive Window', kind: 'number' },
    { path: [...quic, 'initConnectionReceiveWindow'], label: 'Initial Connection Receive Window', kind: 'number' },
    { path: [...quic, 'maxConnectionReceiveWindow'], label: 'Max Connection Receive Window', kind: 'number' },
  ] },
] }];
