import { setPath } from '../../paths';
import type { FieldDef } from '../../types';

const day = 86400000;
const gib = 1024 ** 3;

export function clientFields(protocol: string, record: object): FieldDef[] {
  const client = record as Record<string, unknown>;
  const identity = 'uuid' in client || typeof client.id === 'number' ? 'uuid' : 'id';
  const fields: FieldDef[] = [
    { path: ['email'], label: 'Email', kind: 'text' },
    { path: ['enable'], label: 'Enabled', kind: 'boolean' },
    { path: ['comment'], label: 'Comment', kind: 'text' },
  ];
  if (['vless', 'vmess'].includes(protocol)) {
    fields.push({ path: [identity], label: 'UUID', kind: 'text', generate: 'uuid' });
  }
  if (['trojan', 'shadowsocks'].includes(protocol)) {
    fields.push({ path: ['password'], label: 'Password', kind: 'text', generate: 'password' });
  }
  if (['hysteria', 'hysteria2'].includes(protocol)) fields.push({ path: ['auth'], label: 'Auth', kind: 'text' });
  fields.push({ path: ['subId'], label: 'Subscription ID', kind: 'text', generate: 'password' });
  if (protocol === 'vless') {
    fields.push({ path: ['flow'], label: 'Flow', kind: 'combobox', options: ['', 'xtls-rprx-vision'] });
  }
  if (protocol === 'vmess') fields.push({ path: ['security'], label: 'Security', kind: 'text' });
  fields.push(
    { path: ['totalGB'], label: 'Traffic limit (GB)', kind: 'number',
      read: value => typeof value === 'number' ? value / gib : value,
      write: value => typeof value === 'number' ? Math.round(value * gib) : value },
    { path: ['expiryTime'], label: 'Delayed start', kind: 'boolean', uiOnly: true,
      read: value => typeof value === 'number' && value < 0,
      onChange: (value, enabled, path) => setPath(value, path, enabled ? -day : 0) },
    { path: ['expiryTime'], label: 'Expiry date and time', kind: 'datetime-local',
      showIf: value => !(typeof value.expiryTime === 'number' && value.expiryTime < 0),
      read: value => {
        if (typeof value !== 'number' || value <= 0 || !Number.isFinite(value)) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return new Date(value - date.getTimezoneOffset() * 60000).toISOString().slice(0, -1);
      },
      write: value => typeof value === 'string' && value ? new Date(value).getTime() : value },
    { path: ['expiryTime'], label: 'Delayed start (days)', kind: 'number',
      showIf: value => typeof value.expiryTime === 'number' && value.expiryTime < 0,
      read: value => typeof value === 'number' ? -value / day : value,
      write: value => typeof value === 'number' ? -Math.abs(value) * day : value },
    { path: ['limitIp'], label: 'IP limit', kind: 'number' },
    { path: ['limitHwid'], label: 'HWID limit', kind: 'number' },
    { path: ['tgId'], label: 'Telegram ID', kind: 'number' },
    { path: ['group'], label: 'Group', kind: 'text' },
    { path: ['reset'], label: 'Reset', kind: 'number' },
    { path: ['trafficReset'], label: 'Traffic reset', kind: 'select', options: ['never', 'hourly', 'daily', 'weekly', 'monthly'] },
    { path: ['trafficResetDay'], label: 'Traffic reset day', kind: 'number' },
    { path: ['reverse', 'tag'], label: 'Reverse tag', kind: 'text' },
  );
  if (protocol === 'wireguard') fields.push(
    { path: ['privateKey'], label: 'Private key', kind: 'text' },
    { path: ['publicKey'], label: 'Public key', kind: 'text' },
    { path: ['preSharedKey'], label: 'Pre-shared key', kind: 'text' },
    { path: ['allowedIPs'], label: 'Allowed IPs', kind: 'list' },
    { path: ['keepAlive'], label: 'Keep alive', kind: 'number' },
  );
  if (protocol === 'mtproto') fields.push(
    { path: ['secret'], label: 'Secret', kind: 'text' },
    { path: ['adTag'], label: 'Ad tag', kind: 'text' },
  );
  return fields;
}
