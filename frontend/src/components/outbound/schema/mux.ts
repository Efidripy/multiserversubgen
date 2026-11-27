import type { FieldDef, Outbound } from '../types';

const visible = (value: Outbound) => ['vmess', 'vless', 'trojan', 'shadowsocks', 'http', 'socks'].includes(value.protocol)
  && value.streamSettings?.network !== 'xhttp' && !(value.protocol === 'vless' && value.settings?.flow);
export const muxFields: FieldDef[] = [{ path: ['mux'], label: 'Mux', kind: 'section', showIf: visible, fields: [
  { path: ['mux', 'enabled'], label: 'Enable Mux', kind: 'boolean' },
  { path: ['mux', 'concurrency'], label: 'Concurrency', kind: 'number', showIf: value => value.mux?.enabled === true },
  { path: ['mux', 'xudpConcurrency'], label: 'XUDP Concurrency', kind: 'number', showIf: value => value.mux?.enabled === true },
  { path: ['mux', 'xudpProxyUDP443'], label: 'XUDP UDP 443', kind: 'select', options: ['reject', 'allow', 'skip'],
    showIf: value => value.mux?.enabled === true },
] }];
