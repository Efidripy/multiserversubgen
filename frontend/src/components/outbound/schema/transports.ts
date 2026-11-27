import type { FieldDef, Outbound } from '../types';
const hostPath = (network: string): FieldDef[] => [
  { path: ['streamSettings', `${network}Settings`, 'host'], label: 'host', kind: 'text' },
  { path: ['streamSettings', `${network}Settings`, 'path'], label: 'path', kind: 'text' },
];
export const transportFields: Record<string, FieldDef[]> = {
  tcp: [], kcp: [], ws: hostPath('ws'), grpc: [
    { path: ['streamSettings', 'grpcSettings', 'serviceName'], label: 'serviceName', kind: 'text' },
  ],
  httpupgrade: hostPath('httpupgrade'),
  xhttp: [...hostPath('xhttp'), { path: ['streamSettings', 'xhttpSettings', 'mode'], label: 'mode', kind: 'combobox',
    options: ['auto', 'packet-up', 'stream-up', 'stream-one'] }],
  xdrive: [], hysteria: [], masque: [],
};
export const transportDefaults: Record<string, Outbound> = Object.fromEntries(Object.keys(transportFields).map(key => [key, {}]));
