import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { getClientPresence, type ClientPresenceProjection } from '../api/clients';
import { ChoiceChips } from './ChoiceChips';
import { mergeStaleCacheRecord, readStaleCache } from '../services/staleCache';
import { useTrafficStatsSubscription, TrafficUpdate } from '../services/useTrafficStatsSubscription';
import { UIIcon } from './UIIcon';
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

export interface OnlineClient {
  email: string;
  nodes: Array<{ node_id: string; node_name: string }>;
}

type TrafficStatsValue = {
  up?: number;
  down?: number;
  upload?: number;
  download?: number;
  bytes_sent?: number;
  bytes_recv?: number;
  sent?: number;
  recv?: number;
  traffic_up_bytes?: number;
  traffic_down_bytes?: number;
  total?: number;
  traffic_total_bytes?: number;
};

type TrafficSummary = {
  upload: number;
  download: number;
  total: number;
  count: number;
};

const normalizeEmailKey = (email: string): string => email.trim().toLowerCase();
const TRAFFIC_STATS_CACHE_KEY = 'sub_manager_traffic_stats_cache_v3';
const TRAFFIC_STATS_CACHE_MAX_AGE_MS = 10 * 60 * 1000;
const REALTIME_TRAFFIC_REFRESH_MIN_INTERVAL_MS = 60 * 1000;

type TrafficGroupBy = 'client' | 'inbound' | 'node';
type TrafficPeriod = 'day' | 'week' | 'month' | 'year' | 'all_time';
type TrafficLoadReason = 'bootstrap' | 'manual' | 'group' | 'period';

type TrafficStatsCache = {
  onlineClients?: OnlineClient[];
  trafficData?: TrafficData[];
  onlineTrafficTotals?: Record<string, number>;
  trafficSelections?: Record<string, {
    trafficData: TrafficData[];
    periodNote?: string;
    trafficSummary?: TrafficSummary;
  }>;
  groupBy?: TrafficGroupBy;
  period?: TrafficPeriod;
  periodNote?: string;
};

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');
const toFiniteNumber = (value: unknown): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const normalizeTrafficValue = (raw: TrafficStatsValue) => {
  const upload = toFiniteNumber(raw.up ?? raw.upload ?? raw.bytes_sent ?? raw.sent ?? raw.traffic_up_bytes);
  const download = toFiniteNumber(raw.down ?? raw.download ?? raw.bytes_recv ?? raw.recv ?? raw.traffic_down_bytes);
  const total = toFiniteNumber(raw.total ?? raw.traffic_total_bytes);
  return {
    upload,
    download,
    total: total > 0 ? total : upload + download,
  };
};

const normalizeTrafficSummary = (raw: unknown): TrafficSummary | undefined => {
  if (!raw || typeof raw !== 'object') return undefined;
  const value = raw as Record<string, unknown>;
  return {
    upload: toFiniteNumber(value.upload),
    download: toFiniteNumber(value.download),
    total: toFiniteNumber(value.total),
    count: toFiniteNumber(value.count),
  };
};

export const formatOnlineTrafficTotal = (totals: Record<string, number>, email: string, format: (bytes: number) => string): string => {
  const key = normalizeEmailKey(email);
  return Object.prototype.hasOwnProperty.call(totals, key) ? format(totals[key]) : '—';
};

const trafficSelectionCacheKey = (groupBy: TrafficGroupBy, period: TrafficPeriod) => `${groupBy}:${period}`;

export const groupOnlinePresence = (projection: ClientPresenceProjection): OnlineClient[] => {
  const grouped = new Map<string, OnlineClient>();
  const nodeNames = projection.node_names || {};
  Object.entries(projection.online_by_node || {}).forEach(([nodeId, emails]) => {
    if (!Array.isArray(emails)) return;
    const nodeName = String(nodeNames[nodeId] || nodeId);
    emails.forEach((email) => {
      if (typeof email !== 'string' || !normalizeEmailKey(email)) return;
      const normalizedEmail = normalizeEmailKey(email);
      const current = grouped.get(normalizedEmail) || { email: normalizedEmail, nodes: [] };
      if (!current.nodes.some((node) => node.node_id === nodeId)) {
        current.nodes.push({ node_id: nodeId, node_name: nodeName });
      }
      grouped.set(normalizedEmail, current);
    });
  });
  return Array.from(grouped.values())
    .map((client) => ({ ...client, nodes: [...client.nodes].sort((a, b) => a.node_name.localeCompare(b.node_name, undefined, { sensitivity: 'base', numeric: true })) }))
    .sort((a, b) => a.email.localeCompare(b.email, undefined, { sensitivity: 'base', numeric: true }));
};

