import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { generateNodeMldsa65, generateNodeVlessEncryption } from '../api/serverOps';
import { useTheme } from '../contexts/ThemeContext';
import { LazyJsonEditor } from './LazyJsonEditor';
import { SchemaForm } from './outbound/SchemaForm';
import { clientFields } from './outbound/schema/client';

export interface ClientForEdit {
  id?: string | null;
  email: string;
  enable: boolean;
  up: number;
  down: number;
  total: number;
  expiryTime: number;
  node_id?: number;
  inbound_id: number;
  protocol: string;
  security?: string;
  network?: string;
  flow?: string;
  comment?: string;
  remark?: string;
  limitIp?: number;
  totalGB?: number;
  notes?: string;
}

type Props = { client: ClientForEdit; onClose: () => void; onSaved: () => void };
type RecordValue = Record<string, any>;

const formatBytes = (bytes: number) => {
  if (!bytes) return '0 B';
  const index = Math.min(4, Math.floor(Math.log(Math.max(1, bytes)) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(2)} ${['B', 'KB', 'MB', 'GB', 'TB'][index]}`;
};

export function ClientEditModal({ client, onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const [text, setText] = useState('');
  const [expected, setExpected] = useState<RecordValue | null>(null);
  const [identifier, setIdentifier] = useState(client.id || client.email);
  const [notes, setNotes] = useState(client.notes || '');
  const [savedNotes, setSavedNotes] = useState(client.notes || '');
  const [mode, setMode] = useState<'form' | 'json'>('form');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState('');
  const url = `/v1/clients/${encodeURIComponent(identifier)}`;

  useEffect(() => {
    const controller = new AbortController();
    const initialUrl = `/v1/clients/${encodeURIComponent(client.id || client.email)}/record`;
    api.get(initialUrl, {
      auth: getAuth(), signal: controller.signal, params: { node_id: client.node_id, inbound_id: client.inbound_id },
    }).then(({ data }) => {
      setExpected(data.value);
      setText(JSON.stringify(data.value, null, 2));
    }).catch(err => { if (!controller.signal.aborted) setError(err?.response?.data?.detail || err.message); });
    return () => controller.abort();
  }, [client.id, client.email, client.node_id, client.inbound_id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose(); };
    document.addEventListener('keydown', onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = previous; };
  }, [onClose, busy]);

  let value: RecordValue | null = null;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) value = parsed;
  } catch { /* Keep the JSON draft while it is being edited. */ }
  const update = (next: RecordValue) => setText(JSON.stringify(next, null, 2));
  const showError = (err: any, fallback: string) => setError(err?.response?.data?.detail || err?.message || fallback);

  const generate = async (kind: 'vless' | 'mldsa') => {
    if (!client.node_id || !value) return;
    setBusy(true); setError('');
    try {
      if (kind === 'vless') {
        const auths = await generateNodeVlessEncryption(client.node_id);
        const encryption = auths.find(item => item.encryption)?.encryption;
        if (!encryption) throw new Error(t('clients.vlessEncryptionGenerationFailed'));
        update({ ...value, security: encryption });
      } else {
        const serialized = JSON.stringify(await generateNodeMldsa65(client.node_id), null, 2);
        setKey(serialized);
        try { await navigator.clipboard.writeText(serialized); } catch { /* Clipboard is optional. */ }
      }
    } catch (err: any) { showError(err, t('clients.generationFailed')); }
    finally { setBusy(false); }
  };

  const save = async () => {
    if (!value || !expected || !window.confirm(t('nodeOps.confirmApply'))) return;
    setBusy(true); setError('');
    try {
      await api.put(`${url}/record`, {
        node_id: client.node_id, inbound_id: client.inbound_id, expected, value,
      }, { auth: getAuth() });
      setExpected(value);
      // Notes are keyed by the list identifier: change it only when the identity behind it changed.
      const idOf = (record: RecordValue) => String(record.uuid || (typeof record.id === 'string' && record.id) || '');
      const nextIdentifier = String(idOf(value) && idOf(value) !== idOf(expected) ? idOf(value)
        : identifier === expected.email ? value.email || identifier : identifier);
      setIdentifier(nextIdentifier);
      if (notes !== savedNotes) {
        await api.put(`/v1/clients/${encodeURIComponent(nextIdentifier)}/notes`, {
          node_id: client.node_id, inbound_id: client.inbound_id, email: value.email || client.email, notes,
        }, { auth: getAuth() });
        setSavedNotes(notes);
      }
      onSaved(); onClose();
    } catch (err: any) {
      if (err?.response?.status === 409) setError(t('clients.recordConflict'));
      else if (err?.response?.status === 403) setError(t('clients.recordReadOnly'));
      else showError(err, t('clients.saveFailed'));
    } finally { setBusy(false); }
  };

  const resetTraffic = async () => {
    const email = typeof value?.email === 'string' ? value.email : client.email;
    if (!window.confirm(t('clients.confirmResetTrafficForEmail', { email }))) return;
    setBusy(true); setError('');
    try {
      await api.post(`${url}/reset-traffic`, {
        node_id: client.node_id, inbound_id: client.inbound_id, email,
      }, { auth: getAuth() });
      onSaved();
    } catch (err: any) { showError(err, t('clients.resetFailed')); }
    finally { setBusy(false); }
  };

  const used = client.up + client.down;
  const pct = client.total > 0 ? Math.min(100, used / client.total * 100) : 0;
  const usageColor = pct >= 90 ? colors.danger : pct >= 70 ? colors.warning : '#c45bcc';
  return <div data-ln="client-edit" className="drawer" role="dialog" aria-modal="true" aria-label={t('messages.editClient')}>
    <div className="drawer__backdrop" onClick={() => { if (!busy) onClose(); }} />
    <div className="drawer__panel">
      <div className="drawer__header">
        <div><div className="drawer__title">{t('messages.editClient')}</div>
          <div className="drawer__subtitle">{client.email}</div></div>
        <button className="drawer__close" aria-label={t('common.close')} disabled={busy} onClick={onClose}>×</button>
      </div>
      <div className="drawer__body outbound-editor">
        <div className="d-flex flex-wrap gap-2 mb-3">
          <button className={`seg-tab ${mode === 'form' ? 'seg-tab--active' : ''}`} aria-pressed={mode === 'form'}
            disabled={!value || busy} onClick={() => setMode('form')}>{t('inbounds.form')}</button>
          <button className={`seg-tab ${mode === 'json' ? 'seg-tab--active' : ''}`} aria-pressed={mode === 'json'}
            disabled={busy} onClick={() => setMode('json')}>JSON</button>
        </div>
        {error && <div role="alert" className="alert alert-danger">{error}</div>}
        {expected && !value && <div role="alert">{t('nodeOps.invalidShape')}</div>}
        {mode === 'json' ? <LazyJsonEditor label="JSON" value={text} onChange={setText} readOnly={!expected || busy} /> :
          value && <fieldset className="m-0 min-w-0 border-0 p-0" disabled={busy}>
            <SchemaForm value={value} fields={clientFields(client.protocol, value)} onChange={update} />
          </fieldset>}
        <div className="d-flex flex-wrap gap-2 mt-3">
          {client.protocol === 'vless' && <button className="btn btn-sm btn-ghost-secondary"
            disabled={busy || !value || !client.node_id} onClick={() => void generate('vless')}>
            {t('clients.generateVlessEncryption')}</button>}
          <button className="btn btn-sm btn-ghost-secondary" disabled={busy || !value || !client.node_id}
            onClick={() => void generate('mldsa')}>{t('clients.generateMldsa65')}</button>
        </div>
        {key && <textarea className="form-control mt-2" aria-label="ML-DSA-65" readOnly value={key} rows={3} />}
        <label className="d-block mt-3">{t('clients.noteTitle')}
          <textarea className="form-control" value={notes} disabled={busy} onChange={event => setNotes(event.target.value)} rows={3} />
        </label>
        <div className="mt-3"><span>{t('clients.usage')}: </span>
          <span className="usage-badge" style={{ color: usageColor }}>
            {formatBytes(client.up)} / {formatBytes(client.down)} ({formatBytes(used)})
          </span>
          <button className="btn btn-sm btn-ghost-secondary ms-2" title={t('clients.resetTraffic')}
            disabled={busy} onClick={() => void resetTraffic()}>{t('clients.resetTraffic')}</button>
          {client.total > 0 && <div className="mt-1"><div className="progress-track">
            <div className="progress-track__fill" style={{ width: `${pct}%`, background: usageColor }} />
          </div><div>{t('clients.usageOfTotal', { pct: pct.toFixed(1), total: formatBytes(client.total) })}</div></div>}
        </div>
      </div>
      <div className="drawer__footer"><button className="btn btn-sm btn-ghost-accent" disabled={busy} onClick={onClose}>
        {t('common.close')}</button><button className="btn btn-primary" disabled={!value || !expected || busy}
          onClick={() => void save()}>{t('common.save')}</button></div>
    </div>
  </div>;
}
