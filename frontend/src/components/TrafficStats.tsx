import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { mergeStaleCacheRecord, readStaleCache } from '../services/staleCache';
import { useTrafficStatsSubscription, TrafficUpdate } from '../services/useTrafficStatsSubscription';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

const barGlowPlugin = {
  id: 'barGlowPlugin',
  beforeDatasetsDraw(chart: any) {
    const { ctx } = chart;
    ctx.save();
    ctx.shadowColor = 'rgba(6, 182, 212, 0.45)';
    ctx.shadowBlur = 14;
    ctx.shadowOffsetY = 0;
  },
  afterDatasetsDraw(chart: any) {
    chart.ctx.restore();
  },
};

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  barGlowPlugin
);

interface TrafficData {
  email: string;
  node_name?: string;
  protocol?: string;
  upload: number;
  download: number;
  total: number;
}

interface OnlineClient {
  email: string;
  node_name: string;
}

const normalizeEmailKey = (email: string): string => email.trim().toLowerCase();
const TRAFFIC_STATS_CACHE_KEY = 'sub_manager_traffic_stats_cache_v1';
const TRAFFIC_STATS_CACHE_MAX_AGE_MS = 10 * 60 * 1000;

type TrafficStatsCache = {
  trafficData?: TrafficData[];
  onlineClients?: OnlineClient[];
  onlineTrafficTotals?: Record<string, number>;
};

