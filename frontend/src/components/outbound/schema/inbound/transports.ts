import type { FieldDef } from '../../types';
import { array, field, section } from './common';

const f = (base: string, key: string, kind: FieldDef['kind'] = 'text', options?: string[]) =>
  field(`streamSettings.${base}Settings.${key}`, kind, options);
const network = (names: string[]) => (o: Record<string, any>) => names.includes(o.streamSettings?.network || 'tcp');
const raw = (key: string, kind: FieldDef['kind'] = 'text') => f('tcp', key, kind);
export const transportFields: FieldDef[] = [
  field('streamSettings.network', 'combobox', ['tcp', 'raw', 'kcp', 'ws', 'grpc', 'httpupgrade', 'xhttp', 'hysteria']),
  section('tcp / raw', [raw('acceptProxyProtocol', 'boolean'), f('tcp', 'header.type', 'select', ['none', 'http']),
    raw('header.request.version'), raw('header.request.method'), raw('header.request.path', 'list'),
    raw('header.request.headers', 'json'), raw('header.response.version'), raw('header.response.status'),
    raw('header.response.reason'), raw('header.response.headers', 'json')], network(['tcp', 'raw'])),
  section('kcp', ['mtu', 'tti', 'uplinkCapacity', 'downlinkCapacity', 'cwndMultiplier', 'maxSendingWindow',
    'readBufferSize', 'writeBufferSize'].map(k => f('kcp', k, 'number')).concat([
    f('kcp', 'congestion', 'boolean'), f('kcp', 'header.type'), f('kcp', 'seed')]), network(['kcp'])),
  section('ws', [f('ws', 'acceptProxyProtocol', 'boolean'), f('ws', 'host'), f('ws', 'path'),
    f('ws', 'heartbeatPeriod', 'number'), f('ws', 'headers', 'json')], network(['ws'])),
  section('grpc', [f('grpc', 'serviceName'), f('grpc', 'authority'), f('grpc', 'multiMode', 'boolean'),
    f('grpc', 'idle_timeout', 'number'), f('grpc', 'health_check_timeout', 'number'),
    f('grpc', 'permit_without_stream', 'boolean'), f('grpc', 'initial_windows_size', 'number')], network(['grpc'])),
  section('httpupgrade', [f('httpupgrade', 'acceptProxyProtocol', 'boolean'), f('httpupgrade', 'host'),
    f('httpupgrade', 'path'), f('httpupgrade', 'headers', 'json')], network(['httpupgrade'])),
  section('xhttp', [
    ...['host', 'path', 'mode', 'xPaddingBytes', 'uplinkHTTPMethod', 'xPaddingKey', 'xPaddingHeader',
      'xPaddingPlacement', 'xPaddingMethod', 'sessionIDPlacement', 'sessionIDKey', 'sessionIDTable', 'sessionIDLength',
      'seqPlacement', 'seqKey', 'uplinkDataPlacement', 'uplinkDataKey', 'scMaxEachPostBytes', 'scMinPostsIntervalMs',
      'scStreamUpServerSecs'].map(k => f('xhttp', k)),
    ...['scMaxBufferedPosts', 'serverMaxHeaderBytes', 'uplinkChunkSize'].map(k => f('xhttp', k, 'number')),
    ...['xPaddingObfsMode', 'noSSEHeader', 'noGRPCHeader'].map(k => f('xhttp', k, 'boolean')),
    f('xhttp', 'headers', 'json'),
    ...['maxConcurrency', 'maxConnections', 'cMaxReuseTimes', 'hMaxRequestTimes', 'hMaxReusableSecs',
      'hKeepAlivePeriod'].map(k => f('xhttp', `xmux.${k}`)),
    f('xhttp', 'h2Params', 'json'), f('xhttp', 'downloadSettings', 'json'),
  ], network(['xhttp'])),
  section('hysteria', [f('hysteria', 'version', 'number'), f('hysteria', 'auth'),
    f('hysteria', 'udpIdleTimeout', 'number'), f('hysteria', 'masquerade.type'), f('hysteria', 'masquerade.url'),
    f('hysteria', 'masquerade.rewriteHost', 'boolean'), f('hysteria', 'masquerade.xForwarded', 'boolean'),
    f('hysteria', 'masquerade.insecure', 'boolean'), f('hysteria', 'masquerade.dir'),
    f('hysteria', 'masquerade.statusCode', 'number'), f('hysteria', 'masquerade.content'),
    f('hysteria', 'masquerade.headers', 'json')], o => network(['hysteria'])(o) || o.protocol === 'hysteria'),
  array('streamSettings.externalProxy', [field('forceTls'), field('dest'), field('port', 'number'), field('remark'),
    field('sni'), field('fingerprint'), field('alpn', 'list'), field('pinnedPeerCertSha256', 'list'),
    field('verifyPeerCertByName'), field('echConfigList'), field('cipherSuites'), field('vlessRoute'),
    field('allowInsecure', 'boolean')]),
];
