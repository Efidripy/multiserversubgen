import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LazyJsonEditor } from './LazyJsonEditor';
import { getXrayTemplate, updateXrayTemplate } from '../api/serverOps';

type Row = { email?: string; tag?: string; remark?: string; upload?: number; download?: number; up?: number; down?: number; total?: number; enable?: boolean };
const record = (value: unknown): Record<string, any> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {};
const bytes = (value: number) => { let n = Number(value) || 0; const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']; let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${units[i]}`; };
const button = 'btn btn-sm btn-ghost-secondary';
type SortKey = 'name' | 'download' | 'upload' | 'total';
type Sort = { key: SortKey; ascending: boolean };
const initialSort: Sort = { key: 'total', ascending: false };

export function NodeDataView({ nodeId, kind, data, loading, refresh, copy }: { nodeId: number; kind: 'traffic' | 'online' | 'outbounds'; data: unknown; loading: boolean; refresh: () => void; copy: () => void }) {
  const { t } = useTranslation();
  const [json, setJson] = useState(false);
  const [search, setSearch] = useState('');
  const [sorts, setSorts] = useState<Record<string, Sort>>({ email: initialSort, remark: initialSort, tag: initialSort });
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
  const rows = (kind === 'traffic' ? clients : outboundRows).filter((row) => String(row.email || row.tag || '').toLowerCase().includes(search.toLowerCase()));
  const max = Math.max(0, ...clients.map((row) => Number(row.total) || 0));
  const table = (items: Row[], label: 'email' | 'tag' | 'remark', bars = false) => {
    const sort = sorts[label];
    const number = (row: Row, key: SortKey) => key === 'download' ? Number(row.download ?? row.down) || 0 : key === 'upload' ? Number(row.upload ?? row.up) || 0 : Number(row.total ?? ((Number(row.upload ?? row.up) || 0) + (Number(row.download ?? row.down) || 0))) || 0;
    const sorted = [...items].filter((row) => String(row[label] || '').toLowerCase().includes(search.toLowerCase())).sort((a, b) => (sort.key === 'name' ? String(a[label] || '').localeCompare(String(b[label] || '')) : number(a, sort.key) - number(b, sort.key)) * (sort.ascending ? 1 : -1));
    const columns: [SortKey, string][] = [['name', label === 'email' ? t('clients.email') : label === 'tag' ? t('nodeOps.tag') : t('nav.inbounds')], ['download', t('traffic.download')], ['upload', t('traffic.upload')], ['total', t('traffic.total')]];
    return <div className="overflow-x-auto"><table className="table table-sm min-w-[480px]"><thead><tr>{columns.map(([key, name]) => <th key={key} aria-sort={sort.key === key ? (sort.ascending ? 'ascending' : 'descending') : 'none'}><button type="button" className="node-ops-sort" onClick={() => setSorts((current) => ({ ...current, [label]: { key, ascending: current[label].key === key ? !current[label].ascending : key === 'name' } }))}>{name} {sort.key === key && (sort.ascending ? '\u2191' : '\u2193')}</button></th>)}</tr></thead><tbody>{sorted.map((row, i) => <tr key={`${row[label]}-${i}`}><td>{row[label]} {row.enable === false && <span className="node-ops-warning">{t('common.disabled')}</span>}{bars && <div className="node-ops-bar"><div style={{ width: `${max ? (Number(row.total) || 0) / max * 100 : 0}%` }} /></div>}</td><td>{bytes(number(row, 'download'))}</td><td>{bytes(number(row, 'upload'))}</td><td>{bytes(number(row, 'total'))}</td></tr>)}</tbody></table></div>;
  };
  return <div className="flex min-h-0 flex-1 flex-col gap-3">
    <div className="flex flex-wrap gap-2"><button type="button" className={`seg-tab ${!json ? 'seg-tab--active' : ''}`} aria-pressed={!json} onClick={() => setJson(false)}>{t('nodeOps.table')}</button><button type="button" className={`seg-tab ${json ? 'seg-tab--active' : ''}`} aria-pressed={json} onClick={() => setJson(true)}>JSON</button><button type="button" className={button} disabled={loading} onClick={refresh}>{t('common.refresh')}</button><button type="button" className={button} disabled={data == null} onClick={copy}>{t('common.copy')}</button></div>
    {kind === 'outbounds' && <><button type="button" role="switch" aria-checked={enabled} className={`${button} self-start`} disabled={!template || busy} onClick={() => void toggle()}>{t('nodeOps.outboundStats')}: {t(enabled ? 'common.enabled' : 'common.disabled')}</button>{templateError && <div role="alert" className="text-sm node-ops-error">{templateError}</div>}</>}
    {unavailable && <div role="alert" className="text-sm node-ops-error">{String(payload.error || t('nodeOps.nodeUnavailable'))}</div>}
    {json ? <LazyJsonEditor readOnly label={t('nodeOps.jsonView')} value={JSON.stringify(data, null, 2) || ''} /> : !unavailable && <div className="min-h-0 flex-1 overflow-auto text-sm">
      {kind === 'traffic' && <p className="mb-3">{t('nodeOps.overall')}: {bytes(clients.reduce((sum, row) => sum + (Number(row.total) || 0), 0))}</p>}
      {kind === 'online' && <p className="mb-3">{t('nodeOps.onlineCount', { count: online.length })}</p>}
      {<input className="form-control mb-3 w-full" placeholder={t('nodeOps.search')} value={search} onChange={(e) => setSearch(e.target.value)} />}
      {kind === 'online' ? <ul>{online.filter((email) => email.toLowerCase().includes(search.toLowerCase())).map((email, i) => <li className="node-ops-row p-2" key={`${email}-${i}`}>{email} <span className="node-ops-success">{t('nodeOps.online')}</span></li>)}</ul> : table(rows, kind === 'traffic' ? 'email' : 'tag', kind === 'traffic')}
      {kind === 'traffic' && <><h4 className="mt-5">{t('nav.inbounds')}</h4>{table(inbounds, 'remark')}</>}
    </div>}
  </div>;
}
