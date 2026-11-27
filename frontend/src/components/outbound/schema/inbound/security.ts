import { deletePath, setPath } from '../../paths';
import type { FieldDef } from '../../types';
import { array, field, section } from './common';

const f = (base: string, key: string, kind: FieldDef['kind'] = 'text') =>
  field(`streamSettings.${base}Settings.${key}`, kind);
export const securityFields: FieldDef[] = [
  field('streamSettings.security', 'select', ['none', 'tls', 'reality']),
  section('tls', [
    array('streamSettings.tlsSettings.certificates', [
      { ...field('certificateMode', 'select', ['files', 'contents']), uiOnly: true,
        read: (_, value, path) => {
          const cert = path.slice(0, -1).reduce((item, key) => item?.[key], value);
          return cert?.certificate !== undefined || cert?.key !== undefined ? 'contents' : 'files';
        },
        onChange: (value, mode, path) => {
          const base = path.slice(0, -1);
          const remove = mode === 'files' ? ['certificate', 'key'] : ['certificateFile', 'keyFile'];
          let next = value;
          for (const key of remove) next = deletePath(next, [...base, key]);
          return setPath(next, [...base, mode === 'files' ? 'certificateFile' : 'certificate'], mode === 'files' ? '' : []);
        } },
      { ...field('certificateFile'), showIf: (_, c) => c?.value?.certificate === undefined && c?.value?.key === undefined },
      { ...field('keyFile'), showIf: (_, c) => c?.value?.certificate === undefined && c?.value?.key === undefined },
      { ...field('certificate', 'lineList'), showIf: (_, c) => c?.value?.certificate !== undefined || c?.value?.key !== undefined },
      { ...field('key', 'lineList'), showIf: (_, c) => c?.value?.certificate !== undefined || c?.value?.key !== undefined },
      field('ocspStapling', 'number'),
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
