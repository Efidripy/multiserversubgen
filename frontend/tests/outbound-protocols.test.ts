import { describe, expect, it } from 'vitest';
import { protocolDefaults, protocolFields } from '../src/components/outbound/schema/protocols';
import type { FieldDef, Outbound, Path } from '../src/components/outbound/types';

const required: Record<string, string> = {
  freedom: `streamSettings.sockopt.domainStrategy settings.redirect settings.userLevel settings.proxyProtocol
    settings.fragment.packets settings.fragment.length settings.fragment.interval settings.fragment.maxSplit
    settings.noises.*.type settings.noises.*.packet settings.noises.*.delay settings.noises.*.applyTo
    settings.finalRules.*.action settings.finalRules.*.network settings.finalRules.*.port settings.finalRules.*.ip
    settings.finalRules.*.delay settings.finalRules.*.logLevel`,
  blackhole: 'settings.response.type settings.response.customResponseData',
  dns: `settings.rewriteNetwork settings.rewriteAddress settings.rewritePort settings.userLevel settings.rules.*.action
    settings.rules.*.qType settings.rules.*.domain settings.rules.*.rCode`,
  vmess: `settings.vnext.0.address settings.vnext.0.port settings.vnext.0.users.0.id
    settings.vnext.0.users.0.security`,
  vless: `settings.address settings.port settings.id settings.encryption settings.flow settings.testpre settings.testseed
    settings.reverse.tag settings.reverse.sniffing.enabled settings.reverse.sniffing.destOverride
    settings.reverse.sniffing.metadataOnly settings.reverse.sniffing.routeOnly settings.reverse.sniffing.ipsExcluded
    settings.reverse.sniffing.domainsExcluded`,
  trojan: 'settings.servers.0.address settings.servers.0.port settings.servers.0.password',
  shadowsocks: `settings.servers.0.address settings.servers.0.port settings.servers.0.password
    settings.servers.0.method settings.servers.0.uot settings.servers.0.UoTVersion`,
  socks: 'settings.servers.0.address settings.servers.0.port settings.servers.0.users.0.user settings.servers.0.users.0.pass',
  http: `settings.servers.0.address settings.servers.0.port settings.servers.0.users.0.user
    settings.servers.0.users.0.pass settings.headers`,
  wireguard: `settings.address settings.secretKey settings.mtu settings.noKernelTun settings.reserved settings.remoteDNS
    settings.peers.*.endpoint settings.peers.*.publicKey settings.peers.*.preSharedKey settings.peers.*.keepAlive
    settings.peers.*.allowedIPs`,
  hysteria: 'settings.address settings.port settings.version',
  masque: 'settings.address settings.port settings.remoteDNS',
  loopback: `settings.inboundTag settings.sniffing.enabled settings.sniffing.destOverride settings.sniffing.metadataOnly
    settings.sniffing.routeOnly settings.sniffing.ipsExcluded settings.sniffing.domainsExcluded`,
  amneziawg: `settings.mtu settings.listenPort settings.secretKey settings.address.0 settings.dns
    settings.headerProtectionKey settings.jc settings.jmin settings.jmax settings.s1 settings.s2 settings.s3 settings.s4
    settings.h1 settings.h2 settings.h3 settings.h4 settings.i1 settings.i2 settings.i3 settings.i4 settings.i5
    settings.contentPaddingAddition settings.randomTrailers settings.disableCookies settings.peers.*.endpoint
    settings.peers.*.publicKey settings.peers.*.presharedKey settings.peers.*.keepAlive settings.peers.*.allowedIPs`,
};
function collect(fields: FieldDef[], prefix: Path = []): Map<string, FieldDef> {
  const result = new Map<string, FieldDef>();
  for (const def of fields) {
    const relative = typeof def.path === 'function' ? def.path({}, undefined) : def.path;
    const path = [...prefix, ...relative];
    result.set(path.join('.'), def);
    const next = def.kind === 'array' ? [...path, '*'] : prefix;
    for (const [key, value] of collect(def.fields || [], next)) result.set(key, value);
  }
  return result;
}
describe('outbound protocol schemas', () => {
  it.each(Object.entries(required))('%s describes every saved field', (protocol, paths) => {
    const fields = collect(protocolFields[protocol]);
    for (const path of paths.trim().split(/\s+/)) expect(fields.has(path), path).toBe(true);
  });
  it('shows conditional fields only when applicable', () => {
    const vless = collect(protocolFields.vless);
    const show = (path: string, value: Outbound) => vless.get(path)?.showIf?.(value, undefined);
    expect(show('settings.testpre', { settings: { flow: 'xtls-rprx-vision' } })).toBe(true);
    expect(show('settings.testseed', { settings: { flow: '' } })).toBe(false);
    expect(show('settings.reverse.sniffing', { settings: { reverse: { tag: 'in' } } })).toBe(true);
    expect(show('settings.reverse.sniffing', { settings: {} })).toBe(false);
    expect(show('settings.reverse.sniffing.destOverride', { settings: { reverse: { sniffing: { enabled: true } } } }))
      .toBe(true);
    expect(show('settings.reverse.sniffing.destOverride', { settings: {} })).toBe(false);
    const custom = collect(protocolFields.blackhole).get('settings.response.customResponseData');
    expect(custom?.showIf?.({ settings: { response: { type: 'custom' } } }, undefined)).toBe(true);
    expect(custom?.showIf?.({ settings: {} }, undefined)).toBe(false);
    const delay = collect(protocolFields.freedom).get('settings.finalRules.*.delay');
    expect(delay?.showIf?.({}, { path: [], value: { action: 'block' }, index: 0 })).toBe(true);
    expect(delay?.showIf?.({}, { path: [], value: { action: 'allow' }, index: 0 })).toBe(false);
  });
  it('initializes protocol and peer defaults', () => {
    expect(protocolDefaults.vmess.vnext[0].users[0].security).toBe('auto');
    expect(protocolDefaults.wireguard.peers[0].allowedIPs).toEqual(['0.0.0.0/0', '::/0']);
    expect(protocolDefaults.amneziawg).toMatchObject({ jmin: 40, jmax: 100, disableCookies: true });
  });
});
