import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LazyJsonEditor } from '../LazyJsonEditor';
import { SchemaForm } from './SchemaForm';
import { outboundSchema } from './schema';
import { protocols } from './schema/common';
import { protocolDefaults } from './schema/protocols';
import { transportDefaults } from './schema/transports';
import { securityDefaults } from './schema/security';
import { parseShareOutbound } from './shareOutbound';
import type { Outbound } from './types';

const button = 'btn btn-sm btn-ghost-secondary';
const isObject = (value: unknown): value is Outbound => !!value && typeof value === 'object' && !Array.isArray(value);
export function OutboundEditor({ initial, tags, onApply, onCancel }: {
  initial: Outbound; tags: string[]; onApply: (value: Outbound) => void; onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2));
  const [mode, setMode] = useState<'form' | 'json'>(protocols.includes(initial.protocol) ? 'form' : 'json');
  const [link, setLink] = useState('');
  const [message, setMessage] = useState('');
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { /* invalid JSON */ }
  const valid = isObject(parsed);
  const draft: Outbound = isObject(parsed) ? parsed : {};
  const unique = valid && typeof draft.tag === 'string' && !!draft.tag.trim() && !tags.includes(draft.tag);
  const update = (next: Outbound) => setText(JSON.stringify(next, null, 2));
  const formChange = (next: Outbound) => {
    if (next.protocol !== draft.protocol) {
      if (Object.keys(draft.settings || {}).length && !window.confirm(t('nodeOps.changeProtocol'))) return;
      next.settings = structuredClone(protocolDefaults[next.protocol] || {});
      if (['hysteria', 'masque'].includes(next.protocol)) {
        next.streamSettings = { network: next.protocol, security: 'tls',
          [`${next.protocol}Settings`]: structuredClone(transportDefaults[next.protocol]),
          tlsSettings: { ...structuredClone(securityDefaults.tls), alpn: ['h3'] } };
      } else if (['hysteria', 'masque'].includes(draft.protocol)) {
        next.streamSettings = { network: 'tcp', security: 'none', tcpSettings: structuredClone(transportDefaults.tcp) };
      }
    } else if (next.streamSettings?.network !== draft.streamSettings?.network) {
      const network = next.streamSettings?.network;
      const old = draft.streamSettings?.network || 'tcp';
      if (draft.streamSettings?.[`${old}Settings`] && !window.confirm(t('nodeOps.removeBlockConfirm'))) return;
      delete next.streamSettings[`${old}Settings`];
      if (network) next.streamSettings[`${network}Settings`] = structuredClone(transportDefaults[network] || {});
      if (network === 'xdrive') next.mux = { ...next.mux, enabled: true };
    } else if (next.streamSettings?.security !== draft.streamSettings?.security) {
      const security = next.streamSettings?.security;
      if ((draft.streamSettings?.tlsSettings || draft.streamSettings?.realitySettings) &&
        !window.confirm(t('nodeOps.removeBlockConfirm'))) return;
      delete next.streamSettings.tlsSettings;
      delete next.streamSettings.realitySettings;
      if (security && security !== 'none') next.streamSettings[`${security}Settings`] = structuredClone(securityDefaults[security] || {});
    }
    if (next.protocol === 'vless' && next.settings?.flow &&
      (next.settings.encryption !== 'none' || !['tcp', 'xhttp'].includes(next.streamSettings?.network || 'tcp') ||
        !['tls', 'reality'].includes(next.streamSettings?.security))) delete next.settings.flow;
    if (next.mux?.enabled === false) delete next.mux;
    update(next);
  };
  return <div className="flex min-h-0 flex-1 flex-col gap-2">
    <div className="flex flex-wrap gap-2"><input className="form-control" aria-label={t('nodeOps.shareLink')}
      placeholder={t('nodeOps.shareLink')} value={link} onChange={event => setLink(event.target.value)} />
      <button type="button" className={button} onClick={() => {
        try {
          const result = parseShareOutbound(link);
          if (!result.outbound.tag) result.outbound.tag = draft.tag || '';
          update(result.outbound); setMode('form');
          setMessage(result.warnings.length ? t('nodeOps.shareWarnings', { names: result.warnings.join(', ') }) : '');
        } catch { setMessage(t('nodeOps.invalidShare')); }
      }}>{t('nodeOps.import')}</button></div>
    {message && <div role="alert">{message}</div>}
    <div className="flex flex-wrap gap-2">
      <button type="button" className={`seg-tab ${mode === 'form' ? 'seg-tab--active' : ''}`}
        disabled={!valid || !protocols.includes(draft.protocol)} onClick={() => setMode('form')}>{t('nodeOps.form')}</button>
      <button type="button" className={`seg-tab ${mode === 'json' ? 'seg-tab--active' : ''}`} onClick={() => setMode('json')}>JSON</button>
      <button type="button" className={button} disabled={!unique} onClick={() => { if (unique) onApply(draft); }}>
        {t('nodeOps.applyDraft')}</button>
      <button type="button" className={button} onClick={onCancel}>{t('common.cancel')}</button>
    </div>
    {!unique && <div role="alert" className="node-ops-error">{t('nodeOps.invalidOutbound')}</div>}
    {valid && !protocols.includes(draft.protocol) && <div>{t('nodeOps.jsonOnly')}</div>}
    {mode === 'json' ? <LazyJsonEditor label={t('nodeOps.outboundJson')} value={text} onChange={setText} />
      : <div className="min-h-0 flex-1 overflow-auto"><SchemaForm value={draft} fields={outboundSchema(draft, tags)}
        onChange={formChange} /></div>}
  </div>;
}
