import type { FieldDef, Path } from '../types';

const fingerprints = ['chrome', 'firefox', 'safari', 'ios', 'android', 'edge', '360', 'qq', 'random',
  'randomized', 'randomizednoalpn', 'unsafe'];
const strategies = ['AsIs', 'UseIP', 'UseIPv4', 'UseIPv6', 'UseIPv4v6', 'UseIPv6v4', 'ForceIP', 'ForceIPv4',
  'ForceIPv6', 'ForceIPv4v6', 'ForceIPv6v4'];
const networks = ['tcp', 'udp', 'tcp,udp'];
const methods = ['aes-128-gcm', 'aes-256-gcm', 'chacha20-poly1305', 'chacha20-ietf-poly1305',
  'xchacha20-ietf-poly1305', '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm', '2022-blake3-chacha20-poly1305',
  'none', 'plain'];
const choices: Record<string, string[]> = {
  fingerprint: fingerprints, minVersion: ['1.0', '1.1', '1.2', '1.3'], maxVersion: ['1.0', '1.1', '1.2', '1.3'],
  cipherSuites: ['TLS_AES_128_GCM_SHA256', 'TLS_AES_256_GCM_SHA384', 'TLS_CHACHA20_POLY1305_SHA256',
    'TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256', 'TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256',
    'TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384', 'TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384'],
  domainStrategy: strategies, targetStrategy: strategies, tproxy: ['off', 'redirect', 'tproxy'],
  tcpcongestion: ['bbr', 'cubic', 'reno'], addressPortStrategy: ['none', 'SrvPortOnly', 'SrvAddressOnly',
    'SrvPortAndAddress', 'TxtPortOnly', 'TxtAddressOnly', 'TxtPortAndAddress'],
  xPaddingPlacement: ['queryInHeader', 'header', 'cookie', 'query'], xPaddingMethod: ['repeat-x', 'tokenish'],
  sessionIDPlacement: ['path', 'header', 'cookie', 'query'], seqPlacement: ['path', 'header', 'cookie', 'query'],
  uplinkDataPlacement: ['auto', 'body', 'header', 'cookie'],
  uplinkHTTPMethod: ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'GET', 'HEAD'],
  allowedNetwork: networks, trafficReset: ['never', 'hourly', 'daily', 'weekly', 'monthly'],
  preferIp: ['prefer-ipv6', 'prefer-ipv4', 'only-ipv6', 'only-ipv4'],
  logLevel: ['debug', 'info', 'warning', 'error', 'none'],
  congestion_control: ['bbr', 'cubic', 'new_reno'], udp_relay_mode: ['native', 'quic'],
  log_level: ['info', 'warn', 'error', 'debug'], echForceQuery: ['none', 'half', 'full'],
  shareAddrStrategy: ['node', 'listen', 'custom'], usage: ['encipherment', 'verify', 'issue'],
  ascii: ['prefer_ascii', 'prefer_entropy'],
  sessionIDTable: ['ALPHABET', 'Alphabet', 'BASE36', 'Base62', 'HEX', 'alphabet', 'base36', 'hex', 'number'],
};
const multiple: Record<string, string[]> = {
  alpn: ['h3', 'h2', 'http/1.1', 'spdy/3.1'], destOverride: ['http', 'tls', 'quic', 'fakedns'],
  curvePreferences: ['X25519', 'P256', 'P384', 'P521', 'X25519MLKEM768'],
};

// Resolve shared field names here so inbound, outbound and nested array editors use the same choices.
export function choiceField(field: FieldDef, path: Path): FieldDef {
  const name = String(path.at(-1) ?? '');
  const full = path.join('.');
  if (multiple[name] && field.kind === 'list') return { ...field, kind: 'multiSelect', options: multiple[name] };
  if (field.kind === 'boolean' || field.kind === 'section' || field.kind === 'toggle' || field.kind === 'array') return field;
  if (name === 'alpn' && field.kind === 'text') return { ...field, kind: 'combobox', options: multiple.alpn };
  if (name === 'xver') return { ...field, kind: 'select', options: ['0', '1', '2'], numericOptions: true };
  if (full.includes('customSockopt') && name === 'system') return { ...field, kind: 'select', options: ['linux', 'windows', 'darwin'] };
  if (full.includes('customSockopt') && name === 'type') return { ...field, kind: 'select', options: ['int', 'str'] };
  if (full.includes('header.request') && name === 'method') {
    return { ...field, kind: 'combobox', options: ['GET', 'POST', 'PUT', 'HEAD', 'OPTIONS', 'DELETE', 'PATCH'] };
  }
  if (name === 'proxyProtocol' && field.kind === 'number') {
    return { ...field, kind: 'select', options: ['0', '1', '2'], numericOptions: true };
  }
  if (name === 'method' && full.includes('servers') && field.label === 'Encryption') {
    return { ...field, kind: 'combobox', options: methods };
  }
  if (name === 'method' && full === 'settings.method') return { ...field, kind: 'combobox', options: methods };
  if (name === 'security' && (full.includes('users') || full === 'security') && field.label !== 'clients.vlessEncryption') {
    return { ...field, kind: field.kind === 'select' ? 'select' : 'combobox', options: ['auto', 'aes-128-gcm', 'chacha20-poly1305', 'none', 'zero'] };
  }
  if (name === 'network' && full.startsWith('settings.')) return { ...field, kind: field.kind === 'select' ? 'select' : 'combobox', options: networks };
  if (name === 'mode' && full.includes('xhttpSettings') && field.kind !== 'select') {
    return { ...field, kind: 'combobox', options: ['auto', 'packet-up', 'stream-up', 'stream-one'] };
  }
  if (name === 'type' && full.includes('kcpSettings.header')) {
    return { ...field, kind: 'combobox', options: ['none', 'srtp', 'utp', 'wechat-video', 'dtls', 'wireguard'] };
  }
  if (name === 'type' && full.includes('masquerade')) return { ...field, kind: 'combobox', options: ['proxy', 'file', 'string'] };
  if (name === 'qType') return { ...field, kind: 'combobox', options: ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'PTR', 'SRV', 'HTTPS', 'SVCB'] };
  if (name === 'flow' && field.kind === 'text') return { ...field, kind: 'combobox', options: ['xtls-rprx-vision'] };
  if (name === 'forceTls') return { ...field, kind: 'combobox', options: ['same', 'tls', 'none'] };
  if (choices[name]) return { ...field, kind: field.kind === 'select' ? 'select' : 'combobox', options: choices[name] };
  return field;
}
