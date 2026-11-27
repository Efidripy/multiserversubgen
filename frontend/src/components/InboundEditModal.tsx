import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { generateNodeVlessEncryption, generateNodeX25519 } from '../api/serverOps';
import { LazyJsonEditor } from './LazyJsonEditor';
import { SchemaForm } from './outbound/SchemaForm';
import { setPath } from './outbound/paths';
import { inboundFields } from './outbound/schema/inbound';

type Inbound = { id: number; node_name: string; protocol: string };
type Props = { inbound: Inbound; nodeId: number; onClose: () => void; onSaved: () => void };

export function InboundEditModal({ inbound, nodeId, onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [expected, setExpected] = useState<Record<string, any> | null>(null);
  const [mode, setMode] = useState<'form' | 'json'>('form');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const url = `/v1/inbounds/${nodeId}/${inbound.id}/config`;
  useEffect(() => {
    const controller = new AbortController();
    api.get(url, { auth: getAuth(), signal: controller.signal }).then(({ data }) => {
      setExpected(data); setText(JSON.stringify(data, null, 2));
    }).catch(err => { if (!controller.signal.aborted) setError(err?.response?.data?.detail || err.message); });
    return () => controller.abort();
  }, [url]);
  let value: Record<string, any> | null = null;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) &&
      ['settings', 'streamSettings', 'sniffing'].every(k => parsed[k] === undefined ||
        (parsed[k] !== null && typeof parsed[k] === 'object' && !Array.isArray(parsed[k])))) {
      value = parsed;
    }
  } catch { /* JSON is being edited */ }
  const update = (next: Record<string, any>) => {
    setText(JSON.stringify(next, null, 2));
  };
  const generate = async (kind: 'reality' | 'vless') => {
    if (!value) return;
    setBusy(true); setError('');
    try {
      if (kind === 'reality') {
        const keys = await generateNodeX25519(nodeId);
        let next = value;
        if (keys.privateKey) next = setPath(next, ['streamSettings', 'realitySettings', 'privateKey'], keys.privateKey);
        if (keys.publicKey) next = setPath(next, ['streamSettings', 'realitySettings', 'settings', 'publicKey'], keys.publicKey);
        update(next);
      } else {
        const auths = await generateNodeVlessEncryption(nodeId);
        const decryption = auths.find(item => item.decryption)?.decryption;
        if (!decryption) throw new Error(t('inbounds.vlessDecryptionGenerationFailed'));
        update(setPath(value, ['settings', 'decryption'], decryption));
      }
    } catch (err: any) { setError(err?.response?.data?.detail || err.message); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!value || !expected || !window.confirm(t('nodeOps.confirmApply'))) return;
    setBusy(true); setError('');
    try {
      await api.put(url, { value, expected }, { auth: getAuth() });
      onSaved(); onClose();
    } catch (err: any) { setError(err?.response?.data?.detail || err.message); }
    finally { setBusy(false); }
  };
  return <div data-ln="inbound-edit" className="drawer" role="dialog" aria-modal="true" aria-label={t('inbounds.modifyInbound')}>
    <div className="drawer__backdrop" onClick={onClose} />
    <div className="drawer__panel">
      <div className="drawer__header">
        <div><div className="drawer__title">{t('inbounds.modifyInbound')}</div>
          <div className="drawer__subtitle">{inbound.protocol.toUpperCase()} · {inbound.node_name}</div></div>
        <button className="drawer__close" aria-label={t('common.close')} onClick={onClose}>×</button>
      </div>
      <div className="drawer__body outbound-editor">
        <div className="d-flex flex-wrap gap-2 mb-3">
          <button className={`seg-tab ${mode === 'form' ? 'seg-tab--active' : ''}`} aria-pressed={mode === 'form'}
            disabled={!value} onClick={() => setMode('form')}>{t('inbounds.form')}</button>
          <button className={`seg-tab ${mode === 'json' ? 'seg-tab--active' : ''}`} aria-pressed={mode === 'json'}
            onClick={() => setMode('json')}>JSON</button>
        </div>
        {error && <div role="alert" className="alert alert-danger">{error}</div>}
        {expected && !value && <div role="alert">{t('nodeOps.invalidShape')}</div>}
        {mode === 'json' ? <LazyJsonEditor label="JSON" value={text} onChange={setText} readOnly={!expected || busy} /> :
          value && <><SchemaForm value={value} fields={inboundFields} onChange={update} />
            <div className="d-flex flex-wrap gap-2 mt-3">
              {value.streamSettings?.security === 'reality' && <button className="btn btn-sm btn-ghost-secondary" disabled={busy}
                onClick={() => void generate('reality')}>{t('inbounds.getNewCert')}</button>}
              {inbound.protocol === 'vless' && <button className="btn btn-sm btn-ghost-secondary" disabled={busy} onClick={() => void generate('vless')}>
                {t('inbounds.generateVlessDecryption')}</button>}
            </div></>}
      </div>
      <div className="drawer__footer"><button className="btn btn-primary" disabled={!value || !expected || busy}
        onClick={() => void save()}>{t('common.save')}</button></div>
    </div>
  </div>;
}
