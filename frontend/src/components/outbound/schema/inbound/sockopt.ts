import { array, field, section } from './common';

const f = (key: string, kind: Parameters<typeof field>[1] = 'text') => field(`streamSettings.sockopt.${key}`, kind);
export const sockoptFields = [section('sockopt', [
  ...['mark', 'tcpKeepAliveInterval', 'tcpKeepAliveIdle', 'tcpMaxSeg', 'tcpUserTimeout', 'tcpWindowClamp'].map(k => f(k, 'number')),
  ...['acceptProxyProtocol', 'tcpFastOpen', 'tcpMptcp', 'penetrate', 'V6Only'].map(k => f(k, 'boolean')),
  ...['tcpcongestion', 'tproxy', 'domainStrategy', 'addressPortStrategy', 'dialerProxy', 'interface'].map(k => f(k)),
  f('trustedXForwardedFor', 'list'),
  ...['tryDelayMs', 'interleave', 'maxConcurrentTry'].map(k => f(`happyEyeballs.${k}`, 'number')),
  f('happyEyeballs.prioritizeIPv6', 'boolean'),
  array('streamSettings.sockopt.customSockopt', [field('system'), field('level'), field('opt'), field('type'), field('value', 'json')]),
])];