export const TrafficStats: React.FC<{ onNavigateToClient?: (email: string) => void }> = ({ onNavigateToClient }) => {
  const { t } = useTranslation();
  const { stylePreset } = useTheme();
  const [trafficData, setTrafficData] = useState<TrafficData[]>([]);
  const [onlineClients, setOnlineClients] = useState<OnlineClient[]>([]);
  const [onlineTrafficTotals, setOnlineTrafficTotals] = useState<Record<string, number>>({});
  const [periodNote, setPeriodNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [onlineLoading, setOnlineLoading] = useState(false);
  const [error, setError] = useState('');
  const [groupBy, setGroupBy] = useState<'client' | 'inbound' | 'node'>('client');
  const [period, setPeriod] = useState<'day' | 'week' | 'month' | 'year' | 'all_time'>('all_time');
  const [topN, setTopN] = useState(10);
  const [filterNodeName, setFilterNodeName] = useState('');
  const [trafficSearch, setTrafficSearch] = useState('');
  const [trafficSortField, setTrafficSortField] = useState<'name' | 'download' | 'upload' | 'total'>('download');
  const [trafficSortDir, setTrafficSortDir] = useState<'asc' | 'desc'>('desc');
  const [onlineSortField, setOnlineSortField] = useState<'email' | 'node' | 'traffic'>('email');
  const [onlineSortDir, setOnlineSortDir] = useState<'asc' | 'desc'>('asc');
  const trafficRequestRef = useRef(0);
  const trafficAbortRef = useRef<AbortController | null>(null);
  const onlineAbortRef = useRef<AbortController | null>(null);
  const onlineTotalsAbortRef = useRef<AbortController | null>(null);
  const chartAccent = stylePreset === '3' ? '#fafafa' : stylePreset === '4' ? '#22d3ee' : 'var(--accent)';

  useEffect(() => {
    const cached = readStaleCache<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, TRAFFIC_STATS_CACHE_MAX_AGE_MS);
    if (cached.data) {
      if (Array.isArray(cached.data.trafficData)) setTrafficData(cached.data.trafficData);
      if (Array.isArray(cached.data.onlineClients)) setOnlineClients(cached.data.onlineClients);
      if (cached.data.onlineTrafficTotals && typeof cached.data.onlineTrafficTotals === 'object') {
        setOnlineTrafficTotals(cached.data.onlineTrafficTotals);
      }
    }

    loadTrafficStats(groupBy, period, { silent: cached.isFresh });
    loadOnlineClients(cached.isFresh);
    loadOnlineTrafficTotals(period);
  }, []);

  useEffect(() => () => {
    trafficAbortRef.current?.abort();
    onlineAbortRef.current?.abort();
    onlineTotalsAbortRef.current?.abort();
  }, []);

  const loadTrafficStats = async (
    nextGroupBy: 'client' | 'inbound' | 'node' = groupBy,
    nextPeriod: 'day' | 'week' | 'month' | 'year' | 'all_time' = period,
    options?: { silent?: boolean },
  ) => {
    const requestId = ++trafficRequestRef.current;
    const limit = Math.max(topN * 12, 240);
    trafficAbortRef.current?.abort();
    const controller = new AbortController();
    trafficAbortRef.current = controller;

    if (!options?.silent) setLoading(true);
    setError('');
    setPeriodNote('');

    try {
      const res = await api.get('/v1/traffic/stats-by-period', {
        auth: getAuth(),
        params: { group_by: nextGroupBy, period: nextPeriod, limit },
        signal: controller.signal,
      });
      const statsObj: Record<string, { up: number; down: number; total: number }> = res.data?.stats || {};
      const parsed: TrafficData[] = Object.entries(statsObj).map(([key, s]) => {
        if (nextGroupBy === 'node') {
          return {
            email: key,
            node_name: key,
            upload: s.up || 0,
            download: s.down || 0,
            total: (s.total || 0) === 0 ? (s.up || 0) + (s.down || 0) : (s.total || 0),
          };
        }
        if (nextGroupBy === 'inbound') {
          const sep = key.indexOf(':');
          const nodeName = sep >= 0 ? key.slice(0, sep) : '';
          const inboundName = sep >= 0 ? key.slice(sep + 1) : key;
          return {
            email: inboundName || key,
            node_name: nodeName || undefined,
            upload: s.up || 0,
            download: s.down || 0,
            total: (s.total || 0) === 0 ? (s.up || 0) + (s.down || 0) : (s.total || 0),
          };
        }
        return {
          email: key,
          upload: s.up || 0,
          download: s.down || 0,
          total: (s.total || 0) === 0 ? (s.up || 0) + (s.down || 0) : (s.total || 0),
        };
      });

      if (requestId !== trafficRequestRef.current) return;
      setTrafficData(parsed);
      setPeriodNote(res.data?.note || '');
      mergeStaleCacheRecord<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, { trafficData: parsed });
    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') return;
      if (requestId !== trafficRequestRef.current) return;
      setError(err.response?.data?.detail || t('traffic.loadFailed'));
    } finally {
      if (requestId === trafficRequestRef.current && !options?.silent) {
        setLoading(false);
      }
    }
  };

  const loadOnlineClients = async (silent = false) => {
    onlineAbortRef.current?.abort();
    const controller = new AbortController();
    onlineAbortRef.current = controller;
    if (!silent) setOnlineLoading(true);
    try {
      const onlineRes = await api.get('/v1/clients/online', {
        auth: getAuth(),
        params: { limit: 500 },
        signal: controller.signal,
      });
      const items: Array<{ email: string; node?: string; node_name?: string; inbound_id?: number }> =
        onlineRes.data?.online_clients || [];
      setOnlineClients(
        items.map((c) => ({
          email: c.email,
          node_name: c.node_name || c.node || 'unknown',
        }))
      );
      mergeStaleCacheRecord<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, {
        onlineClients: items.map((c) => ({
          email: c.email,
          node_name: c.node_name || c.node || 'unknown',
        })),
      });
    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') return;
      console.error('Failed to load online clients:', err);
    } finally {
      if (!silent) setOnlineLoading(false);
    }
  };

  const loadOnlineTrafficTotals = async (
    nextPeriod: 'day' | 'week' | 'month' | 'year' | 'all_time' = period,
  ) => {
    onlineTotalsAbortRef.current?.abort();
    const controller = new AbortController();
    onlineTotalsAbortRef.current = controller;
    try {
      const res = await api.get('/v1/traffic/stats-by-period', {
        auth: getAuth(),
        params: { group_by: 'client', period: nextPeriod, limit: 1000 },
        signal: controller.signal,
      });
      const statsObj: Record<string, { up: number; down: number; total: number }> = res.data?.stats || {};
      const totals: Record<string, number> = {};
      Object.entries(statsObj).forEach(([email, s]) => {
        const key = normalizeEmailKey(email);
        if (!key) return;
        const value = (s.total || 0) === 0 ? (s.up || 0) + (s.down || 0) : (s.total || 0);
        totals[key] = (totals[key] || 0) + value;
      });
      setOnlineTrafficTotals(totals);
      mergeStaleCacheRecord<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, { onlineTrafficTotals: totals });
    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') return;
      console.error('Failed to load online traffic totals:', err);
    }
  };

  const handleRealtimeUpdate = useCallback(
    (update: TrafficUpdate) => {
      if (update.type === 'traffic_update') {
        loadTrafficStats(groupBy, period, { silent: true });
        loadOnlineTrafficTotals(period);
        return;
      }
      if (update.type === 'client_update') {
        loadOnlineClients(true);
        return;
      }
      if (update.type === 'server_status') {
        loadTrafficStats(groupBy, period, { silent: true });
      }
    },
    [groupBy, period],
  );

  useTrafficStatsSubscription({
    channels: ['traffic', 'clients', 'server_status'],
    onUpdate: handleRealtimeUpdate,
    onError: (err) => console.warn('[TrafficStats] realtime error:', err),
    fallbackPollIntervalMs: 60_000,
    fallbackRun: () => {
      loadTrafficStats(groupBy, period, { silent: true });
      loadOnlineClients(true);
      loadOnlineTrafficTotals(period);
    },
  });

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 GB';
    const gb = bytes / 1073741824;
    return gb.toFixed(2) + ' GB';
  };

  const compareText = (a: string, b: string) =>
    a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });
  const trafficSortFactor = trafficSortDir === 'asc' ? 1 : -1;
  const onlineSortFactor = onlineSortDir === 'asc' ? 1 : -1;

  const filteredTrafficData = trafficData
    .filter(d => !filterNodeName || d.node_name === filterNodeName)
    .filter(d => !trafficSearch.trim() || (d.email || d.node_name || '').toLowerCase().includes(trafficSearch.trim().toLowerCase()));

  const trafficNodeNames = Array.from(new Set(trafficData.map(d => d.node_name).filter(Boolean)));

  const sortedTraffic = [...filteredTrafficData]
    .sort((a, b) => {
      const aName = a.email || a.node_name || '';
      const bName = b.email || b.node_name || '';
      const byName = compareText(aName, bName);
      const byNode = compareText(a.node_name || '', b.node_name || '');

      if (trafficSortField === 'name') {
        if (byName !== 0) return byName * trafficSortFactor;
        if (byNode !== 0) return byNode * trafficSortFactor;
        return (a.total - b.total) * trafficSortFactor;
      }
      if (trafficSortField === 'download') {
        const byDownload = a.download - b.download;
        if (byDownload !== 0) return byDownload * trafficSortFactor;
        if (byName !== 0) return byName;
        if (byNode !== 0) return byNode;
        return a.total - b.total;
      }
      if (trafficSortField === 'upload') {
        const byUpload = a.upload - b.upload;
        if (byUpload !== 0) return byUpload * trafficSortFactor;
        return (a.total - b.total) * trafficSortFactor;
      }
      const byTotal = a.total - b.total;
      if (byTotal !== 0) return byTotal * trafficSortFactor;
      if (byName !== 0) return byName;
      if (byNode !== 0) return byNode;
      return a.download - b.download;
    })
    .slice(0, topN);

  const filteredOnlineClients = trafficSearch.trim()
    ? onlineClients.filter(c => c.email.toLowerCase().includes(trafficSearch.trim().toLowerCase()) || (c.node_name || '').toLowerCase().includes(trafficSearch.trim().toLowerCase()))
    : onlineClients;

  const sortedOnlineClients = [...filteredOnlineClients].sort((a, b) => {
    const aTraffic = onlineTrafficTotals[normalizeEmailKey(a.email)] || 0;
    const bTraffic = onlineTrafficTotals[normalizeEmailKey(b.email)] || 0;
    const byEmail = compareText(a.email, b.email);
    const byNode = compareText(a.node_name, b.node_name);
    const byTraffic = aTraffic - bTraffic;

    if (onlineSortField === 'email') {
      if (byEmail !== 0) return byEmail * onlineSortFactor;
      if (byNode !== 0) return byNode * onlineSortFactor;
      return byTraffic * onlineSortFactor;
    }
    if (onlineSortField === 'node') {
      if (byNode !== 0) return byNode * onlineSortFactor;
      if (byEmail !== 0) return byEmail * onlineSortFactor;
      return byTraffic * onlineSortFactor;
    }
    if (byTraffic !== 0) return byTraffic * onlineSortFactor;
    if (byEmail !== 0) return byEmail;
    return byNode;
  });

  const applyTrafficSortFromHeader = (field: 'name' | 'download' | 'upload' | 'total') => {
    if (trafficSortField === field) {
      setTrafficSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setTrafficSortField(field);
    setTrafficSortDir(field === 'name' ? 'asc' : 'desc');
  };

  const applyOnlineSortFromHeader = (field: 'email' | 'node' | 'traffic') => {
    if (onlineSortField === field) {
      setOnlineSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setOnlineSortField(field);
    setOnlineSortDir(field === 'traffic' ? 'desc' : 'asc');
  };

  const trafficSortIndicator = (field: 'name' | 'download' | 'upload' | 'total') =>
    trafficSortField === field ? (trafficSortDir === 'asc' ? ' ▲' : ' ▼') : '';

  const onlineSortIndicator = (field: 'email' | 'node' | 'traffic') =>
    onlineSortField === field ? (onlineSortDir === 'asc' ? ' ▲' : ' ▼') : '';

  const topByEntity =
    groupBy === 'client'
      ? t('traffic.entityClient')
      : groupBy === 'inbound'
      ? t('traffic.entityInbound')
      : t('traffic.entityServer');

  // Top Clients Bar Chart
  const topClientsData = {
    labels: sortedTraffic.map(d => d.email || d.node_name || t('traffic.unknown')),
    datasets: [
      {
        label: t('traffic.downloadGbLabel'),
        data: sortedTraffic.map(d => (d.download / 1073741824).toFixed(2)),
        backgroundColor: chartAccent + 'CC',
        borderColor: chartAccent,
        borderWidth: 1.2,
        borderRadius: 10,
        hoverBackgroundColor: chartAccent,
        hoverBorderColor: '#7dd3fc',
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
        labels: {
          color: 'var(--text-primary)',
          font: {
            size: 12,
            weight: 600 as const,
          },
          boxWidth: 12,
          boxHeight: 12,
        }
      },
      title: {
        display: false,
      },
      tooltip: {
        backgroundColor: 'rgba(8, 8, 8, 0.96)',
        borderColor: 'rgba(255, 255, 255, 0.18)',
        borderWidth: 1,
        titleColor: '#fafafa',
        bodyColor: '#d4d4d8',
        displayColors: false,
        padding: 10,
        cornerRadius: 10,
      },
    },
    interaction: {
      intersect: false,
      mode: 'index' as const,
    },
    scales: {
      x: {
        ticks: {
          color: 'var(--text-secondary)',
          font: {
            size: 10,
            weight: 600 as const,
          }
        },
        grid: {
          color: 'var(--border-color)' + '55'
        }
      },
      y: {
        display: true,
        ticks: {
          color: 'var(--text-secondary)',
          font: { size: 10, weight: 600 as const },
          maxTicksLimit: 6,
          callback: (value: any) => {
            const bytes = Number(value);
            if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
            if (bytes >= 1048576) return (bytes / 1048576).toFixed(0) + ' MB';
            return bytes + ' B';
          },
        },
        grid: { color: 'var(--border-color)' + '55' },
      }
    }
  };

  // Traffic Distribution Pie Chart
  const totalDownload = trafficData.reduce((sum, d) => sum + d.download, 0);
  const totalTraffic = trafficData.reduce((sum, d) => sum + d.total, 0);

  return (
    <div className="traffic-stats">
      <div className="card p-3 mb-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        {error && (
          <div className="alert alert-danger mb-3">
            {error}
          </div>
        )}

        <div className="panel-grid">
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('common.actions')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('traffic.refreshHint')}
                </p>
              </div>
            </div>
            <div className="panel-inline-actions">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                onClick={() => {
                  loadTrafficStats(groupBy, period);
                  loadOnlineClients();
                  loadOnlineTrafficTotals(period);
                }}
                disabled={loading}
              >
                {loading ? t('messages.loadingData') : t('common.refresh')}
              </button>
              <input
                type="text"
                className="form-control form-control-sm"
                placeholder={t('traffic.searchEmailOrNode')}
                value={trafficSearch}
                onChange={e => setTrafficSearch(e.target.value)}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)', width: '160px', fontSize: '0.75rem' }}
              />
              {trafficNodeNames.length > 1 && (
                <select
                  className="form-select form-select-sm"
                  value={filterNodeName}
                  onChange={e => setFilterNodeName(e.target.value)}
                  style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)', width: 'auto', fontSize: '0.75rem' }}
                >
                  <option value="">{t('clients.allNodes')}</option>
                  {trafficNodeNames.map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              )}
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                title={t('traffic.clearCacheTitle')}
                onClick={() => {
                  try { localStorage.removeItem(TRAFFIC_STATS_CACHE_KEY); } catch {}
                  setTrafficData([]);
                  loadTrafficStats(groupBy, period);
                  loadOnlineClients();
                }}
              >
                ✕ {t('traffic.clearCache')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                title={t('traffic.exportCsvTitle')}
                disabled={trafficData.length === 0}
                onClick={() => {
                  const rows = trafficData.map(d => [
                    d.email || d.node_name || '',
                    d.node_name || '',
                    d.protocol || '',
                    (d.upload / 1073741824).toFixed(3),
                    (d.download / 1073741824).toFixed(3),
                    (d.total / 1073741824).toFixed(3),
                  ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));
                  const csv = ['name,node,protocol,upload_gb,download_gb,total_gb', ...rows].join('\n');
                  const blob = new Blob([csv], { type: 'text/csv' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `traffic_${groupBy}_${period}_${new Date().toISOString().slice(0,10)}.csv`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                ⬇ {t('traffic.csv')}
              </button>
            </div>
          </div>
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('traffic.groupBy')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('traffic.groupHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              <ChoiceChips
                options={[
                  { value: 'client', label: t('traffic.byClient') },
                  { value: 'inbound', label: t('traffic.byInbound') },
                  { value: 'node', label: t('traffic.byNode') },
                ]}
                value={groupBy}
                onChange={(value) => {
                  const nextGroupBy = value as 'client' | 'inbound' | 'node';
                  setGroupBy(nextGroupBy);
                  loadTrafficStats(nextGroupBy, period);
                }}
                
              />
            </div>
          </div>
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('traffic.period')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('traffic.periodHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              <ChoiceChips
                options={[
                  { value: 'day', label: t('traffic.periodDay') },
                  { value: 'week', label: t('traffic.periodWeek') },
                  { value: 'month', label: t('traffic.periodMonth') },
                  { value: 'year', label: t('traffic.periodYear') },
                  { value: 'all_time', label: t('traffic.periodAllTime') },
                ]}
                value={period}
                onChange={(value) => {
                  const nextPeriod = value as 'day' | 'week' | 'month' | 'year' | 'all_time';
                  setPeriod(nextPeriod);
                  loadTrafficStats(groupBy, nextPeriod);
                  loadOnlineTrafficTotals(nextPeriod);
                }}
                
              />
              {periodNote && (
                <small style={{ color: 'var(--text-secondary)' }}>{periodNote}</small>
              )}
            </div>
          </div>
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('traffic.range')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('traffic.rangeHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              <ChoiceChips
                options={[
                  { value: 5, label: '5' },
                  { value: 10, label: '10' },
                  { value: 20, label: '20' },
                  { value: 50, label: '50' },
                ]}
                value={topN}
                onChange={(value) => setTopN(value)}
                
              />
              <small style={{ color: 'var(--text-secondary)' }}>
                {t('traffic.sortHint')}
              </small>
            </div>
          </div>
        </div>
      </div>

      {/* Stats Summary */}
      <div className="d-flex gap-3 mb-3 flex-wrap">
        <article className="app-shell-stat app-shell-stat--accent flex-fill">
          <span className="app-shell-stat__label">{t('traffic.download')}</span>
          <span className="app-shell-stat__value">{formatBytes(totalDownload)}</span>
        </article>
        <article className="app-shell-stat app-shell-stat--info flex-fill">
          <span className="app-shell-stat__label">{t('traffic.total')}</span>
          <span className="app-shell-stat__value">{formatBytes(totalTraffic)}</span>
        </article>
        <article className="app-shell-stat app-shell-stat--warning flex-fill">
          <span className="app-shell-stat__label">{t('traffic.onlineClients')}</span>
          <span className="app-shell-stat__value" style={{ color: 'var(--warning)' }}>{onlineClients.length}</span>
        </article>
      </div>

      {/* Charts */}
      <div className="row mb-3">
        <div className="col-12">
          <div className="card p-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
            <h6 className="mb-3" style={{ color: 'var(--text-primary)' }}>
              {t('traffic.topBy', { count: topN, entity: topByEntity })}
            </h6>
            <div style={{ height: '400px' }}>
              {loading ? (
                <div className="d-flex flex-column justify-content-center align-items-center h-100 gap-2">
                  <div className="spinner-border spinner-accent" style={{ width: '1.8rem', height: '1.8rem', borderWidth: '0.15em' }} />
                  <span style={{ color: 'var(--text-tertiary)', fontSize: '0.78rem' }}>{t('messages.loadingData')}</span>
                </div>
              ) : (
                <Bar data={topClientsData} options={chartOptions} />
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Online Clients */}
      <div className="card p-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        <div className="d-flex justify-content-between align-items-center mb-3 gap-2">
          <h6 className="mb-0" style={{ color: 'var(--text-primary)' }}>{t('traffic.onlineClients')} ({onlineClients.length})</h6>
          <div className="small" style={{ color: 'var(--text-secondary)' }}>
            {onlineLoading ? t('traffic.loadingOnline') : t('traffic.sortHint')}
          </div>
        </div>
        {onlineLoading && <div className="table-loading-bar mb-1" />}
        {onlineLoading && onlineClients.length === 0 ? (
          <div className="text-center py-4">
            <div className="spinner-border spinner-border-sm spinner-accent" style={{ width: '1.2rem', height: '1.2rem', borderWidth: '0.14em' }} />
          </div>
        ) : onlineClients.length === 0 ? (
          <div className="text-center py-4" style={{ color: 'var(--text-tertiary)', fontSize: '0.85rem' }}>
            {t('traffic.noClientsOnline')}
          </div>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-hover" style={{ color: 'var(--text-primary)' }}>
              <thead>
                <tr style={{ borderColor: 'var(--border-color)' }}>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyOnlineSortFromHeader('email')}>
                      Email{onlineSortIndicator('email')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyOnlineSortFromHeader('node')}>
                      {t('traffic.node')}{onlineSortIndicator('node')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyOnlineSortFromHeader('traffic')}>
                      {t('traffic.total')}{onlineSortIndicator('traffic')}
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedOnlineClients.map((client) => (
                  <tr key={`${client.node_name}:${client.email}`} style={{ borderColor: 'var(--border-color)' }}>
                    <td>
                      <span style={{ color: 'var(--success)' }}>● </span>
                      <strong style={{ color: 'var(--text-primary)' }}>{client.email}</strong>
                    </td>
                    <td>
                      <span className="badge" style={{ backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-primary)' }}>
                        {client.node_name}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>
                      {formatBytes(onlineTrafficTotals[normalizeEmailKey(client.email)] || 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Per-node traffic summary */}
      {groupBy === 'client' && trafficNodeNames.length > 1 && (
        <div className="card p-3 mt-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
          <div className="small mb-2" style={{ color: 'var(--text-secondary)' }}>{t('traffic.trafficByNode')}</div>
          <div className="d-flex flex-wrap gap-2">
            {trafficNodeNames.map(nodeName => {
              const nodeTotal = trafficData.filter(d => d.node_name === nodeName).reduce((s, d) => s + d.total, 0);
              const allTotal = trafficData.reduce((s, d) => s + d.total, 0);
              const pct = allTotal > 0 ? (nodeTotal / allTotal * 100).toFixed(0) : '0';
              return (
                <div key={nodeName} className="d-flex align-items-center gap-2">
                  <span
                    className="badge"
                    style={{ backgroundColor: filterNodeName === nodeName ? 'var(--warning)' : 'var(--bg-tertiary)', color: filterNodeName === nodeName ? '#000' : 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.72rem' }}
                    onClick={() => setFilterNodeName(prev => prev === nodeName ? '' : (nodeName ?? ''))}
                  >
                    {nodeName}
                  </span>
                  <span style={{ color: 'var(--text-primary)', fontSize: '0.78rem' }}>{formatBytes(nodeTotal)}</span>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>({pct}%)</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Top Traffic Table */}
      <div className="card p-3 mt-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        <h6 className="mb-3" style={{ color: 'var(--text-primary)' }}>
          {t('traffic.topUsage', { count: topN })}
        </h6>
        {loading ? (
          <div className="text-center py-3"><div className="spinner-border spinner-border-sm"></div></div>
        ) : sortedTraffic.length === 0 ? (
          <p className="text-center py-3" style={{ color: 'var(--text-secondary)' }}>{t('messages.noDataAvailable')}</p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-hover" style={{ color: 'var(--text-primary)' }}>
              <thead>
                <tr style={{ borderColor: 'var(--border-color)' }}>
                  <th style={{ color: 'var(--text-secondary)' }}>#</th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyTrafficSortFromHeader('name')}>
                      {groupBy === 'client' ? t('clients.email') : groupBy === 'inbound' ? t('nav.inbounds') : t('traffic.node')}{trafficSortIndicator('name')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyTrafficSortFromHeader('upload')}>
                      ↑{trafficSortIndicator('upload')}
                    </button>
                    {' / '}
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyTrafficSortFromHeader('download')}>
                      ↓{trafficSortIndicator('download')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyTrafficSortFromHeader('total')}>
                      {t('traffic.total')}{trafficSortIndicator('total')}
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedTraffic.map((item, idx) => (
                  <tr key={idx} style={{ borderColor: 'var(--border-color)' }}>
                    <td style={{ color: 'var(--text-secondary)' }}>{idx + 1}</td>
                    <td>
                      <strong
                        style={{ color: item.email && onNavigateToClient ? 'var(--accent)' : 'var(--text-primary)', cursor: item.email && onNavigateToClient ? 'pointer' : 'default' }}
                        title={item.email && onNavigateToClient ? `Filter clients by: ${item.email}` : undefined}
                        onClick={() => item.email && onNavigateToClient && onNavigateToClient(item.email)}
                      >
                        {item.email || item.node_name || t('traffic.unknown')}
                      </strong>
                      {item.node_name && groupBy === 'client' && (
                        <span
                          className="badge ms-1"
                          style={{ backgroundColor: filterNodeName === item.node_name ? 'var(--warning)' : 'var(--bg-tertiary)', color: filterNodeName === item.node_name ? '#000' : 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.65rem' }}
                          title={filterNodeName === item.node_name ? 'Click to clear node filter' : `Filter by ${item.node_name}`}
                          onClick={() => setFilterNodeName(prev => prev === item.node_name ? '' : (item.node_name || ''))}
                        >
                          {item.node_name}
                        </span>
                      )}
                      {item.protocol && (
                        <span className="badge ms-1" style={{ backgroundColor: 'var(--accent)', fontSize: '0.65rem' }}>
                          {item.protocol.toUpperCase()}
                        </span>
                      )}
                    </td>
                    <td style={{ color: 'var(--info)' }}><span style={{ fontSize: '0.8rem' }}>{formatBytes(item.upload)}</span></td>
                    <td style={{ color: 'var(--accent)' }}>{formatBytes(item.download)}</td>
                    <td>
                      <strong style={{ color: 'var(--info)' }}>{formatBytes(item.total)}</strong>
                      {filteredTrafficData.length > 0 && (() => {
                        const totalAll = filteredTrafficData.reduce((s, d) => s + d.total, 0);
                        const pct = totalAll > 0 ? (item.total / totalAll * 100).toFixed(1) : '0';
                        return <span className="ms-1 small" style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>{pct}%</span>;
                      })()}
                    </td>
                  </tr>
                ))}
              </tbody>
              {sortedTraffic.length > 0 && (() => {
                const totalUp = filteredTrafficData.reduce((s, d) => s + d.upload, 0);
                const totalDl = filteredTrafficData.reduce((s, d) => s + d.download, 0);
                const totalAll = filteredTrafficData.reduce((s, d) => s + d.total, 0);
                return (
                  <tfoot>
                    <tr style={{ borderTop: '2px solid var(--border-color)', fontWeight: 600 }}>
                      <td colSpan={2} style={{ color: 'var(--text-secondary)', paddingTop: '6px', fontSize: '0.8rem' }}>
                        Σ {filteredTrafficData.length} {(filterNodeName || trafficSearch) ? '(filtered)' : ''}
                      </td>
                      <td style={{ color: 'var(--info)', fontSize: '0.8rem', paddingTop: '6px' }}>{formatBytes(totalUp)}</td>
                      <td style={{ color: 'var(--warning)', fontSize: '0.8rem', paddingTop: '6px' }}>{formatBytes(totalDl)}</td>
                      <td style={{ color: 'var(--text-primary)', fontSize: '0.8rem', paddingTop: '6px' }}>{formatBytes(totalAll)}</td>
                    </tr>
                  </tfoot>
                );
              })()}
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
