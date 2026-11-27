import { describe, expect, it } from 'vitest';
import { parseShareOutbound } from '../src/components/outbound/shareOutbound';
import { setPath as setOutboundField } from '../src/components/outbound/paths';

describe('share outbound parsing', () => {
  const vmess = btoa(JSON.stringify({ add: 'example.com', port: '443', id: 'abc', ps: 'vm', net: 'ws' }));
  it.each([
    ['vless://abc@example.com:443#name', 'vless'],
    [`vmess://${vmess}`, 'vmess'],
    ['trojan://secret@example.com:443', 'trojan'],
    ['ss://YWVzLTEyOC1nY206c2VjcmV0@example.com:443', 'shadowsocks'],
    ['ss://YWVzLTEyOC1nY206c2VjcmV0QGV4YW1wbGUuY29tOjQ0Mw', 'shadowsocks'],
    ['hy2://secret@example.com:443', 'hysteria'],
    ['hysteria2://secret@example.com:443', 'hysteria'],
    ['wg://secret@example.com:443?publickey=pub', 'wireguard'],
    ['wireguard://secret@example.com:443?publickey=pub', 'wireguard'],
  ])('parses %s', (link, protocol) => expect(parseShareOutbound(link).outbound.protocol).toBe(protocol));
  it('builds Xray transport settings and warns about inapplicable parameters', () => {
    const tcp = parseShareOutbound('vless://id@example.com:443?type=tcp&headerType=http&host=site&path=%2Fa');
    expect(tcp.outbound.settings).toEqual({ address: 'example.com', port: 443, id: 'id', flow: '', encryption: 'none' });
    expect(tcp.outbound.streamSettings).toEqual({ network: 'tcp', security: 'none', tcpSettings: {
      header: { type: 'http', request: { path: ['/a'], headers: { Host: ['site'] } } },
    } });
    expect(parseShareOutbound('vless://id@example.com:443?type=kcp&mtu=1200&tti=20&seed=secret').outbound.streamSettings)
      .toEqual({ network: 'kcp', security: 'none', kcpSettings: { mtu: 1200, tti: 20 } });
    expect(parseShareOutbound('vless://id@example.com:443?type=kcp&seed=secret&path=x').warnings).toEqual(['seed', 'path']);
    expect(parseShareOutbound('trojan://secret@example.com:443?type=grpc&serviceName=svc&authority=host&mode=multi')
      .outbound.streamSettings).toEqual({ network: 'grpc', security: 'tls', grpcSettings: {
      serviceName: 'svc', authority: 'host', multiMode: true,
    }, tlsSettings: {} });
  });
  it('builds protocol-specific settings', () => {
    expect(parseShareOutbound('ss://YWVzLTEyOC1nY206c2VjcmV0@example.com:443').outbound.settings)
      .toEqual({ servers: [{ address: 'example.com', port: 443, method: 'aes-128-gcm', password: 'secret' }] });
    expect(parseShareOutbound('hy2://secret@example.com:443').outbound.streamSettings)
      .toEqual({ network: 'hysteria', security: 'tls', hysteriaSettings: { version: 2, auth: 'secret' }, tlsSettings: { alpn: ['h3'] } });
    expect(parseShareOutbound('wg://secret@[::1]:443?publickey=pub').outbound.settings)
      .toEqual({ secretKey: 'secret', address: [], peers: [{ publicKey: 'pub', endpoint: '[::1]:443', allowedIPs: ['0.0.0.0/0', '::/0'] }] });
    const encoded = btoa(JSON.stringify({ add: 'example.com', port: 443, id: 'id', net: 'grpc', path: 'svc', extra: 'secret' }));
    const parsed = parseShareOutbound(`vmess://${encoded}`);
    expect(parsed.outbound.settings).toEqual({ vnext: [{ address: 'example.com', port: 443, users: [{ id: 'id', security: 'auto' }] }] });
    expect(parsed.outbound.streamSettings).toEqual({ network: 'grpc', security: 'none', grpcSettings: { serviceName: 'svc' } });
    expect(parsed.warnings).toEqual(['extra']);
  });
  it('rejects malformed links and reports unsupported parameters', () => {
    expect(() => parseShareOutbound('vless://broken')).toThrow();
    expect(parseShareOutbound('vless://abc@[::1]:443?plugin=secret').warnings).toEqual(['plugin']);
    expect(parseShareOutbound('vless://abc@[::1]:443').outbound.settings.address).toBe('::1');
  });
  it('imports TLS verification parameters and the default port', () => {
    const parsed = parseShareOutbound('vless://id@example.com?security=tls&ech=config&vcn=name&pcs=hash&cs=suite');
    expect(parsed.outbound.settings.port).toBe(443);
    expect(parsed.outbound.streamSettings.tlsSettings).toEqual({
      echConfigList: 'config', verifyPeerCertByName: 'name', pinnedPeerCertSha256: 'hash', cipherSuites: 'suite',
    });
    expect(parsed.warnings).toEqual([]);
    expect(parseShareOutbound('hy2://secret@example.com?pinSHA256=hash').outbound.streamSettings.tlsSettings)
      .toEqual({ pinnedPeerCertSha256: 'hash', alpn: ['h3'] });
    expect(parseShareOutbound('vless://id@example.com?ech=config').warnings).toContain('ech');
  });
  it.each([
    [{ settings: { address: 'old', extra: 1 } }, ['settings','address']],
    [{ settings: { vnext: [{ address: 'old', users: [{ id: 'a', extra: 1 }, { id: 'b' }] }, { address: 'other' }] } }, ['settings','vnext',0,'address']],
    [{ settings: { servers: [{ address: 'old', extra: 1 }, { address: 'other' }] } }, ['settings','servers',0,'address']],
  ])('preserves unrelated fields', (original, path) => {
    const copy = structuredClone(original); const edited = setOutboundField(original, path, 'new');
    expect(original).toEqual(copy); expect(JSON.stringify(edited).replace('new', 'old')).toBe(JSON.stringify(copy));
  });
});

