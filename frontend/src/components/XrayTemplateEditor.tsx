import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getXrayTemplate, updateXrayTemplate, type TemplateSection } from '../api/serverOps';
import { useToast } from './Toast';

export function XrayTemplateEditor({ nodeId, section }: { nodeId: number; section: TemplateSection }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [text, setText] = useState('');
  const [original, setOriginal] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    const template = await getXrayTemplate(nodeId, signal);
    const value = section === 'all' ? template : template[section];
    const formatted = JSON.stringify(value ?? (section === 'outbounds' ? [] : {}), null, 2);
    if (!signal?.aborted) { setText(formatted); setOriginal(formatted); }
  }, [nodeId, section]);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).catch((err) => { if (!controller.signal.aborted) setError(err?.response?.data?.detail || err.message); });
    return () => controller.abort();
  }, [load]);
  let parseError = '';
  let value: unknown;
  try { value = JSON.parse(text); } catch (err) { parseError = text ? String(err) : ''; }
  const valid = section === 'outbounds' ? Array.isArray(value) && value.every((v) => v && typeof v === 'object' && !Array.isArray(v)) : !!value && typeof value === 'object' && !Array.isArray(value);
  const reload = async () => {
    if (text !== original && !window.confirm(t('nodeOps.discard'))) return;
    setBusy(true); setError('');
    try { await load(); } catch (err: any) { setError(err?.response?.data?.detail || err.message); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!window.confirm(t('nodeOps.confirmApply'))) return;
    setBusy(true); setError('');
    try { await updateXrayTemplate(nodeId, section, value, JSON.parse(original)); toast(t('nodeOps.applied'), 'success'); await load(); }
    catch (err: any) { setError(err?.response?.data?.detail || err.message); }
    finally { setBusy(false); }
  };
  return <div className="flex min-h-0 flex-1 flex-col gap-3">
    <div className="flex flex-wrap gap-2">
      <button type="button" className="rounded border border-cyan-500/30 px-3 py-2 text-xs text-slate-200 disabled:opacity-40" disabled={busy || !valid || text === original || !original} onClick={() => void save()}>{t('nodeOps.saveApply')}</button>
      <button type="button" className="rounded border border-cyan-500/30 px-3 py-2 text-xs text-slate-200" disabled={busy} onClick={() => void reload()}>{t('nodeOps.reload')}</button>
      <button type="button" className="rounded border border-cyan-500/30 px-3 py-2 text-xs text-slate-200" onClick={() => void navigator.clipboard.writeText(text).catch(() => setError(t('serverStatus.clipboardUnavailable')))}>{t('common.copy')}</button>
    </div>
    {(error || parseError || (text && !valid ? t('nodeOps.invalidShape') : '')) && <div role="alert" className="text-sm text-rose-300">{error || parseError || t('nodeOps.invalidShape')}</div>}
    <textarea aria-label={t('nodeOps.template')} className="min-h-0 w-full flex-1 resize-none rounded border border-cyan-500/20 bg-[#07101d] p-3 font-mono text-xs text-slate-200" value={text} disabled={busy || !original} onChange={(event) => setText(event.target.value)} />
  </div>;
}