export const TrafficStats: React.FC<{ onNavigateToClient?: (email: string) => void }> = ({ onNavigateToClient }) => {
  const { t } = useTranslation();
  const { stylePreset } = useTheme();
  const [trafficData, setTrafficData] = useState<TrafficData[]>([]);
  const [onlineClients, setOnlineClients] = useState<OnlineClient[]>([]);
  const [onlineTrafficTotals, setOnlineTrafficTotals] = useState<Record<string, number>>({});
  const [trafficSummary, setTrafficSummary] = useState<TrafficSummary | undefined>();
  const [periodNote, setPeriodNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadReason, setLoadReason] = useState<TrafficLoadReason | null>(null);
  const [onlineLoading, setOnlineLoading] = useState(false);
  const [error, setError] = useState('');
  const [groupBy, setGroupBy] = useState<TrafficGroupBy>('client');
  const [period, setPeriod] = useState<TrafficPeriod>('all_time');
  const [topN, setTopN] = useState(10);
  const [filterNodeName, setFilterNodeName] = useState('');
  const [trafficSearch, setTrafficSearch] = useState('');
  const [trafficSortField, setTrafficSortField] = useState<'name' | 'download' | 'upload' | 'total'>('download');
  const [trafficSortDir, setTrafficSortDir] = useState<'asc' | 'desc'>('desc');
  const [onlineSortField, setOnlineSortField] = useState<'email' | 'node' | 'traffic'>('email');
  const [onlineSortDir, setOnlineSortDir] = useState<'asc' | 'desc'>('asc');
  const [onlineDetailsRequested, setOnlineDetailsRequested] = useState(false);
  const trafficRequestRef = useRef(0);
  const trafficAbortRef = useRef<AbortController | null>(null);
  const onlineAbortRef = useRef<AbortController | null>(null);
  const onlineTotalsAbortRef = useRef<AbortController | null>(null);
  const realtimeTrafficRefreshTimerRef = useRef<number | null>(null);
  const lastRealtimeTrafficRefreshRef = useRef(0);
  const chartAccent = stylePreset === '3' ? '#e2e8f0' : '#22d3ee';
  const readCachedTrafficSelection = (nextGroupBy: TrafficGroupBy, nextPeriod: TrafficPeriod) => {
    const cached = readStaleCache<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, TRAFFIC_STATS_CACHE_MAX_AGE_MS).data;
    if (!cached) return undefined;
    const selection = cached.trafficSelections?.[trafficSelectionCacheKey(nextGroupBy, nextPeriod)];
    if (selection) return selection;
    // One release of the panel stored only the active selection.  Read it
    // once for a seamless upgrade, then write the multi-period form below.
    if (cached.groupBy === nextGroupBy && cached.period === nextPeriod && Array.isArray(cached.trafficData)) {
      return { trafficData: cached.trafficData, periodNote: cached.periodNote };
    }
    return undefined;
  };

  const persistTrafficSelection = (
    nextGroupBy: TrafficGroupBy,
    nextPeriod: TrafficPeriod,
    nextTrafficData: TrafficData[],
    nextPeriodNote: string,
    nextTrafficSummary?: TrafficSummary,
  ) => {
    const cached = readStaleCache<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, Number.MAX_SAFE_INTEGER).data;
    mergeStaleCacheRecord<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, {
      trafficData: nextTrafficData,
      groupBy: nextGroupBy,
      period: nextPeriod,
      periodNote: nextPeriodNote,
      trafficSelections: {
        ...(cached?.trafficSelections ?? {}),
        [trafficSelectionCacheKey(nextGroupBy, nextPeriod)]: {
          trafficData: nextTrafficData,
          periodNote: nextPeriodNote,
          trafficSummary: nextTrafficSummary,
        },
      },
    });
  };

  useEffect(() => {
    const cached = readStaleCache<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, TRAFFIC_STATS_CACHE_MAX_AGE_MS);
    if (cached.data) {
      if (Array.isArray(cached.data.onlineClients)) setOnlineClients(cached.data.onlineClients);
      const selection = cached.data.trafficSelections?.[trafficSelectionCacheKey(groupBy, period)]
        ?? (cached.data.groupBy === groupBy && cached.data.period === period && Array.isArray(cached.data.trafficData)
          ? { trafficData: cached.data.trafficData, periodNote: cached.data.periodNote }
          : undefined);
      if (selection) {
        setTrafficData(selection.trafficData);
        setPeriodNote(selection.periodNote || '');
        setTrafficSummary(selection.trafficSummary);
      }
      if (cached.data.onlineTrafficTotals) setOnlineTrafficTotals(cached.data.onlineTrafficTotals);
    }

    // Let the controls and any stale projection render before starting the
    // remote-backed period query.  Full online details remain opt-in.
    const bootstrapTimer = window.setTimeout(() => {
      loadTrafficStats(groupBy, period, { reason: 'bootstrap' });
    }, cached.isFresh ? 2_000 : 750);
    return () => window.clearTimeout(bootstrapTimer);
  }, []);

  useEffect(() => () => {
    trafficAbortRef.current?.abort();
    onlineAbortRef.current?.abort();
    onlineTotalsAbortRef.current?.abort();
    if (realtimeTrafficRefreshTimerRef.current !== null) {
      window.clearTimeout(realtimeTrafficRefreshTimerRef.current);
    }
  }, []);

  const loadTrafficStats = async (
    nextGroupBy: TrafficGroupBy = groupBy,
    nextPeriod: TrafficPeriod = period,
    options?: { silent?: boolean; reason?: TrafficLoadReason },
  ) => {
    const requestId = ++trafficRequestRef.current;
    const limit = Math.max(topN * 12, 240);
    trafficAbortRef.current?.abort();
    const controller = new AbortController();
    trafficAbortRef.current = controller;
    const cachedSelection = readCachedTrafficSelection(nextGroupBy, nextPeriod);
    if (cachedSelection) {
      setTrafficData(cachedSelection.trafficData);
      setPeriodNote(cachedSelection.periodNote || '');
    }

    if (!options?.silent) {
      setLoading(true);
      setLoadReason(options?.reason ?? 'manual');
    }
    setError('');
    if (!cachedSelection) setPeriodNote('');

    try {
      const res = await api.get('/v1/traffic/stats-by-period', {
        auth: getAuth(),
        params: { group_by: nextGroupBy, period: nextPeriod, limit },
        signal: controller.signal,
      });
      const statsObj: Record<string, TrafficStatsValue> = res.data?.stats || {};
      const parsed: TrafficData[] = Object.entries(statsObj).map(([key, s]) => {
        const traffic = normalizeTrafficValue(s);
        if (nextGroupBy === 'node') {
          return {
            email: key,
            node_name: key,
            ...traffic,
          };
        }
        if (nextGroupBy === 'inbound') {
          const sep = key.indexOf(':');
          const nodeName = sep >= 0 ? key.slice(0, sep) : '';
          const inboundName = sep >= 0 ? key.slice(sep + 1) : key;
          return {
            email: inboundName || key,
            node_name: nodeName || undefined,
            ...traffic,
          };
        }
        return {
          email: key,
          ...traffic,
        };
      });

      if (requestId !== trafficRequestRef.current) return;
      const summary = normalizeTrafficSummary(res.data?.summary);
      setTrafficData(parsed);
      setPeriodNote(res.data?.note || '');
      setTrafficSummary(summary);
      persistTrafficSelection(nextGroupBy, nextPeriod, parsed, res.data?.note || '', summary);
    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') return;
      if (requestId !== trafficRequestRef.current) return;
      setError(err.response?.data?.detail || t('traffic.loadFailed'));
    } finally {
      if (requestId === trafficRequestRef.current && !options?.silent) {
        setLoading(false);
        setLoadReason(null);
      }
    }
  };

  const loadOnlineClients = async (silent = false) => {
    onlineAbortRef.current?.abort();
    const controller = new AbortController();
    onlineAbortRef.current = controller;
    if (!silent) setOnlineLoading(true);
    try {
      const items = groupOnlinePresence(await getClientPresence(controller.signal));
      setOnlineClients(items);
      mergeStaleCacheRecord<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, {
        onlineClients: items,
      });
      return items;
    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') return;
      console.error('Failed to load online clients:', err);
    } finally {
      if (!silent) setOnlineLoading(false);
    }
  };

  const loadOnlineTrafficTotals = async (
    nextPeriod: TrafficPeriod = period,
    clients: OnlineClient[] = onlineClients,
  ) => {
    const emails = clients.map((client) => normalizeEmailKey(client.email)).filter(Boolean);
    if (emails.length === 0) {
      setOnlineTrafficTotals({});
      return;
    }
    onlineTotalsAbortRef.current?.abort();
    const controller = new AbortController();
    onlineTotalsAbortRef.current = controller;
    try {
      const res = await api.post('/v1/traffic/client-totals', {
        emails,
        period: nextPeriod,
      }, {
        auth: getAuth(),
        signal: controller.signal,
        skipCacheInvalidation: true,
      });
      const totals: Record<string, number> = Object.fromEntries(
        Object.entries(res.data?.totals || {}).map(([email, total]) => [normalizeEmailKey(email), toFiniteNumber(total)]),
      );
      setOnlineTrafficTotals(totals);
      mergeStaleCacheRecord<TrafficStatsCache>(TRAFFIC_STATS_CACHE_KEY, { onlineTrafficTotals: totals });
    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') return;
      console.error('Failed to load online traffic totals:', err);
    }
  };

  const refreshOnlineDetails = async (silent = false) => {
    const clients = await loadOnlineClients(silent);
    if (clients) await loadOnlineTrafficTotals(period, clients);
  };

  const scheduleRealtimeTrafficRefresh = useCallback(() => {
    const refresh = () => {
      realtimeTrafficRefreshTimerRef.current = null;
      lastRealtimeTrafficRefreshRef.current = Date.now();
      loadTrafficStats(groupBy, period, { silent: true });
    };

    const remaining = REALTIME_TRAFFIC_REFRESH_MIN_INTERVAL_MS - (Date.now() - lastRealtimeTrafficRefreshRef.current);
    if (remaining <= 0) {
      refresh();
      return;
    }

    if (realtimeTrafficRefreshTimerRef.current === null) {
      realtimeTrafficRefreshTimerRef.current = window.setTimeout(refresh, remaining);
    }
  }, [groupBy, period]);

  useEffect(() => {
    if (realtimeTrafficRefreshTimerRef.current !== null) {
      window.clearTimeout(realtimeTrafficRefreshTimerRef.current);
      realtimeTrafficRefreshTimerRef.current = null;
    }
  }, [groupBy, period]);

  const handleRealtimeUpdate = useCallback(
    (update: TrafficUpdate) => {
      if (update.data?.source === 'snapshot_collector') {
        if (update.type !== 'client_update') {
          return;
        }
        scheduleRealtimeTrafficRefresh();
        if (onlineDetailsRequested) {
          void refreshOnlineDetails(true);
        }
        return;
      }
      if (update.type === 'traffic_update') {
        scheduleRealtimeTrafficRefresh();
        if (onlineDetailsRequested) loadOnlineTrafficTotals(period);
        return;
      }
      if (update.type === 'client_update') {
        if (onlineDetailsRequested) void refreshOnlineDetails(true);
        return;
      }
      if (update.type === 'server_status') {
        scheduleRealtimeTrafficRefresh();
      }
    },
    [onlineDetailsRequested, period, scheduleRealtimeTrafficRefresh],
  );

  useTrafficStatsSubscription({
    channels: ['traffic', 'clients', 'server_status'],
    onUpdate: handleRealtimeUpdate,
    onError: (err) => console.warn('[TrafficStats] realtime error:', err),
    fallbackPollIntervalMs: 60_000,
    fallbackRun: () => {
      scheduleRealtimeTrafficRefresh();
      if (onlineDetailsRequested) {
        void refreshOnlineDetails(true);
      }
    },
  });

  const loadOnlineDetails = async () => {
    setOnlineDetailsRequested(true);
    await refreshOnlineDetails();
  };

  const formatBytes = (bytes: number) => {
    const value = Math.max(0, Number(bytes) || 0);
    if (value === 0) return '0 GB';
    const tb = value / 1099511627776;
    if (tb >= 1) return `${tb.toFixed(2)} TB`;
    return `${(value / 1073741824).toFixed(2)} GB`;
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
    ? onlineClients.filter(c => c.email.toLowerCase().includes(trafficSearch.trim().toLowerCase()) || c.nodes.some((node) => node.node_name.toLowerCase().includes(trafficSearch.trim().toLowerCase())))
    : onlineClients;

  const onlineNodeLabel = (client: OnlineClient) => client.nodes.map((node) => node.node_name).join(', ');

  const sortedOnlineClients = [...filteredOnlineClients].sort((a, b) => {
    const aTraffic = onlineTrafficTotals[normalizeEmailKey(a.email)] ?? -1;
    const bTraffic = onlineTrafficTotals[normalizeEmailKey(b.email)] ?? -1;
    const byEmail = compareText(a.email, b.email);
    const byNode = compareText(onlineNodeLabel(a), onlineNodeLabel(b));
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
    trafficSortField === field ? (trafficSortDir === 'asc' ? ' â–²' : ' â–¼') : '';

  const onlineSortIndicator = (field: 'email' | 'node' | 'traffic') =>
    onlineSortField === field ? (onlineSortDir === 'asc' ? ' â–²' : ' â–¼') : '';

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
        label: t('traffic.download'),
        data: sortedTraffic.map(d => d.download),
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
          color: '#e2e8f0',
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
        backgroundColor: '#0f1420',
        borderColor: 'rgba(30, 41, 59, 0.6)',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#cbd5e1',
        displayColors: false,
        padding: 10,
        cornerRadius: 10,
        callbacks: {
          label: (context: any) => {
            const datasetLabel = context?.dataset?.label || '';
            return `${datasetLabel}: ${formatBytes(Number(context?.parsed?.y || 0))}`;
          },
        },
      },
    },
    interaction: {
      intersect: false,
      mode: 'index' as const,
    },
    scales: {
      x: {
        ticks: {
          color: '#94a3b8',
          font: {
            size: 10,
            weight: 600 as const,
          }
        },
        grid: {
          color: 'rgba(30, 41, 59, 0.6)'
        }
      },
      y: {
        display: true,
        ticks: {
          color: '#94a3b8',
          font: { size: 10, weight: 600 as const },
          maxTicksLimit: 6,
          callback: (value: any) => {
            const bytes = Number(value);
            if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
            if (bytes >= 1048576) return (bytes / 1048576).toFixed(0) + ' MB';
            return bytes + ' B';
          },
        },
        grid: { color: 'rgba(30, 41, 59, 0.6)' },
      }
    }
  };


  // Traffic Distribution Pie Chart
  const totalUpload = trafficData.reduce((sum, d) => sum + d.upload, 0);
  const totalDownload = trafficData.reduce((sum, d) => sum + d.download, 0);
  const totalTraffic = trafficData.reduce((sum, d) => sum + d.total, 0);
  const summaryUpload = trafficSummary?.upload ?? totalUpload;
  const summaryDownload = trafficSummary?.download ?? totalDownload;
  const summaryTraffic = trafficSummary?.total ?? totalTraffic;
  const isTrafficTruncated = (trafficSummary?.count ?? trafficData.length) > trafficData.length;
  const filteredTotalUpload = filteredTrafficData.reduce((sum, d) => sum + d.upload, 0);
  const filteredTotalDownload = filteredTrafficData.reduce((sum, d) => sum + d.download, 0);
  const filteredTotalTraffic = filteredTrafficData.reduce((sum, d) => sum + d.total, 0);

  const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(103,232,249,0.05)]';
  const titleClass = 'text-xs font-medium uppercase tracking-[0.14em] text-slate-300';
  const hintClass = 'mt-1 text-xs font-light leading-5 text-slate-500';
  const metricClass = 'min-w-[5.5rem] whitespace-nowrap font-mono tabular-nums';
  const valueClass = `block ${metricClass} text-sm`;
  const controlButtonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs font-medium tracking-wide text-slate-300 transition hover:border-cyan-300/40 hover:bg-[#0f1420] hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50';
  const accentButtonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-300/25 bg-cyan-300 px-3 text-xs font-medium tracking-wide text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-60';
  const inputClass = 'h-9 min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs font-light text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10';
  const headerButtonClass = 'inline-flex whitespace-nowrap text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500 hover:text-cyan-300';

  const summaryMetrics = [
    { label: t('traffic.upload'), value: formatBytes(summaryUpload), color: 'text-cyan-300', bar: 'from-cyan-400 to-sky-400' },
    { label: t('traffic.download'), value: formatBytes(summaryDownload), color: 'text-emerald-300', bar: 'from-emerald-400 to-teal-300' },
    { label: t('traffic.total'), value: formatBytes(summaryTraffic), color: 'text-indigo-200', bar: 'from-indigo-400 to-cyan-300' },
  ];

  const isColdLoading = loading && trafficData.length === 0;
  const isPeriodSwitchLoading = loading && loadReason === 'period';
  const isGroupSwitchLoading = loading && loadReason === 'group';
  const renderChartSkeleton = () => (
    <div className="relative h-full min-w-0 overflow-hidden rounded-lg bg-[#0a0e1a] p-4">
      <div className="absolute inset-x-4 top-10 h-px bg-cyan-500/10" />
      <div className="absolute inset-x-4 top-1/3 h-px bg-cyan-500/10" />
      <div className="absolute inset-x-4 top-2/3 h-px bg-cyan-500/10" />
      <div className="absolute inset-x-4 bottom-10 h-px bg-cyan-500/10" />
      <div className="flex h-full items-end gap-3 pt-10">
        {[44, 72, 58, 86, 34, 64, 76, 48].map((height, idx) => (
          <div key={idx} className="flex min-w-0 flex-1 items-end">
            <div
              className="w-full animate-pulse rounded-t-md bg-cyan-300/20"
              style={{ height: `${height}%`, animationDelay: `${idx * 90}ms` }}
            />
          </div>
        ))}
      </div>
    </div>
  );

  const renderNodeChips = (item: TrafficData) => (
    <div className="mt-2 flex min-w-0 flex-wrap gap-1">
      {item.node_name && groupBy === 'client' && (
        <button
          type="button"
          className={cn('max-w-full rounded-md px-2 py-1 text-[11px] font-medium', filterNodeName === item.node_name ? 'bg-amber-300 text-slate-950' : 'bg-[#0f1420] text-slate-400 hover:text-cyan-200')}
          title={filterNodeName === item.node_name ? 'Click to clear node filter' : `Filter by ${item.node_name}`}
          onClick={() => setFilterNodeName(prev => prev === item.node_name ? '' : (item.node_name || ''))}
        >
          <span className="truncate">{item.node_name}</span>
        </button>
      )}
      {item.protocol && <span className="rounded-md bg-cyan-300 px-2 py-1 text-[11px] font-medium text-slate-950">{item.protocol.toUpperCase()}</span>}
    </div>
  );

  return (
    <div className="min-h-screen min-w-0 overflow-hidden bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6">
      <div className="min-w-0 space-y-4 overflow-hidden">
        {error && <div className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div>}

        <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
          {summaryMetrics.map(metric => (
            <article key={metric.label} className={panelClass}>
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">{metric.label}</div>
                  {isColdLoading ? (
                    <div className="mt-4 h-7 w-28 animate-pulse rounded-md bg-cyan-300/10" />
                  ) : (
                    <div className={cn('mt-4 text-2xl font-medium leading-none', metricClass, metric.color)}>{metric.value}</div>
                  )}
                </div>
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[#0a0e1a] text-cyan-300"><UIIcon name="traffic" size={16} /></div>
              </div>
              <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-[#0a0e1a]"><div className={cn('h-full rounded-full bg-gradient-to-r', metric.bar)} style={{ width: '100%' }} /></div>
            </article>
          ))}
        </section>

        <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
          <div className={panelClass}>
            <h6 className={titleClass}>{t('common.actions')}</h6>
            <p className={hintClass}>{t('traffic.refreshHint')}</p>
            <div className="mt-4 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
              <button type="button" className={accentButtonClass} disabled={loading} onClick={() => { loadTrafficStats(groupBy, period, { reason: 'manual' }); if (onlineDetailsRequested) loadOnlineDetails(); }}>
                <UIIcon name={loading ? 'spinner' : 'refresh'} size={14} className={loading ? 'animate-spin' : undefined} />
                <span className="whitespace-nowrap">{loading ? t('messages.loadingData') : t('common.refresh')}</span>
              </button>
              <button type="button" className={controlButtonClass} title={t('traffic.clearCacheTitle')} onClick={() => { try { sessionStorage.removeItem(TRAFFIC_STATS_CACHE_KEY); } catch {} setTrafficData([]); setOnlineTrafficTotals({}); loadTrafficStats(groupBy, period, { reason: 'manual' }); if (onlineDetailsRequested) loadOnlineDetails(); }}><UIIcon name="clear" size={14} /><span className="whitespace-nowrap">{t('traffic.clearCache')}</span></button>
              <button type="button" className={controlButtonClass} title={isTrafficTruncated ? t('traffic.exportCsvTopNTitle', { shown: trafficData.length, total: trafficSummary?.count ?? trafficData.length }) : t('traffic.exportCsvTitle')} disabled={trafficData.length === 0} onClick={() => { const rows = trafficData.map(d => [d.email || d.node_name || '', d.node_name || '', d.protocol || '', (d.upload / 1073741824).toFixed(3), (d.download / 1073741824).toFixed(3), (d.total / 1073741824).toFixed(3)].map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')); const csv = ['name,node,protocol,upload_gb,download_gb,total_gb', ...rows].join('\n'); const blob = new Blob([csv], { type: 'text/csv' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${isTrafficTruncated ? `traffic_top_${trafficData.length}_of_${trafficSummary?.count}_` : 'traffic_'}${groupBy}_${period}_${new Date().toISOString().slice(0,10)}.csv`; a.click(); URL.revokeObjectURL(url); }}><UIIcon name="download" size={14} /><span className="whitespace-nowrap">{t('traffic.csv')}</span></button>
              <div className="flex h-9 min-w-0 items-center rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs text-slate-500"><span className="mr-2 h-2 w-2 rounded-full bg-emerald-300" /><span className="truncate">{t('traffic.onlineClients')}</span><span className="ml-2 min-w-[2.5rem] whitespace-nowrap text-right font-mono text-slate-200">{onlineClients.length}</span></div>
            </div>
            <div className="mt-3 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
              <input type="text" className={inputClass} placeholder={t('traffic.searchEmailOrNode')} value={trafficSearch} onChange={e => setTrafficSearch(e.target.value)} />
              {trafficNodeNames.length > 1 && <select className={cn(inputClass, 'w-full sm:w-44')} value={filterNodeName} onChange={e => setFilterNodeName(e.target.value)}><option value="">{t('clients.allNodes')}</option>{trafficNodeNames.map(n => <option key={n} value={n}>{n}</option>)}</select>}
            </div>
          </div>

          <div className={panelClass}>
            <h6 className={titleClass}>{t('traffic.groupBy')}</h6>
            <p className={hintClass}>{t('traffic.groupHint')}</p>
            <div className="mt-4 min-w-0">
              <ChoiceChips options={[{ value: 'client', label: t('traffic.byClient') }, { value: 'inbound', label: t('traffic.byInbound') }, { value: 'node', label: t('traffic.byNode') }]} value={groupBy} disabled={loading && loadReason === 'manual'} onChange={(value) => { const nextGroupBy = value as TrafficGroupBy; setGroupBy(nextGroupBy); loadTrafficStats(nextGroupBy, period, { reason: 'group' }); }} />
              {isGroupSwitchLoading && <div className="mt-3 h-1 overflow-hidden rounded-full bg-[#0a0e1a]"><div className="h-full w-1/2 animate-pulse rounded-full bg-cyan-300" /></div>}
            </div>
          </div>

          <div className={panelClass}>
            <h6 className={titleClass}>{t('traffic.period')}</h6>
            <p className={hintClass}>{t('traffic.periodHint')}</p>
            <div className="mt-4 min-w-0">
              <ChoiceChips options={[{ value: 'day', label: t('traffic.periodDay') }, { value: 'week', label: t('traffic.periodWeek') }, { value: 'month', label: t('traffic.periodMonth') }, { value: 'year', label: t('traffic.periodYear') }, { value: 'all_time', label: t('traffic.periodAllTime') }]} value={period} disabled={loading && loadReason === 'manual'} onChange={(value) => { const nextPeriod = value as TrafficPeriod; setPeriod(nextPeriod); loadTrafficStats(groupBy, nextPeriod, { reason: 'period' }); if (onlineDetailsRequested) loadOnlineTrafficTotals(nextPeriod); }} />
              {isPeriodSwitchLoading && (
                <div className="mt-3 space-y-2">
                  <div className="h-1 overflow-hidden rounded-full bg-[#0a0e1a]"><div className="h-full w-1/2 animate-pulse rounded-full bg-cyan-300" /></div>
                  <div className="text-xs text-cyan-200/80">{t('messages.loadingData')}</div>
                </div>
              )}
              {periodNote && <div className="mt-3 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-xs text-slate-500">{periodNote}</div>}
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
          <div className={panelClass}>
            <h6 className={titleClass}>{t('traffic.range')}</h6>
            <p className={hintClass}>{t('traffic.rangeHint')}</p>
            <div className="mt-4 min-w-0"><ChoiceChips options={[{ value: 5, label: '5' }, { value: 10, label: '10' }, { value: 20, label: '20' }, { value: 50, label: '50' }]} value={topN} onChange={(value) => setTopN(value)} /><div className="mt-3 text-xs text-slate-500">{t('traffic.sortHint')}</div></div>
          </div>
          <div className={cn(panelClass, 'lg:col-span-2')}>
            <div className="mb-4 flex min-w-0 items-center justify-between gap-3"><h6 className={titleClass}>{t('traffic.topBy', { count: topN, entity: topByEntity })}</h6><span className={cn(metricClass, 'text-right text-xs text-slate-500')}>{formatBytes(totalTraffic)}</span></div>
            <div className="h-[320px] min-w-0 lg:h-[400px]">{isColdLoading ? renderChartSkeleton() : <Bar data={topClientsData} options={chartOptions} />}</div>
          </div>
        </section>

        <section className={panelClass}>
          <div className="mb-4 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><h6 className={titleClass}>{t('traffic.onlineClients')} ({onlineClients.length})</h6><div className="flex items-center gap-2"><div className="text-xs text-slate-500">{onlineLoading ? t('traffic.loadingOnline') : t('traffic.sortHint')}</div>{!onlineDetailsRequested && <button type="button" className={controlButtonClass} onClick={loadOnlineDetails}>{t('common.refresh')}</button>}</div></div>
          {onlineLoading && <div className="mb-4 h-1 overflow-hidden rounded-full bg-[#0a0e1a]"><div className="h-full w-1/2 animate-pulse rounded-full bg-cyan-300" /></div>}
          {onlineLoading && onlineClients.length === 0 ? <div className="grid gap-2 py-2">{Array.from({ length: 4 }).map((_, idx) => <div key={idx} className="h-12 animate-pulse rounded-lg border border-cyan-500/10 bg-[#0a0e1a]" style={{ animationDelay: `${idx * 90}ms` }} />)}</div> : onlineClients.length === 0 ? <div className="flex justify-center py-10 text-sm text-slate-500">{t('traffic.noClientsOnline')}</div> : <>
            <div className="hidden min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 lg:block"><table className="w-full table-fixed border-collapse text-sm"><thead><tr className="border-b border-cyan-500/20 bg-cyan-500/5"><th className="px-4 py-3 text-left"><button type="button" className={headerButtonClass} onClick={() => applyOnlineSortFromHeader('email')}>Email{onlineSortIndicator('email')}</button></th><th className="w-48 px-4 py-3 text-left"><button type="button" className={headerButtonClass} onClick={() => applyOnlineSortFromHeader('node')}>{t('traffic.node')}{onlineSortIndicator('node')}</button></th><th className="w-40 px-4 py-3 text-right"><button type="button" className={cn(headerButtonClass, 'justify-end')} onClick={() => applyOnlineSortFromHeader('traffic')}>{t('traffic.total')}{onlineSortIndicator('traffic')}</button></th></tr></thead><tbody>{sortedOnlineClients.map(client => <tr key={client.email} className="border-b border-cyan-500/10 hover:bg-cyan-400/5"><td className="min-w-0 px-4 py-3"><div className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full bg-emerald-300" /><strong className="truncate text-slate-100" title={client.email}>{client.email}</strong></div></td><td className="px-4 py-3"><span className="inline-flex max-w-full rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-2 py-1 text-xs font-medium text-slate-300"><span className="truncate" title={onlineNodeLabel(client)}>{onlineNodeLabel(client)}</span></span></td><td className="px-4 py-3 text-right"><span className={cn(valueClass, 'ml-auto text-slate-300')}>{formatOnlineTrafficTotal(onlineTrafficTotals, client.email, formatBytes)}</span></td></tr>)}</tbody></table></div>
            <div className="grid min-w-0 grid-cols-1 gap-2 lg:hidden">{sortedOnlineClients.map(client => <article key={client.email} className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-3"><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0"><div className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full bg-emerald-300" /><strong className="truncate text-sm text-slate-100" title={client.email}>{client.email}</strong></div><div className="mt-2 inline-flex max-w-full rounded-md border border-cyan-500/20 px-2 py-1 text-xs text-slate-400"><span className="truncate" title={onlineNodeLabel(client)}>{onlineNodeLabel(client)}</span></div></div><span className={cn(valueClass, 'text-right text-cyan-200')}>{formatOnlineTrafficTotal(onlineTrafficTotals, client.email, formatBytes)}</span></div></article>)}</div>
          </>}
        </section>

        {groupBy === 'client' && trafficNodeNames.length > 1 && <section className={panelClass}><h6 className={titleClass}>{t('traffic.trafficByNode')}</h6><div className="mt-4 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">{trafficNodeNames.map(nodeName => { const nodeTotal = trafficData.filter(d => d.node_name === nodeName).reduce((s, d) => s + d.total, 0); const pct = totalTraffic > 0 ? (nodeTotal / totalTraffic * 100).toFixed(0) : '0'; return <button key={nodeName} type="button" className={cn('min-w-0 rounded-lg border px-3 py-3 text-left transition', filterNodeName === nodeName ? 'border-amber-300/50 bg-amber-300/10 text-amber-200' : 'border-cyan-500/20 bg-[#0a0e1a] text-slate-300 hover:border-cyan-300/40')} onClick={() => setFilterNodeName(prev => prev === nodeName ? '' : (nodeName ?? ''))}><div className="truncate text-xs font-medium uppercase tracking-[0.14em]">{nodeName}</div><div className="mt-2 flex min-w-0 items-center justify-between gap-3"><span className={cn(valueClass, 'text-slate-100')}>{formatBytes(nodeTotal)}</span><span className="whitespace-nowrap font-mono text-xs text-slate-500">{pct}%</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#0a0e1a]"><div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-emerald-300" style={{ width: `${pct}%` }} /></div></button>; })}</div></section>}

        <section className={panelClass}>
          <div className="mb-4 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><h6 className={titleClass}>{t('traffic.topUsage', { count: topN })}</h6><span className="whitespace-nowrap font-mono text-xs text-slate-500">{isTrafficTruncated ? t('traffic.rowsShown', { shown: filteredTrafficData.length, total: trafficSummary?.count ?? trafficData.length }) : t('traffic.rows', { count: filteredTrafficData.length })}</span></div>
          {isColdLoading ? <div className="grid gap-2 py-2">{Array.from({ length: 5 }).map((_, idx) => <div key={idx} className="h-14 animate-pulse rounded-lg border border-cyan-500/10 bg-[#0a0e1a]" style={{ animationDelay: `${idx * 80}ms` }} />)}</div> : sortedTraffic.length === 0 ? <p className="flex justify-center py-10 text-sm text-slate-500">{t('messages.noDataAvailable')}</p> : <>
            <div className="hidden min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 lg:block"><table className="w-full table-fixed border-collapse text-sm"><thead><tr className="border-b border-cyan-500/20 bg-cyan-500/5"><th className="w-14 px-4 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-slate-500">#</th><th className="px-4 py-3 text-left"><button type="button" className={headerButtonClass} onClick={() => applyTrafficSortFromHeader('name')}>{groupBy === 'client' ? t('clients.email') : groupBy === 'inbound' ? t('nav.inbounds') : t('traffic.node')}{trafficSortIndicator('name')}</button></th><th className="w-36 px-4 py-3 text-right"><button type="button" className={cn(headerButtonClass, 'justify-end')} onClick={() => applyTrafficSortFromHeader('upload')}>Up{trafficSortIndicator('upload')}</button></th><th className="w-36 px-4 py-3 text-right"><button type="button" className={cn(headerButtonClass, 'justify-end')} onClick={() => applyTrafficSortFromHeader('download')}>Down{trafficSortIndicator('download')}</button></th><th className="w-44 px-4 py-3 text-right"><button type="button" className={cn(headerButtonClass, 'justify-end')} onClick={() => applyTrafficSortFromHeader('total')}>{t('traffic.total')}{trafficSortIndicator('total')}</button></th></tr></thead><tbody>{sortedTraffic.map((item, idx) => { const pct = filteredTotalTraffic > 0 ? (item.total / filteredTotalTraffic * 100).toFixed(1) : '0'; return <tr key={idx} className="border-b border-cyan-500/10 hover:bg-cyan-400/5"><td className="px-4 py-3 font-mono text-xs text-slate-500">{idx + 1}</td><td className="min-w-0 px-4 py-3"><button type="button" className={cn('block max-w-full truncate text-left font-medium', item.email && onNavigateToClient ? 'text-cyan-300 hover:text-cyan-200' : 'cursor-default text-slate-100')} title={item.email && onNavigateToClient ? `Filter clients by: ${item.email}` : undefined} onClick={() => item.email && onNavigateToClient && onNavigateToClient(item.email)}>{item.email || item.node_name || t('traffic.unknown')}</button>{renderNodeChips(item)}</td><td className="px-4 py-3 text-right"><span className={cn(valueClass, 'ml-auto text-cyan-300')}>{formatBytes(item.upload)}</span></td><td className="px-4 py-3 text-right"><span className={cn(valueClass, 'ml-auto text-emerald-300')}>{formatBytes(item.download)}</span></td><td className="px-4 py-3 text-right"><strong className={cn(valueClass, 'ml-auto text-indigo-200')}>{formatBytes(item.total)}</strong><div className="mt-2 flex items-center justify-end gap-2"><div className="h-1.5 w-20 overflow-hidden rounded-full bg-[#0a0e1a]"><div className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-cyan-300" style={{ width: `${pct}%` }} /></div><span className="whitespace-nowrap font-mono text-[11px] text-slate-500">{pct}%</span></div></td></tr>; })}</tbody><tfoot><tr className="border-t border-cyan-500/20 bg-cyan-500/5"><td colSpan={2} className="px-4 py-3 text-xs font-medium uppercase tracking-[0.14em] text-slate-500">Total {filteredTrafficData.length} {(filterNodeName || trafficSearch) ? '(filtered)' : ''}</td><td className="px-4 py-3 text-right"><span className={cn(valueClass, 'ml-auto text-cyan-300')}>{formatBytes(filteredTotalUpload)}</span></td><td className="px-4 py-3 text-right"><span className={cn(valueClass, 'ml-auto text-emerald-300')}>{formatBytes(filteredTotalDownload)}</span></td><td className="px-4 py-3 text-right"><span className={cn(valueClass, 'ml-auto text-indigo-200')}>{formatBytes(filteredTotalTraffic)}</span></td></tr></tfoot></table></div>
            <div className="grid min-w-0 grid-cols-1 gap-2 lg:hidden">{sortedTraffic.map((item, idx) => { const pct = filteredTotalTraffic > 0 ? (item.total / filteredTotalTraffic * 100).toFixed(1) : '0'; return <article key={idx} className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-3"><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0"><div className="mb-2 font-mono text-xs text-slate-500">#{idx + 1}</div><button type="button" className={cn('block max-w-full truncate text-left text-sm font-medium', item.email && onNavigateToClient ? 'text-cyan-300' : 'cursor-default text-slate-100')} title={item.email && onNavigateToClient ? `Filter clients by: ${item.email}` : undefined} onClick={() => item.email && onNavigateToClient && onNavigateToClient(item.email)}>{item.email || item.node_name || t('traffic.unknown')}</button>{renderNodeChips(item)}</div><span className={cn(valueClass, 'text-right text-indigo-200')}>{formatBytes(item.total)}</span></div><div className="mt-4 grid grid-cols-2 gap-2"><div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2"><div className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">Up</div><span className={cn(valueClass, 'mt-1 text-cyan-300')}>{formatBytes(item.upload)}</span></div><div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2"><div className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">Down</div><span className={cn(valueClass, 'mt-1 text-emerald-300')}>{formatBytes(item.download)}</span></div></div><div className="mt-3 flex items-center gap-2"><div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-[#0a0e1a]"><div className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-cyan-300" style={{ width: `${pct}%` }} /></div><span className="min-w-[3rem] whitespace-nowrap text-right font-mono text-xs text-slate-500">{pct}%</span></div></article>; })}</div>
          </>}
        </section>
      </div>
    </div>
  );
};
