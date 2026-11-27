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
  ...protocolFields,
  section('streamSettings', transportFields),
  section('security', securityFields),
  ...sockoptFields,
  ...sniffingFields,
  ...finalmaskFields,
];
