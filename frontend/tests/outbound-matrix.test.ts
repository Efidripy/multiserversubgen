import { describe, expect, it } from 'vitest';
import { outboundSchema } from '../src/components/outbound/schema';
import { protocols } from '../src/components/outbound/schema/common';
import { protocolDefaults } from '../src/components/outbound/schema/protocols';
import { securityDefaults } from '../src/components/outbound/schema/security';
import { transportDefaults } from '../src/components/outbound/schema/transports';
import type { FieldDef, Outbound } from '../src/components/outbound/types';

// Visible, config-writing paths only: containers and UI-only controls may legitimately repeat a path.
function paths(fields: FieldDef[], value: Outbound): string[] {
  return fields.flatMap((field) => {
    if (field.showIf && !field.showIf(value, undefined)) return [];
    if (field.kind === 'array') return [];
    if (field.kind === 'section' || field.kind === 'toggle') return paths(field.fields || [], value);
    if (field.uiOnly) return [];
    const path = typeof field.path === 'function' ? field.path(value, undefined) : field.path;
    return [path.join('.')];
  });
}

const stream = (network: string, security: string) => ({
  network, security,
  [`${network}Settings`]: structuredClone(transportDefaults[network] || {}),
  ...(security === 'none' ? {} : { [`${security}Settings`]: structuredClone(securityDefaults[security] || {}) }),
});

describe('outbound schema matrix', () => {
  for (const protocol of protocols) {
    for (const network of ['tcp', 'kcp', 'ws', 'grpc', 'httpupgrade', 'xhttp']) {
      for (const security of ['none', 'tls', 'reality']) {
        it(`${protocol} ${network} ${security}: no duplicate fields, nothing mutated`, () => {
          const value: Outbound = { tag: 'a', protocol, settings: structuredClone(protocolDefaults[protocol] || {}),
            streamSettings: stream(network, security) };
          const before = structuredClone(value);
          const all = paths(outboundSchema(value, ['b']), value);
          expect(all.filter((path, index) => all.indexOf(path) !== index)).toEqual([]);
          expect(value).toEqual(before);
        });
      }
    }
  }
});
