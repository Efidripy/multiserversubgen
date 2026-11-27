// Add fields to the relevant schema file; paths are relative to the outbound (or the current array item).
import type { FieldDef, Outbound } from '../types';
import { common } from './common';
import { protocolFields } from './protocols';
import { transportFields } from './transports';
import { securityFields } from './security';
import { sockoptFields } from './sockopt';
import { muxFields } from './mux';
import { finalmaskFields } from './finalmask';

export function outboundSchema(value: Outbound, tags: string[]): FieldDef[] {
  const protocol = value.protocol;
  const network = value.streamSettings?.network || 'tcp';
  const security = ['hysteria', 'masque'].includes(protocol) ? 'tls' : value.streamSettings?.security || 'none';
  const transport = !['freedom', 'blackhole', 'wireguard', 'hysteria', 'masque'].includes(protocol);
  return [
    ...common,
    ...(protocolFields[protocol] || []),
    ...(['hysteria', 'masque'].includes(protocol) ? [...transportFields[protocol], ...securityFields.tls] : transport ? [{ path: ['streamSettings', 'network'], label: 'transport', kind: 'select' as const,
      options: ['tcp', 'kcp', 'ws', 'grpc', 'httpupgrade', 'xhttp', ...(protocol === 'vless' ? ['xdrive'] : [])] },
    ...(transportFields[network] || []),
    { path: ['streamSettings', 'security'], label: 'security', kind: 'select' as const, options: ['none', 'tls', 'reality'] },
    ...(securityFields[security] || [])] : []),
    ...sockoptFields(tags),
    ...muxFields,
    ...finalmaskFields,
  ];
}
