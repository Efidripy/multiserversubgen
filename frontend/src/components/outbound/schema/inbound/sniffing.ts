import { field, section } from './common';

export const sniffingFields = [section('sniffing', [
  field('sniffing.enabled', 'boolean'),
  field('sniffing.destOverride', 'list'),
  field('sniffing.metadataOnly', 'boolean'),
  field('sniffing.routeOnly', 'boolean'),
  field('sniffing.ipsExcluded', 'list'),
  field('sniffing.domainsExcluded', 'list'),
])];
