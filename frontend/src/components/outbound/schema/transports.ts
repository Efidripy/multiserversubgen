import type { FieldDef, Outbound, Path } from '../types';
import { fingerprints } from './security';

type Kind = FieldDef['kind'];
const base = (name: string): Path => ['streamSettings', `${name}Settings`];
const f = (path: Path, label: string, kind: Kind = 'text', options?: string[]): FieldDef => ({ path, label, kind, options });
const at = (name: string, key: string, label: string, kind: Kind = 'text', options?: string[]): FieldDef =>
  f([...base(name), ...key.split('.')], label, kind, options);
const section = (label: string, fields: FieldDef[]): FieldDef => ({ path: [], label, kind: 'section', fields });
const equals = (name: string, key: string, value: unknown) => (o: Outbound) => o.streamSettings?.[`${name}Settings`]?.[key] === value;
const x = (key: string, label: string, kind: Kind = 'text', options?: string[]) => at('xhttp', key, label, kind, options);
const placement = ['', 'path', 'header', 'cookie', 'query'];
const xmuxDefaults = { maxConcurrency: '', maxConnections: 3, cMaxReuseTimes: 0, hMaxRequestTimes: '600-900',
  hMaxReusableSecs: '1800-3000', hKeepAlivePeriod: 0 };
const download = [...base('xhttp'), 'downloadSettings'];
const downloadField = (key: string, label: string, kind: Kind = 'text', options?: string[]): FieldDef =>
  f([...download, ...key.split('.')], label, kind, options);
const downloadSecurity = (type: string) => (o: Outbound) => o.streamSettings?.xhttpSettings?.downloadSettings?.security === type;
const downloadFields: FieldDef[] = [
  downloadField('address', 'Address'), downloadField('port', 'Port', 'number'),
  downloadField('xhttpSettings.host', 'Host'), downloadField('xhttpSettings.path', 'Path'),
  { ...downloadField('security', 'Security', 'select', ['none', 'tls', 'reality']), onChange: (o, v) => {
    const d = o.streamSettings.xhttpSettings.downloadSettings; delete d.tlsSettings; delete d.realitySettings;
    if (v === 'tls') d.tlsSettings = {};
    if (v === 'reality') d.realitySettings = { fingerprint: 'chrome' }; return o; } },
  { ...downloadField('tlsSettings.serverName', 'TLS SNI'), showIf: downloadSecurity('tls') },
  ...['serverName', 'publicKey', 'fingerprint', 'shortId'].map(key => ({
    ...downloadField(`realitySettings.${key}`, `REALITY ${key}`, key === 'fingerprint' ? 'combobox' : 'text', fingerprints),
    showIf: downloadSecurity('reality'),
  })),
];
const httpMode = (o: Outbound) => !o.streamSettings?.xhttpSettings?.mode ||
  ['auto', 'packet-up'].includes(o.streamSettings.xhttpSettings.mode);
