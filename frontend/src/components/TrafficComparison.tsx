import { useEffect, useState, type PointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { getTrafficComparison, type TrafficComparisonData } from '../api/trafficComparison';

type Point = { ts: number; value: number };
type Client = TrafficComparisonData['top_clients'][number];

function formatBytes(value: number) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = value > 0 ? Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4) : 0;
  return `${(value / 1024 ** index).toFixed(1)} ${units[index]}`;
}

function percent(value: number | null) {
  return value === null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function change(current: number, previous: number | null) {
  return previous ? (current - previous) * 100 / previous : null;
}

function niceTicks(maximum: number) {
  const unit = 1024 ** Math.min(Math.floor(Math.log(Math.max(maximum, 1)) / Math.log(1024)), 4);
  const raw = Math.max(maximum, 1) / unit / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].find(n => n * magnitude >= raw)! * magnitude * unit;
  return Array.from({ length: Math.ceil(maximum / step) + 1 || 2 }, (_, i) => i * step);
}

function chartPath(series: Point[], maximum: number) {
  const coords = series.map((p, i) => [60 + i * 530 / Math.max(series.length - 1, 1), 210 - p.value / maximum * 190]);
  if (!coords.length) return '';
  return `M ${coords[0][0]} ${coords[0][1]} ` + coords.slice(1).map((p, i) => {
    const mid = (coords[i][0] + p[0]) / 2;
    return `C ${mid} ${coords[i][1]}, ${mid} ${p[1]}, ${p[0]} ${p[1]}`;
  }).join(' ');
}

function ComparisonChart({ current, previous, range }: { current: Point[]; previous: Point[]; range: string }) {
  const { t, i18n } = useTranslation();
  const [hover, setHover] = useState<number | null>(null);
  const ticks = niceTicks(Math.max(1, ...current.map(p => p.value), ...previous.map(p => p.value)));
  const max = ticks[ticks.length - 1];
  const path = chartPath(current, max);
  const point = hover === null ? null : current[hover];
  const prior = hover === null ? null : previous[hover]?.value ?? null;
  const x = hover === null ? 0 : 60 + hover * 530 / Math.max(current.length - 1, 1);
  const y = point ? 210 - point.value / max * 190 : 0;
  const move = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const pos = (event.clientX - rect.left) / rect.width * 600;
    setHover(Math.max(0, Math.min(current.length - 1, Math.round((pos - 60) / 530 * (current.length - 1)))));
  };
  const indices = Array.from({ length: Math.min(6, current.length) }, (_, i) => Math.round(i * (current.length - 1) / (Math.min(6, current.length) - 1 || 1)));
  return <div className="tc-chart-wrap">
    <svg className="tc-chart" viewBox="0 0 600 240" preserveAspectRatio="none" role="img" aria-label={t('comparison.totalTraffic')} onPointerMove={move} onPointerDown={move} onPointerLeave={() => setHover(null)}>
      <defs>
      <linearGradient id="tc-fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor="var(--ln-accent)" stopOpacity=".25" />
      <stop offset="100%" stopColor="var(--ln-accent)" stopOpacity="0" />
      </linearGradient>
      </defs>
      {ticks.map(tick => <g key={tick}>
      <line className="tc-gridline" x1="60" x2="590" y1={210 - tick / max * 190} y2={210 - tick / max * 190} />
      <text x="54" y={214 - tick / max * 190} textAnchor="end">
      {formatBytes(tick)}
      </text>
      </g>)}
      {indices.map(i => <text key={i} x={60 + i * 530 / Math.max(current.length - 1, 1)} y="234" textAnchor={i === 0 ? 'start' : i === current.length - 1 ? 'end' : 'middle'}>
      {new Date(current[i].ts * 1000).toLocaleString(i18n.language, range === '24h' ? { hour: '2-digit', minute: '2-digit' } : { day: 'numeric', month: 'short' })}
      </text>)}
      {path && <path fill="url(#tc-fill)" d={`${path} L 590 210 L 60 210 Z`} />}
      <path className="tc-previous" d={chartPath(previous, max)} />
      <path className="tc-current" d={path} />
      {current.length > 0 && <circle className="tc-dot" cx="590" cy={210 - current[current.length - 1].value / max * 190} r="3" />}
      {point && <>
      <line className="tc-crosshair" x1={x} x2={x} y1="20" y2="210" />
      <circle className="tc-dot" cx={x} cy={y} r="4" />
      </>}
    </svg>
    {point && <div className="tc-tooltip" style={{ left: `${x / 6}%`, transform: `translateX(-${x / 6}%)` }}>
      <strong>
      {new Date(point.ts * 1000).toLocaleString(i18n.language)}
      </strong>
      <span>
      {t('comparison.current')}: {formatBytes(point.value)}
      </span>
      <span>
      {t('comparison.previous')}: {prior === null ? '—' : formatBytes(prior)}
      </span>
      <span>
      {percent(change(point.value, prior))} {t('comparison.toComparison')}
      </span>
      </div>}
  </div>;
}

function StatTile({ label, children }: { label: string; children: React.ReactNode }) {
  return <div>
      <span>
      {label}
      </span>
      {children}
      </div>;
}

