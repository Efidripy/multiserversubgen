import type { FieldDef } from '../types';

const base = ['streamSettings', 'sockopt'];
export const sockoptDefaults = {
  dialerProxy: '', domainStrategy: 'AsIs', addressPortStrategy: 'none', tcpKeepAliveInterval: 0,
  tcpFastOpen: false, tcpMptcp: false, penetrate: false, mark: 0, interface: '', tproxy: 'off',
  tcpcongestion: 'bbr', tcpUserTimeout: 0, tcpKeepAliveIdle: 0, tcpMaxSeg: 0, tcpWindowClamp: 0,
};
export const sockoptFields = (tags: string[]): FieldDef[] => [{
  path: base, label: 'Socket Options', kind: 'toggle', defaults: sockoptDefaults, fields: [
    { path: [...base, 'dialerProxy'], label: 'Dialer Proxy', kind: 'select', options: tags },
    { path: [...base, 'domainStrategy'], label: 'Domain Strategy', kind: 'select',
      options: ['AsIs', 'UseIP', 'UseIPv6v4', 'UseIPv6', 'UseIPv4v6', 'UseIPv4',
        'ForceIP', 'ForceIPv6v4', 'ForceIPv6', 'ForceIPv4v6', 'ForceIPv4'], showIf: value => value.protocol !== 'freedom' },
    { path: [...base, 'addressPortStrategy'], label: 'Address Port Strategy', kind: 'select',
      options: ['none', 'SrvPortOnly', 'SrvAddressOnly', 'SrvPortAndAddress', 'TxtPortOnly', 'TxtAddressOnly', 'TxtPortAndAddress'] },
    { path: [...base, 'tcpKeepAliveInterval'], label: 'Keep Alive Interval', kind: 'number' },
    { path: [...base, 'tcpFastOpen'], label: 'TCP Fast Open', kind: 'boolean' },
    { path: [...base, 'tcpMptcp'], label: 'Multipath TCP', kind: 'boolean' },
    { path: [...base, 'penetrate'], label: 'Penetrate', kind: 'boolean' },
    { path: [...base, 'mark'], label: 'Mark', kind: 'number' },
    { path: [...base, 'interface'], label: 'Interface', kind: 'text' },
    { path: [...base, 'tproxy'], label: 'TProxy', kind: 'select', options: ['off', 'redirect', 'tproxy'] },
    { path: [...base, 'tcpcongestion'], label: 'TCP Congestion', kind: 'combobox', options: ['bbr', 'cubic', 'reno'] },
    { path: [...base, 'tcpUserTimeout'], label: 'TCP User Timeout', kind: 'number' },
    { path: [...base, 'tcpKeepAliveIdle'], label: 'TCP Keep Alive Idle', kind: 'number' },
    { path: [...base, 'tcpMaxSeg'], label: 'TCP Max Segment', kind: 'number' },
    { path: [...base, 'tcpWindowClamp'], label: 'TCP Window Clamp', kind: 'number' },
    { path: [...base, 'happyEyeballs'], label: 'Happy Eyeballs', kind: 'toggle',
      defaults: { tryDelayMs: 250, prioritizeIPv6: false, interleave: 1, maxConcurrentTry: 4 }, fields: [
        { path: [...base, 'happyEyeballs', 'tryDelayMs'], label: 'Try Delay (ms)', kind: 'number' },
        { path: [...base, 'happyEyeballs', 'prioritizeIPv6'], label: 'Prioritize IPv6', kind: 'boolean' },
        { path: [...base, 'happyEyeballs', 'interleave'], label: 'Interleave', kind: 'number' },
        { path: [...base, 'happyEyeballs', 'maxConcurrentTry'], label: 'Max Concurrent Try', kind: 'number' },
      ] },
    { path: [...base, 'customSockopt'], label: 'Custom Socket Options', kind: 'array',
      defaults: { system: '', level: '6', opt: '', type: 'int', value: '' }, fields: [
        { path: ['system'], label: 'System', kind: 'select', options: ['', 'linux', 'windows', 'darwin'] },
        { path: ['level'], label: 'Level', kind: 'text' },
        { path: ['opt'], label: 'Option', kind: 'text' },
        { path: ['type'], label: 'Type', kind: 'select', options: ['int', 'str'] },
        { path: ['value'], label: 'Value', kind: 'text' },
      ] },
  ],
}];
