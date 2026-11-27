import type { FieldDef } from '../../types';
import { finalmaskFields as shared } from '../finalmask';
import { field } from './common';

// Reuse the mask editors without their outbound presets or destructive type-change handlers.
const adapt = (entry: FieldDef): FieldDef => {
  const result: FieldDef = { ...entry, onChange: undefined, defaults: entry.kind === 'array' ? (Array.isArray(entry.defaults) ? [] : {}) : undefined,
    fields: entry.fields?.filter(child => !child.uiOnly).map(adapt) };
  if (entry.path instanceof Array && entry.path.join('.') === 'type' && entry.options instanceof Array) {
    result.options = [...entry.options.filter(option => option !== 'udphop'), 'filter'];
  }
  if (entry.path instanceof Array && entry.path.join('.') === 'streamSettings.finalmask.tcp') {
    result.fields = [...(result.fields || []),
      { ...field('settings.allowedSourceIPs', 'list'), showIf: (_, c) => c?.value?.type === 'filter' },
      { ...field('settings.blockedSourceIPs', 'list'), showIf: (_, c) => c?.value?.type === 'filter' }];
  }
  if (entry.path instanceof Array && entry.path.join('.') === 'streamSettings.finalmask.quicParams') {
    result.kind = 'section';
    result.fields = [...(result.fields || []), field('streamSettings.finalmask.quicParams.udpHop.ports'),
      field('streamSettings.finalmask.quicParams.udpHop.interval')];
  }
  if (typeof entry.path !== 'function' && entry.path.length) result.label = String(entry.path.at(-1));
  return result;
};
export const finalmaskFields = shared.map(adapt);