function TopUsers({ data, node, sort, setSort, error }: { data: TrafficComparisonData | null; node: string; sort: string; setSort: (s: string) => void; error: boolean }) {
  const { t } = useTranslation();
  const top = [...(data?.top_clients ?? [])].sort((a, b) => sort === 'growth' ? (b.delta_pct ?? -Infinity) - (a.delta_pct ?? -Infinity) : b.current - a.current);
  const max = Math.max(1, ...top.flatMap((c: Client) => [c.current, c.previous ?? 0]));
  const topTotal = top.reduce((sum, c) => sum + c.current, 0);
  return <section className="tc-card">
      <div className="tc-head">
      <h3>
      {t('comparison.topUsers')}
      </h3>
      <div className="tc-segments">
      {(['current', 'growth'] as const).map(s => <button type="button" key={s} aria-pressed={sort === s} onClick={() => setSort(s)}>
      {t(`comparison.${s}`)}
      </button>)}
      </div>
      </div>
    {node && <p>
      {t('comparison.nodeClientsUnavailable')}
      </p>}
    {!node && data && top.length === 0 && <p>
      {t('comparison.noClients')}
      </p>}
    {!data && !error && <div className="tc-skeleton tc-skeleton-rows" />}
    <div className="tc-rows">
      {top.map((c, i) => <div className="tc-row" key={c.email}>
      <span>
      {i + 1}
      </span>
      <div className="tc-user">
      <span title={c.email}>
      {c.email}
      </span>
      <div className="tc-bars">
      <i style={{ width: `${c.current / max * 100}%` }} />
      <i style={{ width: `${(c.previous ?? 0) / max * 100}%` }} />
      </div>
      </div>
      <div className="tc-value">
      {formatBytes(c.current)}<em className={c.delta_pct === null ? '' : c.delta_pct < 0 ? 'tc-negative' : 'tc-positive'}>
      {percent(c.delta_pct)}
      </em>
      </div>
      </div>)}
      </div>
    <div className="tc-tiles">
      <StatTile label={t('comparison.topUse')}>
      <strong>
      {data && !node ? formatBytes(topTotal) : '—'}
      </strong>
      </StatTile>
      <StatTile label={t('comparison.share')}>
      <strong title={data && topTotal > data.totals.current && !node ? t('comparison.shareSourceHint') : undefined}>
      {data?.totals.current && !node ? topTotal > data.totals.current ? '≈100%' : `${Math.min(100, topTotal / data.totals.current * 100).toFixed(1)}%` : '—'}
      </strong>
      </StatTile>
      </div>
  </section>;
}

export function TrafficComparison({ nodes }: { nodes: { id: number; name: string }[] }) {
  const { t } = useTranslation();
  const [range, setRange] = useState('24h');
  const [node, setNode] = useState('');
  const [sort, setSort] = useState('current');
  const [data, setData] = useState<TrafficComparisonData | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(false);
    getTrafficComparison(range, node, controller.signal).then(setData).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [range, node, attempt]);
  const total = data?.totals.current ?? 0;
  const prev = data?.totals.previous ?? null;
  const delta = change(total, prev);
  return <div className="tc-grid" data-testid="traffic-comparison">
    <section className="tc-card">
      <div className="tc-head">
      <h3>
      {t('comparison.totalTraffic')}
      </h3>
      <div className="tc-controls">
      <select aria-label={t('comparison.nodes')} value={node} onChange={e => setNode(e.target.value)}>
      <option value="">
      {t('comparison.allNodes')}
      </option>
      {nodes.map(n => <option key={n.id} value={n.id}>
      {n.name}
      </option>)}
      </select>
      </div>
      </div>
      <div className="tc-range">
      <div className="tc-segments">
      {(['24h', '7d', '30d'] as const).map(r => <button type="button" key={r} aria-pressed={range === r} onClick={() => setRange(r)}>
      {t(`comparison.range_${r}`)}
      </button>)}
      </div>
      <span>
      {t('comparison.comparedPeriod', { period: t(`comparison.range_${range}`) })}
      </span>
      </div>
      {error ? <div className="tc-state">
      <p>
      {t('comparison.error')}
      </p>
      <button type="button" onClick={() => setAttempt(attempt + 1)}>
      {t('comparison.retry')}
      </button>
      </div> : !data ? <div className="tc-skeleton tc-skeleton-chart" /> : <>
        <ComparisonChart current={data.series_current} previous={data.series_previous} range={range} />
        {prev === null && <p className="tc-hint">
      {t('comparison.historyHint', { days: data.history_days ?? 0, required: range === '24h' ? 2 : range === '7d' ? 14 : 60 })}
      </p>}
        <div className="tc-tiles">
      <StatTile label={t('comparison.currentPeriod')}>
      <strong>
      {formatBytes(total)} <em className={delta === null ? '' : delta < 0 ? 'tc-negative' : 'tc-positive'}>
      {percent(delta)}
      </em>
      </strong>
      </StatTile>
      <StatTile label={t('comparison.previousPeriod')}>
      <strong>
      {prev === null ? '—' : formatBytes(prev)}
      </strong>
      <small>
      {prev === null ? '—' : `${total >= prev ? '+' : '−'}${formatBytes(Math.abs(total - prev))}`}
      </small>
      </StatTile>
      <StatTile label={t('comparison.legend')}>
      <small>
      <i className="tc-legend" /> {t('comparison.current')}<br />
      <i className="tc-legend tc-legend-previous" /> {t('comparison.previous')}
      </small>
      </StatTile>
      </div>
      </>}
    </section>
    <TopUsers data={data} node={node} sort={sort} setSort={setSort} error={error} />
  </div>;
}
