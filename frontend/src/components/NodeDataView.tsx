import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getXrayTemplate, updateXrayTemplate } from '../api/serverOps';

type Row = { email?: string; tag?: string; remark?: string; upload?: number; download?: number; up?: number; down?: number; total?: number; enable?: boolean };
const record = (value: unknown): Record<string, any> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {};
const bytes = (value: number) => { let n = Number(value) || 0; const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']; let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${units[i]}`; };
const button = 'rounded border border-cyan-500/30 bg-[#0a0e1a] px-3 py-2 text-xs text-slate-200 disabled:opacity-40';

export function NodeDataView({ nodeId, kind, data, loading, refresh, copy }: { nodeId: number; kind: 'traffic' | 'online' | 'outbounds'; data: unknown; loading: boolean; refresh: () => void; copy: () => void }) {
  const { t } = useTranslation();
  const [json, setJson] = useState(false);
  const [search, setSearch] = useState('');
  const [template, setTemplate] = useState<Record<string, any> | null>(null);
  const [templateError, setTemplateError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (kind !== 'outbounds') return;
    const controller = new AbortController();
    setTemplate(null); setTemplateError('');
    getXrayTemplate(nodeId, controller.signal).then((value) => {
      if (!controller.signal.aborted) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) setTemplateError(t('nodeOps.templateUnavailable'));
        else setTemplate(value);
      }
    }).catch((err) => { if (!controller.signal.aborted) setTemplateError(err?.response?.data?.detail || err?.message || t('nodeOps.templateUnavailable')); });
    return () => controller.abort();
  }, [kind, nodeId, t]);
  const system = record(record(template?.policy).system);
  const enabled = Boolean(system.statsOutboundUplink && system.statsOutboundDownlink);
  const toggle = async () => {
    if (!template || !window.confirm(t('nodeOps.confirmOutboundStats'))) return;
    const next = !enabled;
    const value = { ...template, policy: { ...record(template.policy), system: { ...system, statsOutboundUplink: next, statsOutboundDownlink: next } }, ...(next && !('stats' in template) ? { stats: {} } : {}) };
    setBusy(true); setTemplateError('');
    try { await updateXrayTemplate(nodeId, 'all', value, template); setTemplate(value); }
    catch (err: any) { setTemplateError(err?.response?.data?.detail || err?.message || t('common.failed')); }
    finally { setBusy(false); }
  };
  const payload = record(data);
  const unavailable = payload.error || payload.available === false;
  const clients: Row[] = Array.isArray(payload.clients) ? payload.clients : [];
  const inbounds: Row[] = Array.isArray(payload.traffic) ? payload.traffic : [];
  const online: string[] = Array.isArray(payload.online_clients) ? payload.online_clients.map((item: any) => typeof item === 'string' ? item : item?.email).filter((item: unknown): item is string => typeof item === 'string' && !!item) : [];
  const outboundRows: Row[] = Array.isArray(data) ? [...data] : [];
  if (kind === 'outbounds' && Array.isArray(template?.outbounds)) for (const item of template.outbounds) {
    if (item?.tag && !outboundRows.some((row) => row.tag === item.tag)) outboundRows.push({ tag: item.tag, up: 0, down: 0, total: 0 });
  }
  const rows = (kind === 'traffic' ? [...clients].sort((a, b) => (b.total || 0) - (a.total || 0)) : outboundRows).filter((row) => String(row.email || row.tag || '').toLowerCase().includes(search.toLowerCase()));
  const max = Math.max(0, ...clients.map((row) => Number(row.total) || 0));
  const table = (items: Row[], label: 'email' | 'tag' | 'remark', bars = false) => <div className="overflow-x-auto"><table className="w-full min-w-[480px] text-left text-xs text-slate-200"><thead className="text-slate-400"><tr>{[label === 'email' ? t('clients.email') : label === 'tag' ? t('nodeOps.tag') : t('nav.inbounds'), t('traffic.download'), t('traffic.upload'), t('traffic.total')].map((name) => <th className="p-2" key={name}>{name}</th>)}</tr></thead><tbody>{items.map((row, i) => <tr className="border-t border-slate-700" key={`${row[label]}-${i}`}><td className="p-2">{row[label]} {row.enable === false && <span className="text-amber-300">{t('common.disabled')}</span>}{bars && <div className="mt-1 h-1 w-24 bg-slate-700"><div className="h-full bg-cyan-400" style={{ width: `${max ? (Number(row.total) || 0) / max * 100 : 0}%` }} /></div>}</td><td className="p-2">{bytes(Number(row.download ?? row.down))}</td><td className="p-2">{bytes(Number(row.upload ?? row.up))}</td><td className="p-2">{bytes(Number(row.total ?? ((row.up || 0) + (row.down || 0))))}</td></tr>)}</tbody></table></div>;
  return <div className="flex min-h-0 flex-1 flex-col gap-3">
    <div className="flex flex-wrap gap-2"><button type="button" className={button} aria-pressed={!json} onClick={() => setJson(false)}>{t('nodeOps.table')}</button><button type="button" className={button} aria-pressed={json} onClick={() => setJson(true)}>JSON</button><button type="button" className={button} disabled={loading} onClick={refresh}>{t('common.refresh')}</button><button type="button" className={button} disabled={data == null} onClick={copy}>{t('common.copy')}</button></div>
    {kind === 'outbounds' && <><button type="button" role="switch" aria-checked={enabled} className={`${button} self-start`} disabled={!template || busy} onClick={() => void toggle()}>{t('nodeOps.outboundStats')}: {t(enabled ? 'common.enabled' : 'common.disabled')}</button>{templateError && <div role="alert" className="text-sm text-rose-300">{templateError}</div>}</>}
    {unavailable && <div role="alert" className="text-sm text-rose-300">{String(payload.error || t('nodeOps.nodeUnavailable'))}</div>}
    {json ? <pre className="min-h-0 flex-1 overflow-auto rounded border border-cyan-500/20 bg-[#07101d] p-3 text-xs text-slate-200">{JSON.stringify(data, null, 2) || t('common.noRecordsFound')}</pre> : !unavailable && <div className="min-h-0 flex-1 overflow-auto text-sm text-slate-200">
      {kind === 'traffic' && <p className="mb-3">{t('nodeOps.overall')}: {bytes(clients.reduce((sum, row) => sum + (Number(row.total) || 0), 0))}</p>}
      {kind === 'online' && <p className="mb-3">{t('nodeOps.onlineCount', { count: online.length })}</p>}
      {kind !== 'outbounds' && <input className="mb-3 w-full rounded border border-cyan-500/20 bg-[#0a0e1a] p-2 text-slate-200" placeholder={t('nodeOps.search')} value={search} onChange={(e) => setSearch(e.target.value)} />}
      {kind === 'online' ? <ul>{online.filter((email) => email.toLowerCase().includes(search.toLowerCase())).map((email, i) => <li className="border-b border-slate-700 p-2" key={`${email}-${i}`}>{email} <span className="text-emerald-300">{t('nodeOps.online')}</span></li>)}</ul> : table(rows, kind === 'traffic' ? 'email' : 'tag', kind === 'traffic')}
      {kind === 'traffic' && <><h4 className="mt-5 text-slate-300">{t('nav.inbounds')}</h4>{table(inbounds, 'remark')}</>}
    </div>}
  </div>;
}
