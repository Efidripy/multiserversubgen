import type { FieldDef } from '../../types';
import { field, section } from './common';
import { protocolFields } from './protocols';
import { transportFields } from './transports';
import { securityFields } from './security';
import { sockoptFields } from './sockopt';
import { sniffingFields } from './sniffing';
import { finalmaskFields } from './finalmask';

export const inboundFields: FieldDef[] = [
  { ...field('remark'), label: 'Remark' },
  field('enable', 'boolean'),
  field('listen'),
  field('port', 'number'),
  ...['tag', 'shareAddrStrategy', 'shareAddr', 'trafficReset'].map(name =>
    ({ ...field(name), showIf: (value: Record<string, unknown>) => name in value })),
  ...['trafficResetDay', 'subSortIndex'].map(name =>
    ({ ...field(name, 'number'), showIf: (value: Record<string, unknown>) => name in value })),
  { ...field('total', 'number'), label: 'total (GB)', showIf: value => 'total' in value,
    read: value => typeof value === 'number' ? value / (1024 ** 3) : value,
    write: value => typeof value === 'number' ? Math.round(value * (1024 ** 3)) : value },
  { ...field('expiryTime', 'datetime'), showIf: value => 'expiryTime' in value,
    read: value => {
      if (typeof value !== 'number' || !value) return '';
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? '' : new Date(value - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    },
    write: value => value ? new Date(String(value)).getTime() : 0 },
  ...protocolFields,
  section('streamSettings', transportFields),
  section('security', securityFields),
  ...sockoptFields,
  ...sniffingFields,
  ...finalmaskFields,
];
