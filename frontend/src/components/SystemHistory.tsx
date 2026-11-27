import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js';
import { Line } from 'react-chartjs-2';
import { getServerHistory } from '../api/serverOps';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);
const groups = {
  cpu: ['cpu'], ram: ['mem', 'swap'], bandwidth: ['netUp', 'netDown'], packets: ['pktUp', 'pktDown'],
  connections: ['tcpCount', 'udpCount'], diskIO: ['diskRead', 'diskWrite'], diskUsage: ['diskUsage'], online: ['online'], load: ['load1', 'load5', 'load15'],
} as const;
const names: Record<string, string> = {
  cpu: 'CPU', mem: 'RAM', swap: 'Swap', netUp: 'Up', netDown: 'Down', pktUp: 'Up', pktDown: 'Down', tcpCount: 'TCP', udpCount: 'UDP',
  diskRead: 'Read', diskWrite: 'Write', diskUsage: 'Disk', online: 'Online', load1: '1m', load5: '5m', load15: '15m',
};
type Group = keyof typeof groups;
type Point = { t: number; v: number };
const colors = ['#22d3ee', '#fb7185', '#a78bfa'];
export function SystemHistory({ nodeId }: { nodeId: number }) {
  const { t, i18n } = useTranslation();
  const [group, setGroup] = useState<Group>('cpu');
  const [bucket, setBucket] = useState(2);
  const [series, setSeries] = useState<Point[][]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let generation = 0;
    const run = async () => {
      if (stopped || document.hidden) return;
      const id = ++generation;
      controller = new AbortController();
      try {
        const results = await Promise.allSettled(groups[group].map((metric) => getServerHistory(nodeId, metric, bucket, controller?.signal)));
        const failure = results.find((result) => result.status === 'rejected');
        if (failure?.status === 'rejected') throw failure.reason;
        const data = results.map((result) => result.status === 'fulfilled' ? result.value : []);
        if (!stopped && id === generation) { setSeries(data); setError(''); }
      } catch (err: any) { if (!stopped && id === generation && !controller.signal.aborted) setError(err?.response?.data?.detail || err.message); }
      finally { if (!stopped && id === generation && !document.hidden) timer = setTimeout(run, bucket <= 30 ? 2000 : 10000); }
    };
    const visibility = () => { if (document.hidden) { generation++; controller?.abort(); if (timer) clearTimeout(timer); } else void run(); };
    setSeries([]); setError(''); void run();
    document.addEventListener('visibilitychange', visibility);
    return () => { stopped = true; generation++; controller?.abort(); if (timer) clearTimeout(timer); document.removeEventListener('visibilitychange', visibility); };
  }, [nodeId, group, bucket]);
  const timestamps = Array.from(new Set(series.flatMap((s) => s.map((p) => p.t)))).sort((a, b) => a - b);
  const percent = group === 'cpu' || group === 'ram' || group === 'diskUsage';
  const bytes = group === 'bandwidth' || group === 'diskIO';
  const format = (n: number) => {
    if (percent) return `${n}%`;
    if (bytes) { const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']; let i = 0; while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${units[i]}`; }
    if (group === 'packets') return `${n} pkt/s`;
    return group === 'load' ? String(n) : String(Math.round(n));
  };
  const labels = timestamps.map((stamp) => new Date(stamp * 1000).toLocaleString(i18n.language, 60 >= bucket ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }));
  return <div className="space-y-3">
    <select aria-label={t('nodeOps.interval')} className="rounded border border-cyan-500/30 bg-[#0a0e1a] p-2 text-slate-200" value={bucket} onChange={(e) => setBucket(Number(e.target.value))}>{[[2,'2m'],[60,'1h'],[180,'3h'],[360,'6h'],[720,'12h'],[1440,'24h'],[2880,'2d'],[10080,'7d']].map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select>
    <div className="flex flex-wrap gap-2">{(Object.keys(groups) as Group[]).map((key) => <button type="button" key={key} aria-pressed={group === key} className={`rounded border border-cyan-500/30 px-3 py-2 text-xs text-slate-200 ${group === key ? 'bg-cyan-400/20' : ''}`} onClick={() => setGroup(key)}>{t(`nodeOps.${key}`)}</button>)}</div>
    {error && <div role="alert" className="text-rose-300">{error}</div>}
    <div className="relative h-72 min-w-0"><Line data={{ labels, datasets: groups[group].map((metric, index) => ({ label: names[metric], data: timestamps.map((stamp) => series[index]?.find((p) => p.t === stamp)?.v ?? null), borderColor: colors[index], backgroundColor: colors[index], pointRadius: 0, tension: 0.2 })) }} options={{ responsive: true, maintainAspectRatio: false, animation: false, scales: { x: { ticks: { color: '#94a3b8', maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } }, y: { grid: { color: 'rgba(148,163,184,0.15)' }, ...(percent ? { min: 0, max: 100 } : {}), ticks: { color: '#94a3b8', callback: (v) => format(Number(v)) } } }, plugins: { legend: { labels: { color: '#cbd5e1', boxWidth: 12 } }, tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${format(ctx.parsed.y ?? 0)}` } } } }} /></div>
  </div>;
}
