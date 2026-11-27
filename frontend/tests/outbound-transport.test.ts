import { describe, expect, it } from 'vitest';
import type { FieldDef, Outbound } from '../src/components/outbound/types';
import { transportFields } from '../src/components/outbound/schema/transports';
import { securityFields } from '../src/components/outbound/schema/security';

function flatten(fields: FieldDef[]): FieldDef[] {
  return fields.flatMap(field => [field, ...flatten(field.fields || [])]);
}
const required: Record<string, string> = {
  tcp: ['header.type header.request.version header.request.method header.request.path header.request.headers',
    'header.response.version header.response.status header.response.reason header.response.headers',
  ].join(' '),
  kcp: 'mtu tti uplinkCapacity downlinkCapacity cwndMultiplier maxSendingWindow',
  ws: 'host path heartbeatPeriod headers',
  grpc: 'serviceName authority multiMode',
  httpupgrade: 'host path headers',
  xhttp: ['host path mode xPaddingBytes headers xPaddingObfsMode xPaddingKey xPaddingHeader xPaddingPlacement',
    'xPaddingMethod uplinkHTTPMethod sessionIDPlacement sessionIDKey sessionIDTable sessionIDLength',
    'seqPlacement seqKey scMinPostsIntervalMs scMaxEachPostBytes uplinkDataPlacement uplinkDataKey',
    'uplinkChunkSize noGRPCHeader xmux.maxConcurrency xmux.maxConnections xmux.cMaxReuseTimes',
    'xmux.hMaxRequestTimes xmux.hMaxReusableSecs xmux.hKeepAlivePeriod downloadSettings.address',
    'downloadSettings.port downloadSettings.xhttpSettings.host downloadSettings.xhttpSettings.path',
    'downloadSettings.security downloadSettings.tlsSettings.serverName',
    'downloadSettings.realitySettings.serverName downloadSettings.realitySettings.publicKey',
    'downloadSettings.realitySettings.fingerprint downloadSettings.realitySettings.shortId',
  ].join(' '),
  xdrive: ['service remoteFolder secrets s3.endpoint s3.region s3.bucket s3.pathStyle template key segmentBytes',
    'flushIntervalMs pollIntervalMs maxPollIntervalMs eagerWindowMs holeTimeoutMs sessionTtlSeconds',
    'concurrency',
  ].join(' '),
  hysteria: ['version auth udpIdleTimeout masquerade.type masquerade.url masquerade.rewriteHost',
    'masquerade.xForwarded masquerade.insecure masquerade.dir masquerade.statusCode masquerade.content',
    'masquerade.headers',
  ].join(' '),
  masque: 'host path warp.privateKey warp.publicKey warp.address user pass headers',
  tls: 'serverName fingerprint alpn echConfigList verifyPeerCertByName pinnedPeerCertSha256 useSystemCA',
  reality: 'serverName fingerprint shortId spiderX publicKey mldsa65Verify',
};
function find(network: string, suffix: string): FieldDef {
  const fields = transportFields[network] || securityFields[network];
  const path = `streamSettings.${network}Settings.${suffix}`;
  const field = flatten(fields).find(item => Array.isArray(item.path) && item.path.join('.') === path);
  expect(field, path).toBeDefined();
  return field!;
}
function visible(field: FieldDef, settings: Outbound): boolean {
  return field.showIf?.({ streamSettings: settings }, undefined) ?? true;
}
describe('outbound transport and security schemas', () => {
  it('describes every required path', () => {
    for (const [network, paths] of Object.entries(required)) for (const path of paths.split(' ')) find(network, path);
    const paths = flatten(transportFields.xdrive).map(field => Array.isArray(field.path) && field.path.join('.'));
    expect(paths).toContain('streamSettings.address');
    expect(paths).toContain('streamSettings.port');
  });
  it('applies visibility conditions', () => {
    expect(visible(find('tcp', 'header.request.method'), { tcpSettings: { header: { type: 'none' } } })).toBe(false);
    expect(visible(find('tcp', 'header.request.method'), { tcpSettings: { header: { type: 'http' } } })).toBe(true);
    expect(visible(find('xhttp', 'xPaddingKey'), { xhttpSettings: { xPaddingObfsMode: false } })).toBe(false);
    expect(visible(find('xhttp', 'xPaddingKey'), { xhttpSettings: { xPaddingObfsMode: true } })).toBe(true);
    expect(visible(find('xhttp', 'sessionIDKey'), { xhttpSettings: { sessionIDPlacement: 'path' } })).toBe(false);
    expect(visible(find('xhttp', 'sessionIDKey'), { xhttpSettings: { sessionIDPlacement: 'header' } })).toBe(true);
    expect(visible(find('xhttp', 'scMaxEachPostBytes'), { xhttpSettings: { mode: 'stream-one' } })).toBe(false);
    expect(visible(find('xhttp', 'noGRPCHeader'), { xhttpSettings: { mode: 'packet-up' } })).toBe(false);
    expect(visible(find('hysteria', 'masquerade.url'), { hysteriaSettings: { masquerade: { type: 'proxy' } } })).toBe(true);
    expect(visible(find('hysteria', 'masquerade.url'), { hysteriaSettings: { masquerade: { type: 'file' } } })).toBe(false);
    expect(visible(find('masque', 'user'), { masqueSettings: { warp: {} } })).toBe(false);
    expect(visible(find('xdrive', 's3.bucket'), { xdriveSettings: { service: 's3' } })).toBe(true);
    expect(visible(find('xhttp', 'downloadSettings.realitySettings.shortId'),
      { xhttpSettings: { downloadSettings: { security: 'tls' } } })).toBe(false);
  });
});
