import { describe, expect, it } from 'vitest';
import type { FieldDef } from '../src/components/outbound/types';
import { sockoptFields } from '../src/components/outbound/schema/sockopt';
import { muxFields } from '../src/components/outbound/schema/mux';
import { finalmaskFields } from '../src/components/outbound/schema/finalmask';

function paths(fields: FieldDef[], prefix: (string | number)[] = []): string[] {
  return fields.flatMap(field => {
    if (typeof field.path === 'function') throw new Error('Unexpected dynamic path');
    const path = [...prefix, ...field.path];
    return [path.join('.'), ...paths(field.fields || [], field.kind === 'array' ? [...path, '*'] : prefix)];
  });
}
function find(fields: FieldDef[], path: string): FieldDef | undefined {
  for (const field of fields) {
    if (Array.isArray(field.path) && field.path.join('.') === path) return field;
    const nested = find(field.fields || [], path);
    if (nested) return nested;
  }
}
describe('outbound extra schemas', () => {
  it('describes the checklist paths', () => {
    const required = [
      ...`dialerProxy domainStrategy addressPortStrategy tcpKeepAliveInterval tcpFastOpen tcpMptcp penetrate mark interface
        tproxy tcpcongestion tcpUserTimeout tcpKeepAliveIdle tcpMaxSeg tcpWindowClamp happyEyeballs.tryDelayMs
        happyEyeballs.prioritizeIPv6 happyEyeballs.interleave happyEyeballs.maxConcurrentTry customSockopt
        customSockopt.*.system customSockopt.*.level customSockopt.*.opt customSockopt.*.type customSockopt.*.value`
        .trim().split(/\s+/).map(p => `streamSettings.sockopt.${p}`),
      ...'enabled concurrency xudpConcurrency xudpProxyUDP443'.split(' ').map(p => `mux.${p}`),
      ...`type settings.packets settings.lengths settings.delays settings.maxSplit settings.hostname settings.password
        settings.ascii settings.customTable settings.customTables settings.paddingMin settings.paddingMax settings.profiles
        settings.profiles.*.username settings.profiles.*.uuid settings.profiles.*.texturesValue
        settings.profiles.*.texturesSignature settings.clients settings.servers settings.errors`
        .trim().split(/\s+/).map(p => `streamSettings.finalmask.tcp.*.${p}`),
      ...`type settings.password settings.ascii settings.customTable settings.customTables settings.paddingMin settings.paddingMax
        settings.header settings.value settings.dgram settings.ips settings.url settings.stunServers settings.ipMode
        settings.portMapping.enabled settings.portMapping.timeout settings.portMapping.lifetime settings.tlsConfig.serverName
        settings.tlsConfig.alpn settings.tlsConfig.fingerprint settings.tlsConfig.allowInsecure settings.packetSize settings.mode
        settings.interval settings.remotePorts settings.remoteIPs settings.allowedSourceIPs settings.blockedSourceIPs
        settings.domains settings.domains.*.names settings.domains.*.types settings.domains.*.edns0
        settings.domains.*.lenLimit settings.domains.*.labelLimit settings.resolvers settings.resolvers.*.addrs
        settings.resolvers.*.worker settings.resolvers.*.tlsConfig settings.resolvers.*.quicConfig settings.extraPoll
        settings.reset settings.script settings.noise settings.client settings.server`
        .trim().split(/\s+/).map(p => `streamSettings.finalmask.udp.*.${p}`),
      ...['clients.*.*', 'servers.*.*', 'errors.*.*'].flatMap(group =>
        'type delay reuse transform rand randRange packet capture'.split(' ')
          .map(p => `streamSettings.finalmask.tcp.*.settings.${group}.${p}`)),
      ...['client.*', 'server.*'].flatMap(group => 'type reuse transform rand randRange packet capture'.split(' ')
        .map(p => `streamSettings.finalmask.udp.*.settings.${group}.${p}`)),
      ...'type delay rand randRange packet'.split(' ').map(p => `streamSettings.finalmask.udp.*.settings.noise.*.${p}`),
      ...`congestion bbrProfile debug brutalUp brutalDown brutalDisableLossCompensation udpHop.ports udpHop.interval
        maxIdleTimeout keepAlivePeriod disablePathMTUDiscovery disableChromeParrot disableGSO disableStatelessReset
        maxIncomingStreams initStreamReceiveWindow maxStreamReceiveWindow initConnectionReceiveWindow maxConnectionReceiveWindow`
        .trim().split(/\s+/).map(p => `streamSettings.finalmask.quicParams.${p}`),
    ];
    const described = paths([...sockoptFields([]), ...muxFields, ...finalmaskFields]);
    expect(required.filter(path => !described.includes(path))).toEqual([]);
  });
  it('applies protocol, mask and congestion visibility', () => {
    expect(muxFields[0].showIf?.({ protocol: 'vless', settings: { flow: 'xtls-rprx-vision' } }, undefined)).toBe(false);
    expect(muxFields[0].showIf?.({ protocol: 'vmess', streamSettings: { network: 'xhttp' } }, undefined)).toBe(false);
    expect(muxFields[0].showIf?.({ protocol: 'vmess' }, undefined)).toBe(true);
    expect(find(sockoptFields([]), 'streamSettings.sockopt.domainStrategy')?.showIf?.({ protocol: 'freedom' }, undefined))
      .toBe(false);
    const hostname = find(finalmaskFields, 'settings.hostname');
    const context = { path: ['streamSettings', 'finalmask', 'tcp', 0], value: { type: 'xmc' }, index: 0 };
    expect(hostname?.showIf?.({ streamSettings: { finalmask: { tcp: [{ type: 'xmc' }] } } }, context)).toBe(true);
    expect(hostname?.showIf?.({ streamSettings: { finalmask: { tcp: [{ type: 'fragment' }] } } }, context)).toBe(false);
    const bbr = find(finalmaskFields, 'streamSettings.finalmask.quicParams.bbrProfile');
    expect(bbr?.showIf?.({ streamSettings: { finalmask: { quicParams: { congestion: 'bbr' } } } }, undefined)).toBe(true);
    expect(bbr?.showIf?.({ streamSettings: { finalmask: { quicParams: { congestion: 'brutal' } } } }, undefined)).toBe(false);
  });
});