const xhttp: FieldDef[] = [
  x('host', 'Host'), x('path', 'Path'), x('mode', 'Mode', 'select', ['auto', 'packet-up', 'stream-up', 'stream-one']),
  x('headers', 'Headers', 'keyValue'), x('xPaddingBytes', 'Padding Bytes'),
  x('xPaddingObfsMode', 'Padding Obfuscation', 'boolean'),
  ...[
    x('xPaddingKey', 'Padding Key'), x('xPaddingHeader', 'Padding Header'),
    x('xPaddingPlacement', 'Padding Placement', 'select', ['', 'queryInHeader', 'header', 'cookie', 'query']),
    x('xPaddingMethod', 'Padding Method', 'select', ['', 'repeat-x', 'tokenish']),
  ].map(field => ({ ...field, showIf: equals('xhttp', 'xPaddingObfsMode', true) })),
  { ...x('uplinkHTTPMethod', 'Uplink HTTP Method', 'select'), options: o =>
    ['', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', ...(o.streamSettings?.xhttpSettings?.mode === 'packet-up' ? ['GET', 'HEAD'] : [])] },
  ...(['sessionID', 'seq'] as const).flatMap(prefix => [
    x(`${prefix}Placement`, `${prefix} Placement`, 'select', placement),
    { ...x(`${prefix}Key`, `${prefix} Key`), showIf: (o: Outbound) => {
      const value = o.streamSettings?.xhttpSettings?.[`${prefix}Placement`]; return !!value && value !== 'path';
    } },
  ]),
  x('sessionIDTable', 'Session ID Table', 'combobox',
    ['ALPHABET', 'Alphabet', 'BASE36', 'Base62', 'HEX', 'alphabet', 'base36', 'hex', 'number']),
  { ...x('sessionIDLength', 'Session ID Length'), showIf: o => !!o.streamSettings?.xhttpSettings?.sessionIDTable },
  ...[x('scMinPostsIntervalMs', 'Minimum Posts Interval'), x('scMaxEachPostBytes', 'Maximum Post Bytes'),
    x('uplinkDataPlacement', 'Uplink Data Placement', 'select', ['', 'auto', 'body', 'header', 'cookie'])]
    .map(field => ({ ...field, showIf: httpMode })),
  ...[x('uplinkDataKey', 'Uplink Data Key'), x('uplinkChunkSize', 'Uplink Chunk Size')].map(field => ({
    ...field, showIf: (o: Outbound) => httpMode(o) && !!o.streamSettings?.xhttpSettings?.uplinkDataPlacement &&
      o.streamSettings.xhttpSettings.uplinkDataPlacement !== 'body',
  })),
  { ...x('noGRPCHeader', 'No gRPC Header', 'boolean'), showIf: o => o.streamSettings?.xhttpSettings?.mode !== 'packet-up' },
  { path: [...base('xhttp'), 'xmux'], label: 'XMUX', kind: 'toggle', defaults: xmuxDefaults, fields: [
    { ...x('xmux.maxConcurrency', 'Max Concurrency'), onChange: (o, v) => {
      if (Number(v) > 0) o.streamSettings.xhttpSettings.xmux.maxConnections = 0; return o; } },
    { ...x('xmux.maxConnections', 'Max Connections'), onChange: (o, v) => {
      if (Number(v) > 0) o.streamSettings.xhttpSettings.xmux.maxConcurrency = ''; return o; } },
    x('xmux.cMaxReuseTimes', 'Max Reuse Times'), x('xmux.hMaxRequestTimes', 'Max Request Times'),
    x('xmux.hMaxReusableSecs', 'Max Reusable Seconds'), x('xmux.hKeepAlivePeriod', 'Keep Alive Period', 'number'),
  ] },
  { path: download, label: ['Separate', 'Download'].join(' '), kind: 'toggle',
    defaults: (o: Outbound) => {
      const upload = o.streamSettings?.xhttpSettings || {};
      const keys = ['host', 'headers', 'sessionIDPlacement', 'sessionIDKey', 'sessionIDTable', 'sessionIDLength',
        'seqPlacement', 'seqKey', 'xPaddingBytes', 'xPaddingObfsMode', 'xPaddingKey', 'xPaddingHeader',
        'xPaddingPlacement', 'xPaddingMethod'];
      return { network: 'xhttp', port: 443, security: 'tls', xhttpSettings: { path: upload.path || '/',
        ...Object.fromEntries(keys.filter(key => upload[key] !== undefined).map(key => [key, upload[key]])) } };
    },
    showIf: o => o.streamSettings?.xhttpSettings?.mode !== 'stream-one', fields: downloadFields },
];
const raw = (key: string, label: string, kind: Kind = 'text') => at('tcp', `header.${key}`, label, kind);
const rawFields = [raw('request.version', 'Request Version'), raw('request.method', 'Request Method'),
  raw('request.path', 'Request Path', 'list'), raw('request.headers', 'Request Headers', 'json'),
  raw('response.version', 'Response Version'), raw('response.status', 'Response Status'),
  raw('response.reason', 'Response Reason'), raw('response.headers', 'Response Headers', 'json')];
const masquerade = [...base('hysteria'), 'masquerade'];
const masq = (key: string, label: string, kind: Kind = 'text', options?: string[]) => f([...masquerade, key], label, kind, options);
const masqType = (type: string) => (o: Outbound) => o.streamSettings?.hysteriaSettings?.masquerade?.type === type;
const xdrive = (key: string, label: string, kind: Kind = 'text', options?: string[]) => at('xdrive', key, label, kind, options);
export const transportFields: Record<string, FieldDef[]> = {
  tcp: [{ ...at('tcp', 'header.type', 'HTTP Camouflage', 'select', ['none', 'http']),
    onChange: (o, v) => { o.streamSettings.tcpSettings.header = v === 'http'
      ? { type: 'http', request: { version: '1.1', method: 'GET', path: ['/'], headers: {} },
        response: { version: '1.1', status: '200', reason: 'OK', headers: {} } } : { type: 'none' }; return o; } },
    section('HTTP Camouflage Settings', rawFields.map(field => ({ ...field,
      showIf: o => o.streamSettings?.tcpSettings?.header?.type === 'http' })))],
  kcp: [at('kcp', 'mtu', 'MTU', 'number'), at('kcp', 'tti', 'TTI (ms)', 'number'),
    at('kcp', 'uplinkCapacity', 'Uplink (Mbps)', 'number'), at('kcp', 'downlinkCapacity', 'Downlink (Mbps)', 'number'),
    at('kcp', 'cwndMultiplier', 'CWND Multiplier', 'number'), at('kcp', 'maxSendingWindow', 'Max Sending Window', 'number')],
  ws: [at('ws', 'host', 'Host'), at('ws', 'path', 'Path'), at('ws', 'heartbeatPeriod', 'Heartbeat Period', 'number'),
    at('ws', 'headers', 'Headers', 'keyValue')],
  grpc: [at('grpc', 'serviceName', 'Service Name'), at('grpc', 'authority', 'Authority'),
    at('grpc', 'multiMode', 'Multi Mode', 'boolean')],
  httpupgrade: [at('httpupgrade', 'host', 'Host'), at('httpupgrade', 'path', 'Path'),
    at('httpupgrade', 'headers', 'Headers', 'keyValue')],
  xhttp,
  xdrive: [xdrive('service', 'Service', 'select', ['google-drive', 'local', 'template', 's3']),
    xdrive('remoteFolder', 'Remote Folder'), xdrive('key', 'Key'),
    { ...xdrive('secrets', 'Secrets', 'list'), showIf: o => o.streamSettings?.xdriveSettings?.service !== 'local' },
    ...[xdrive('s3.endpoint', 'S3 Endpoint'), xdrive('s3.region', 'S3 Region'), xdrive('s3.bucket', 'S3 Bucket'),
      xdrive('s3.pathStyle', 'S3 Path Style', 'boolean')].map(field => ({ ...field, showIf: equals('xdrive', 'service', 's3') })),
    { ...xdrive('template', 'Template', 'json'), showIf: equals('xdrive', 'service', 'template') },
    ...[f(['streamSettings', 'address'], 'Front'), f(['streamSettings', 'port'], 'Front Port', 'number')]
      .map(field => ({ ...field, showIf: (o: Outbound) => o.streamSettings?.xdriveSettings?.service !== 'local' })),
    ...['segmentBytes', 'flushIntervalMs', 'pollIntervalMs', 'maxPollIntervalMs', 'eagerWindowMs', 'holeTimeoutMs',
      'sessionTtlSeconds', 'concurrency'].map(key => xdrive(key, key, 'number'))],
  hysteria: [at('hysteria', 'version', 'Version', 'number'), at('hysteria', 'auth', 'Auth Password'),
    at('hysteria', 'udpIdleTimeout', 'UDP Idle Timeout', 'number'),
    { path: masquerade, label: 'Masquerade', kind: 'toggle',
      defaults: { type: '', dir: '', url: '', rewriteHost: false, insecure: false, content: '', headers: {}, statusCode: 0 },
      fields: [masq('type', 'Type', 'select', ['', 'proxy', 'file', 'string']),
        ...[masq('url', 'Upstream URL'), masq('rewriteHost', 'Rewrite Host', 'boolean'),
          masq('xForwarded', 'X-Forwarded', 'boolean'), masq('insecure', 'Skip TLS Verify', 'boolean')]
          .map(field => ({ ...field, showIf: masqType('proxy') })),
        { ...masq('dir', 'Directory'), showIf: masqType('file') },
        ...[masq('statusCode', 'Status Code', 'number'), masq('content', 'Body'), masq('headers', 'Headers', 'keyValue')]
          .map(field => ({ ...field, showIf: masqType('string') }))] }],
  masque: [at('masque', 'host', 'Host'), at('masque', 'path', 'Path'),
    { path: [...base('masque'), 'warp'], label: 'WARP', kind: 'toggle',
      defaults: { privateKey: '', publicKey: '', address: [] },
      onChange: (o, v) => { if (v) { delete o.streamSettings.masqueSettings.user; delete o.streamSettings.masqueSettings.pass; }
        return o; }, fields: [at('masque', 'warp.privateKey', 'Private Key'),
        at('masque', 'warp.publicKey', 'Public Key'), at('masque', 'warp.address', 'Address', 'list')] },
    ...[at('masque', 'user', 'Username'), at('masque', 'pass', 'Password')]
      .map(field => ({ ...field, showIf: (o: Outbound) => o.streamSettings?.masqueSettings?.warp === undefined })),
    at('masque', 'headers', 'Headers', 'keyValue')],
};
export const transportDefaults: Record<string, Outbound> = {
  tcp: { header: { type: 'none' } },
  kcp: { mtu: 1350, tti: 20, uplinkCapacity: 5, downlinkCapacity: 20, cwndMultiplier: 1, maxSendingWindow: 2097152 },
  ws: { host: '', path: '/', headers: {}, heartbeatPeriod: 0 }, grpc: { serviceName: '', authority: '', multiMode: false },
  httpupgrade: { host: '', path: '/', headers: {} }, xhttp: { host: '', path: '/', mode: 'auto', headers: {},
    xPaddingBytes: '100-1000', xPaddingObfsMode: false }, xdrive: { service: 'google-drive', remoteFolder: '' },
  hysteria: { version: 2, auth: '', udpIdleTimeout: 60 }, masque: {},
};
