import { describe, expect, it } from 'vitest';
import { inboundFields } from '../src/components/outbound/schema/inbound';
import { getPath, setPath } from '../src/components/outbound/paths';
import type { FieldDef, ItemContext, Outbound, Path } from '../src/components/outbound/types';

function check(fields: FieldDef[], value: Outbound, context?: ItemContext): number {
  let count = 0;
  for (const field of fields) {
    if (field.showIf && !field.showIf(value, context)) continue;
    const relative = typeof field.path === 'function' ? field.path(value, context) : field.path;
    const path: Path = context && typeof field.path !== 'function' ? [...context.path, ...relative] : relative;
    if (field.kind === 'section' || field.kind === 'toggle') {
      count += check(field.fields || [], value, context);
    } else if (field.kind === 'array') {
      const next = setPath(value, path, [{ type: 'filter', settings: { unknown: 7 }, unknown: 8 }]);
      count += check(field.fields || [], next, { path: [...path, 0], value: getPath(next, [...path, 0]), index: 0 });
    } else if (!field.uiOnly) {
      const before = structuredClone(value);
      const original = getPath(value, path);
      expect(field.read ? field.read(original, value, path) : original).toEqual(original);
      const sample = field.kind === 'boolean' ? true : field.kind === 'number' ? 123 :
        field.kind === 'list' || field.kind === 'numberList' ? ['sample'] : field.kind === 'json' ? { sample: 1 } : 'sample';
      const written = field.write ? field.write(sample, value, path) : sample;
      expect(getPath(setPath(value, path, written), path)).toEqual(written);
      expect(value).toEqual(before);
      count++;
    }
  }
  return count;
}

describe('inbound schema matrix', () => {
  for (const protocol of ['vless', 'vmess', 'trojan', 'shadowsocks', 'hysteria', 'wireguard', 'socks',
    'mixed', 'http', 'dokodemo-door', 'tunnel', 'tun', 'mtproto']) {
    for (const network of ['tcp', 'raw', 'kcp', 'ws', 'grpc', 'httpupgrade', 'xhttp', 'hysteria']) {
      for (const security of ['none', 'tls', 'reality']) {
        it(`${protocol} ${network} ${security}`, () => {
          const value = { protocol, settings: { unknown: 1 }, streamSettings: { network, security, unknown: 2 },
            sniffing: { unknown: 3 }, unknown: 4 };
          const before = structuredClone(value);
          expect(check(inboundFields, value)).toBeGreaterThan(10);
          expect(value).toEqual(before);
        });
      }
    }
  }
  it.each(['target', 'dest'])('writes the existing REALITY %s key', key => {
    const value = { streamSettings: { security: 'reality', realitySettings: { [key]: 'example:443' } } };
    const security = inboundFields.find(f => f.label === 'security')!;
    const reality = security.fields!.find(f => f.label === 'reality')!;
    const target = reality.fields!.find(f => f.label === 'target')!;
    expect(typeof target.path === 'function' && target.path(value, undefined).at(-1)).toBe(key);
  });
});
