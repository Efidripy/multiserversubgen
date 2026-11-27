import type { FieldDef } from '../../types';

const field = (path: string, label: string, kind: FieldDef['kind'] = 'text', options?: string[]): FieldDef =>
  ({ path: path.split('.'), label, kind, options });
const section = (label: string, fields: FieldDef[]): FieldDef => ({ path: [], label, kind: 'section', fields });

export const inboundFields: FieldDef[] = [
  field('remark', 'Remark'), field('enable', 'Enable', 'boolean'),
  field('listen', 'Listen IP'), field('port', 'Port', 'number'),
  section('Transmission', [
    field('streamSettings.network', 'Network', 'select', ['tcp', 'ws', 'grpc', 'xhttp', 'httpupgrade', 'quic']),
    field('streamSettings.wsSettings.host', 'WebSocket host'), field('streamSettings.wsSettings.path', 'WebSocket path'),
    field('streamSettings.wsSettings.heartbeatPeriod', 'Heartbeat period', 'number'),
    field('streamSettings.grpcSettings.serviceName', 'gRPC service name'),
    field('streamSettings.grpcSettings.multiMode', 'gRPC multi mode', 'boolean'),
    field('streamSettings.xhttpSettings.host', 'XHTTP host'), field('streamSettings.xhttpSettings.path', 'XHTTP path'),
    field('streamSettings.xhttpSettings.mode', 'XHTTP mode', 'select', ['auto', 'packet-up', 'stream-up', 'stream-one']),
    field('streamSettings.xhttpSettings.scMaxBufferedPosts', 'Max buffered posts', 'number'),
    field('streamSettings.xhttpSettings.scMaxEachPostBytes', 'Max upload size', 'number'),
    field('streamSettings.xhttpSettings.xPaddingBytes', 'Padding bytes'),
    field('streamSettings.xhttpSettings.noSSEHeader', 'No SSE header', 'boolean'),
    field('streamSettings.httpupgradeSettings.host', 'HTTPUpgrade host'),
    field('streamSettings.httpupgradeSettings.path', 'HTTPUpgrade path'),
  ]),
  section('Socket options', [
    field('streamSettings.sockopt.tcpFastOpen', 'TCP fast open', 'boolean'),
    field('streamSettings.sockopt.tcpMptcp', 'Multipath TCP', 'boolean'),
    field('streamSettings.sockopt.V6Only', 'IPv6 only', 'boolean'),
    field('streamSettings.sockopt.domainStrategy', 'Domain strategy', 'combobox',
      ['AsIs', 'UseIP', 'UseIPv4', 'UseIPv6', 'ForceIP', 'ForceIPv4', 'ForceIPv6']),
    field('streamSettings.sockopt.tcpcongestion', 'TCP congestion'),
    field('streamSettings.sockopt.tproxy', 'TProxy', 'select', ['off', 'redirect', 'tproxy']),
  ]),
  section('Security', [
    field('streamSettings.security', 'Security', 'select', ['none', 'tls', 'reality']),
    field('settings.decryption', 'VLESS decryption'),
    field('streamSettings.realitySettings.show', 'Reality show', 'boolean'),
    field('streamSettings.realitySettings.xver', 'Reality xver', 'number'),
    field('streamSettings.realitySettings.dest', 'Reality target'),
    field('streamSettings.realitySettings.serverNames', 'Reality server names', 'list'),
    field('streamSettings.realitySettings.shortIds', 'Reality short IDs', 'list'),
    field('streamSettings.realitySettings.privateKey', 'Reality private key'),
    field('streamSettings.realitySettings.settings.publicKey', 'Reality public key'),
    field('streamSettings.realitySettings.settings.fingerprint', 'Reality fingerprint'),
    field('streamSettings.realitySettings.settings.spiderX', 'Reality spiderX'),
    field('streamSettings.tlsSettings.serverName', 'TLS server name'),
    field('streamSettings.tlsSettings.allowInsecure', 'TLS allow insecure', 'boolean'),
  ]),
  section('Sniffing', [
    field('sniffing.enabled', 'Enable sniffing', 'boolean'), field('sniffing.destOverride', 'Destination overrides', 'list'),
    field('sniffing.metadataOnly', 'Metadata only', 'boolean'), field('sniffing.routeOnly', 'Route only', 'boolean'),
    field('sniffing.ipsExcluded', 'Excluded IPs', 'list'), field('sniffing.domainsExcluded', 'Excluded domains', 'list'),
  ]),
];
