import type { FieldDef } from '../../types';
import { array, field, section } from './common';

const settings = (name: string, kind: FieldDef['kind'] = 'text', options?: string[]) => field(`settings.${name}`, kind, options);
const accounts = () => array('settings.accounts', [field('user'), field('pass')]);
const fallbacks = () => array('settings.fallbacks', [
  field('name'), field('alpn'), field('path'), field('dest', 'json'), field('xver', 'number'),
]);
export const protocolFields: FieldDef[] = [
  section('masque', [settings('address', 'list'), settings('mtu', 'number')], o => o.protocol === 'masque'),
  section('amneziawg', [
    ...['privateKey', 'subnetIp', 'primaryDns', 'secondaryDns', 'externalInterface', 'ipv6Subnet',
      'ipv6ExternalInterface', 'h1', 'h2', 'h3', 'h4', 'i1', 'i2', 'i3', 'i4', 'i5', 'headerProtectionKey',
      'contentPaddingAddition', 'rekeyAfterTime', 'rekeyTimeout', 'rejectAfterTime', 'keepaliveTimeout',
      'maxHandshakeAttempts'].map(name => settings(`server.${name}`)),
    ...['subnetCidr', 'mtu', 'jc', 'jmin', 'jmax', 's1', 's2', 's3', 's4']
      .map(name => settings(`server.${name}`, 'number')),
    ...['ipv6Enabled', 'randomTrailers', 'disableCookies', 'kernelMode']
      .map(name => settings(`server.${name}`, 'boolean')),
  ], o => o.protocol === 'amneziawg'),
  section('tuic', [
    ...['certificate', 'private_key', 'sni', 'log_level', 'congestion_control', 'udp_relay_mode']
      .map(name => settings(`server.${name}`)),
    ...['max_idle_time', 'authentication_timeout', 'max_udp_relay_packet_size']
      .map(name => settings(`server.${name}`, 'number')),
    settings('server.zero_rtt_handshake', 'boolean'),
    settings('server.alpn', 'list'),
  ], o => o.protocol === 'tuic'),
  section('vless', [settings('decryption'), settings('encryption'), settings('testseed', 'numberList'), fallbacks()],
    o => o.protocol === 'vless'),
  section('trojan', [fallbacks()], o => o.protocol === 'trojan'),
  section('shadowsocks', [settings('method', 'combobox', ['aes-256-gcm', 'chacha20-poly1305',
    'chacha20-ietf-poly1305', 'xchacha20-ietf-poly1305', '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm']),
    settings('password'), settings('network', 'combobox', ['tcp', 'udp', 'tcp,udp']), settings('ivCheck', 'boolean')],
    o => o.protocol === 'shadowsocks'),
  section('hysteria', [settings('version', 'number')], o => o.protocol === 'hysteria'),
  section('wireguard', [settings('secretKey'), settings('mtu', 'number'), settings('subnetIp'),
    settings('subnetCidr', 'number'), settings('dns'), settings('noKernelTun', 'boolean'),
    array('settings.peers', [field('publicKey'), field('preSharedKey'), field('allowedIPs', 'list'),
      field('endpoint'), field('keepAlive', 'number')])], o => o.protocol === 'wireguard'),
  section('socks / mixed', [settings('auth', 'select', ['noauth', 'password']), accounts(),
    settings('udp', 'boolean'), settings('ip'), settings('userLevel', 'number')],
    o => ['socks', 'mixed'].includes(o.protocol)),
  section('http', [accounts(), settings('allowTransparent', 'boolean'), settings('userLevel', 'number')],
    o => o.protocol === 'http'),
  section('dokodemo-door / tunnel', [settings('address'), settings('port', 'number'), settings('network'),
    settings('timeout', 'number'), settings('followRedirect', 'boolean'), settings('userLevel', 'number'),
    settings('rewriteAddress'), settings('rewritePort', 'number'), settings('allowedNetwork'), settings('portMap', 'json')],
    o => ['dokodemo-door', 'tunnel'].includes(o.protocol)),
  section('tun', [settings('name'), settings('desc'), settings('mtu', 'number'), settings('gateway', 'list'),
    settings('dns', 'list'), settings('userLevel', 'number'), settings('autoSystemRoutingTable', 'list'),
    settings('autoOutboundsInterface'), settings('autoSystemDnsToGateway', 'boolean'),
    settings('autoSystemWfpBlockLeak', 'list')], o => o.protocol === 'tun'),
  section('mtproto', [settings('fakeTlsDomain'), settings('domainFronting.ip'), settings('domainFronting.port', 'number'),
    settings('domainFronting.proxyProtocol', 'boolean'), settings('proxyProtocolListener', 'boolean'), settings('preferIp'),
    settings('debug', 'boolean'), settings('throttleMaxConnections', 'number'),
    settings('pendingHandshakesMaxPerIp', 'number'), settings('routeThroughXray', 'boolean'), settings('outboundTag'),
    settings('publicIpv4'), settings('publicIpv6')], o => o.protocol === 'mtproto'),
];
