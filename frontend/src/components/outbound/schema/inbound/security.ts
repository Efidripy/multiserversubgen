import type { FieldDef } from '../../types';
import { array, field, section } from './common';

const f = (base: string, key: string, kind: FieldDef['kind'] = 'text') =>
  field(`streamSettings.${base}Settings.${key}`, kind);
export const securityFields: FieldDef[] = [
  field('streamSettings.security', 'select', ['none', 'tls', 'reality']),
  section('tls', [
    array('streamSettings.tlsSettings.certificates', [field('certificateFile'), field('keyFile'),
      field('certificate', 'list'), field('key', 'list'), field('ocspStapling', 'number'),
      field('oneTimeLoading', 'boolean'), field('usage', 'combobox', ['encipherment', 'verify', 'issue']),
      field('buildChain', 'boolean')]),
    ...['serverName', 'cipherSuites', 'minVersion', 'maxVersion', 'echServerKeys', 'masterKeyLog',
      'settings.fingerprint', 'settings.echConfigList', 'settings.verifyPeerCertByName',
      'echSockopt.dialerProxy', 'echSockopt.domainStrategy'].map(k => f('tls', k)),
    ...['alpn', 'curvePreferences', 'settings.pinnedPeerCertSha256'].map(k => f('tls', k, 'list')),
    ...['rejectUnknownSni', 'disableSystemRoot', 'enableSessionResumption', 'allowInsecure',
      'echSockopt.tcpFastOpen', 'echSockopt.tcpMptcp'].map(k => f('tls', k, 'boolean')),
  ], o => o.streamSettings?.security === 'tls' || o.protocol === 'hysteria'),
  section('reality', [
    f('reality', 'show', 'boolean'), f('reality', 'xver', 'number'),
    { ...f('reality', 'target'), path: o => ['streamSettings', 'realitySettings',
      o.streamSettings?.realitySettings?.target !== undefined || o.streamSettings?.realitySettings?.dest === undefined
        ? 'target' : 'dest'] },
    ...['serverNames', 'shortIds'].map(k => f('reality', k, 'list')),
    f('reality', 'maxTimediff', 'number'),
    ...['minClientVer', 'maxClientVer', 'privateKey', 'mldsa65Seed', 'masterKeyLog', 'settings.fingerprint',
      'settings.publicKey', 'settings.spiderX', 'settings.mldsa65Verify', 'settings.serverName'].map(k => f('reality', k)),
    ...['limitFallbackUpload', 'limitFallbackDownload'].flatMap(dir =>
      ['afterBytes', 'bytesPerSec', 'burstBytesPerSec'].map(k => f('reality', `${dir}.${k}`, 'number'))),
  ], o => o.streamSettings?.security === 'reality'),
];
