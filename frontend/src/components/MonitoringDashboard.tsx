import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { registerPollingTask } from '../services/pollingScheduler';
import { useTrafficStatsSubscription, TrafficUpdate } from '../services/useTrafficStatsSubscription';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';

const lineGlowPlugin = {
  id: 'lineGlowPlugin',
  beforeDatasetsDraw(chart: any) {
    const { ctx } = chart;
    ctx.save();
    ctx.shadowColor = 'rgba(56, 189, 248, 0.38)';
    ctx.shadowBlur = 10;
    ctx.shadowOffsetY = 0;
  },
  afterDatasetsDraw(chart: any) {
    chart.ctx.restore();
  },
};

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Title, Tooltip, Legend, lineGlowPlugin);

interface NodeItem {
  id: number;
  name: string;
}

interface HistoryPoint {
  ts: number;
  node_id: number;
  node_name: string;
  available: number;
  xray_running: number;
  cpu: number;
  online_clients: number;
  traffic_total: number;
  poll_ms: number;
}

interface DepsHealth {
  status: string;
  collector_running: boolean;
  redis: {
    enabled: boolean;
    ok: boolean;
    error: string | null;
  };
}

interface TrafficStatsResponse {
  stats: Record<string, { up: number; down: number; total: number; count: number }>;
  group_by: 'client' | 'inbound' | 'node';
}

interface LiveTrafficPoint {
  ts: number;
  nodesTotal: number;
  peopleTotal: number;
  inboundsTotal: number;
  nodeTotals: Record<string, number>;
}

type TrafficMode = 'history' | 'live';
type TrafficSource = 'nodes' | 'people' | 'inbounds';
type TrafficVisualStyle = 'stepped' | 'bars' | 'smooth';
type TrafficSmoothing = 'raw' | 'sma3' | 'sma5';
type NullableNumberSeries = (number | null)[];
interface BucketedNodeHistory {
  nodeId: number;
  nodeName: string;
  points: (HistoryPoint | null)[];
  bucketsRaw: Map<number, HistoryPoint[]>;
}

interface SnapshotNode {
  name: string;
  node_id: number;
  available: boolean;
  xray_running: boolean;
  cpu: number;
  online_clients: number;
  traffic_total: number;
}

interface AdGuardSource {
  id: number;
  name: string;
  admin_url: string;
  dns_url: string;
  username: string;
  verify_tls: boolean;
  enabled: boolean;
  last_error: string;
  last_success_ts: number;
  last_collected_ts: number;
}

interface AdGuardSnapshot {
  source_id: number;
  source_name: string;
  available: boolean;
  queries_total: number;
  blocked_total: number;
  blocked_rate: number;
  cache_hit_ratio: number;
  avg_latency_ms: number;
  upstream_errors: number;
  top_domains?: Array<{ name: string; count: number }>;
  top_blocked_domains?: Array<{ name: string; count: number }>;
  top_clients?: Array<{ name: string; count: number }>;
}

interface AdGuardOverview {
  ts: number;
  sources: AdGuardSnapshot[];
  summary: {
    sources_total: number;
    sources_online: number;
    queries_total: number;
    blocked_total: number;
    blocked_rate: number;
    avg_latency_ms: number;
    cache_hit_ratio: number;
    upstream_errors: number;
  };
}

interface AdGuardHistoryPoint {
  ts: number;
  available: boolean;
  queries_total: number;
  blocked_total: number;
  blocked_rate: number;
  cache_hit_ratio: number;
  avg_latency_ms: number;
  upstream_errors: number;
}

interface AdGuardHistorySeries {
  source_id: number;
  source_name: string;
  points: Array<AdGuardHistoryPoint | null>;
}

interface AdGuardHistoryResponse {
  ts: number;
  range_sec: number;
  bucket_sec: number;
  buckets: number[];
  series: AdGuardHistorySeries[];
  summary: {
    queries_delta: number;
    blocked_delta: number;
    queries_per_sec: number;
    blocked_per_sec: number;
  };
}

interface StackServiceProbe {
  enabled: boolean;
  url: string;
  ok: boolean;
  status_code: number | null;
  error: string;
}

interface StackStatusResponse {
  ts: number;
  public_paths?: {
    panel?: string;
    grafana?: string;
  };
  services: {
    prometheus: StackServiceProbe;
    loki: StackServiceProbe;
    grafana: StackServiceProbe;
  };
  prometheus_metrics: Record<string, number | null>;
}

interface ResourceMetric {
  current?: number;
  total?: number;
  percent?: number;
}

interface ServerResourceStatus {
  node: string;
  available: boolean;
  timestamp?: string;
  error?: string;
  reason?: string;
  system?: {
    cpu?: number;
    mem?: ResourceMetric;
    disk?: ResourceMetric;
    swap?: ResourceMetric;
    uptime?: number;
    loads?: number[];
  };
  xray?: {
    running?: boolean;
    uptime?: number;
    version?: string;
  };
  network?: {
    upload?: number;
    download?: number;
  };
}

interface ServerStatusResponse {
  servers?: ServerResourceStatus[];
  count?: number;
}

interface CollectorStatus {
  mode?: string;
  running?: boolean;
  ws_connections?: number;
  timestamp?: number;
}

const RANGE_OPTIONS = [
  { value: 3600, label: '1h' },
  { value: 6 * 3600, label: '6h' },
  { value: 24 * 3600, label: '24h' },
  { value: 7 * 24 * 3600, label: '7d' },
] as const;

const TRAFFIC_STEP_OPTIONS = [
  { value: 5, label: '5s' },
  { value: 10, label: '10s' },
  { value: 30, label: '30s' },
  { value: 60, label: '1m' },
  { value: 5 * 60, label: '5m' },
  { value: 10 * 60, label: '10m' },
] as const;

function normalizeStepForMode(mode: TrafficMode, stepSec: number): number {
  if (mode === 'history') {
    // History is persisted at >= 30s granularity.
    return Math.max(30, stepSec);
  }
  return Math.max(5, stepSec);
}

function buildGrafanaUrl(runtimePath?: string): string {
  const normalizePath = (value: string): string => {
    const cleaned = value.trim().replace(/^\/+|\/+$/g, '');
    return cleaned ? `/${cleaned}/` : '/grafana/';
  };

  if (runtimePath && runtimePath.trim()) {
    return `${window.location.origin}${normalizePath(runtimePath)}`;
  }

  const explicitPath = (import.meta.env.VITE_GRAFANA_PATH as string | undefined)?.trim();
  if (explicitPath) {
    return `${window.location.origin}${normalizePath(explicitPath)}`;
  }

  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
  const legacyPath = base ? `${base}/grafana` : '/grafana';
  return `${window.location.origin}${legacyPath}/`;
}

const bytesToMb = (bytes: number) => bytes / (1024 * 1024);
const bytesToGb = (bytes: number) => bytes / (1024 * 1024 * 1024);
const CHART_PALETTE = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#06b6d4', '#e11d48', '#84cc16', '#f97316', '#14b8a6'];
const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');
const toFiniteNumber = (value: unknown): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const clampPercent = (value: unknown): number => Math.max(0, Math.min(100, Math.round(toFiniteNumber(value))));

const formatBytes = (bytes: number): string => {
  const value = Math.max(0, Number(bytes) || 0);
  if (value === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

const formatUptime = (seconds?: number): string => {
  const value = Math.max(0, Number(seconds) || 0);
  if (value === 0) return '-';
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
};

function getBucketSec(rangeSec: number, preferredStepSec?: number): number {
  if (preferredStepSec && preferredStepSec > 0) return preferredStepSec;
  if (rangeSec <= 3600) return 60;
  if (rangeSec <= 6 * 3600) return 120;
  if (rangeSec <= 24 * 3600) return 300;
  return 900;
}

function buildUsageFromCumulative(points: NullableNumberSeries): NullableNumberSeries {
  let prev: number | null = null;
  return points.map((cur) => {
    if (cur === null || Number.isNaN(cur)) return null;
    if (prev === null) {
      prev = cur;
      return 0;
    }
    let delta = cur - prev;
    if (delta < 0) {
      delta = cur;
    }
    prev = cur;
    return Math.max(0, delta);
  });
}

function smoothSeries(values: NullableNumberSeries, mode: TrafficSmoothing): NullableNumberSeries {
  const windowSize = mode === 'sma3' ? 3 : mode === 'sma5' ? 5 : 1;
  if (windowSize <= 1) return values;

  return values.map((value, idx) => {
    if (value === null || Number.isNaN(value)) return null;
    const start = Math.max(0, idx - windowSize + 1);
    const sample = values
      .slice(start, idx + 1)
      .filter((v): v is number => v !== null && !Number.isNaN(v));
    if (!sample.length) return value;
    const avg = sample.reduce((sum, v) => sum + v, 0) / sample.length;
    return Number(avg.toFixed(2));
  });
}

function buildTrafficConsumptionSeries(points: (HistoryPoint | null)[]): NullableNumberSeries {
  let baseTotal: number | null = null;
  let prevTotal: number | null = null;
  let accumulated = 0;
  return points.map((point) => {
    if (!point) return null;
    const curTotal = Number(point.traffic_total || 0);
    if (baseTotal === null) {
      baseTotal = curTotal;
      prevTotal = curTotal;
      return 0;
    }
    const prev = prevTotal ?? curTotal;
    let delta = curTotal - prev;
    // If node counter has reset, treat current total as new-cycle usage.
    if (delta < 0) {
      delta = curTotal;
    }
    prevTotal = curTotal;
    accumulated += Math.max(0, delta);
    return accumulated;
  });
}

function buildBucketTrafficConsumptionSeries(
  perNode: BucketedNodeHistory[],
  buckets: number[]
): NullableNumberSeries {
  let cumulative = 0;
  return buckets.map((bucketTs) => {
    let intervalUsage = 0;
    for (const nodeData of perNode) {
      const pointsInBucket = nodeData.bucketsRaw.get(bucketTs) || [];
      if (pointsInBucket.length === 0) continue;
      
      // Sort by timestamp to get first and last points in bucket
      pointsInBucket.sort((a, b) => a.ts - b.ts);
      const first = pointsInBucket[0];
      const last = pointsInBucket[pointsInBucket.length - 1];
      
      const lastTotal = Number(last?.traffic_total || 0);
      const firstTotal = Number(first?.traffic_total || 0);
      
      let delta = lastTotal - firstTotal;
      // Handle counter reset: if delta is negative, treat last total as new-cycle usage.
      if (delta < 0) {
        delta = lastTotal;
      }
      intervalUsage += Math.max(0, delta);
    }
    cumulative += intervalUsage;
    return cumulative;
  });
}

function bucketizeAllNodesHistory(points: HistoryPoint[], rangeSec: number, preferredStepSec?: number): {
  buckets: number[];
  perNode: BucketedNodeHistory[];
} {
  const bucketSec = getBucketSec(rangeSec, preferredStepSec);

  // Group ALL points per node per bucket (for per-bucket delta calculation).
  const perNodeBucket = new Map<number, Map<number, HistoryPoint[]>>();
  for (const p of points) {
    const bucketTs = Math.floor(p.ts / bucketSec) * bucketSec;
    const nodeMap = perNodeBucket.get(p.node_id) || new Map<number, HistoryPoint[]>();
    const bucket = nodeMap.get(bucketTs) || [];
    bucket.push(p);
    nodeMap.set(bucketTs, bucket);
    perNodeBucket.set(p.node_id, nodeMap);
  }

  const allBuckets = new Set<number>();
  for (const nodeMap of perNodeBucket.values()) {
    for (const ts of nodeMap.keys()) allBuckets.add(ts);
  }
  const buckets = Array.from(allBuckets).sort((a, b) => a - b);

  const perNode = Array.from(perNodeBucket.entries())
    .map(([nodeId, nodeMap]) => {
      const firstBucket = Array.from(nodeMap.values())[0] || [];
      const nodeName = firstBucket[0]?.node_name || `Node ${nodeId}`;
      return {
        nodeId,
        nodeName,
        points: buckets.map((ts) => {
          const bucket = nodeMap.get(ts) || [];
          if (bucket.length === 0) return null;
          // Return latest point in bucket for display purposes.
          bucket.sort((a, b) => a.ts - b.ts);
          return bucket[bucket.length - 1];
        }),
        bucketsRaw: nodeMap,
      };
    })
    .sort((a, b) => a.nodeName.localeCompare(b.nodeName));

  return { buckets, perNode };
}

function formatTickLabel(tsSec: number, rangeSec: number): string {
  const d = new Date(tsSec * 1000);
  if (rangeSec > 24 * 3600) {
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export const MonitoringDashboard: React.FC = () => {
  const { stylePreset } = useTheme();
  const { t } = useTranslation();

  const [nodes, setNodes] = useState<NodeItem[]>([]);
  const [selectedScope, setSelectedScope] = useState<string>('all'); // "all" | node id as string
  const [rangeSec, setRangeSec] = useState<number>(24 * 3600);
  const [trafficUnit, setTrafficUnit] = useState<'MB' | 'GB'>('MB');
  const [trafficMode, setTrafficMode] = useState<TrafficMode>('history');
  const [trafficSource, setTrafficSource] = useState<TrafficSource>('nodes');
  const [trafficStepSec, setTrafficStepSec] = useState<number>(60);
  const [trafficVisualStyle, setTrafficVisualStyle] = useState<TrafficVisualStyle>('stepped');
  const [trafficSmoothing, setTrafficSmoothing] = useState<TrafficSmoothing>('raw');
  const [liveTrafficSeries, setLiveTrafficSeries] = useState<LiveTrafficPoint[]>([]);
  const [liveTrafficError, setLiveTrafficError] = useState('');
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [allScopeHistory, setAllScopeHistory] = useState<HistoryPoint[]>([]);
  const [latestSnapshotNodes, setLatestSnapshotNodes] = useState<SnapshotNode[]>([]);
  const [depsHealth, setDepsHealth] = useState<DepsHealth | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState('');
  const [adguardSources, setAdguardSources] = useState<AdGuardSource[]>([]);
  const [adguardOverview, setAdguardOverview] = useState<AdGuardOverview | null>(null);
  const [adguardHistory, setAdguardHistory] = useState<AdGuardHistoryResponse | null>(null);
  const [stackStatus, setStackStatus] = useState<StackStatusResponse | null>(null);
  const [serverStatuses, setServerStatuses] = useState<ServerResourceStatus[]>([]);
  const [collectorStatus, setCollectorStatus] = useState<CollectorStatus | null>(null);
  const [adguardLoading, setAdguardLoading] = useState(false);
  const [adguardError, setAdguardError] = useState('');
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceError, setResourceError] = useState('');
  const [blockedSourceFilter, setBlockedSourceFilter] = useState<string>('all');
  const [blockedSearch, setBlockedSearch] = useState('');
  const [blockedShowCount, setBlockedShowCount] = useState<number>(25);
  const realtimeRefreshRef = useRef(0);
  const [editingAdguardSourceId, setEditingAdguardSourceId] = useState<number | null>(null);
  const [adguardForm, setAdguardForm] = useState({
    name: '',
    admin_url: '',
    dns_url: '',
    username: '',
    password: '',
    verify_tls: true,
    enabled: true,
  });
  const grafanaUrl = useMemo(() => {
    const runtimeGrafanaPath = stackStatus?.public_paths?.grafana;
    return buildGrafanaUrl(runtimeGrafanaPath);
  }, [stackStatus?.public_paths?.grafana]);

  const isAllScope = selectedScope === 'all';
  const selectedNodeId = isAllScope ? null : Number(selectedScope);
  const selectedNodeName = useMemo(
    () => (isAllScope ? 'All servers' : nodes.find((n) => n.id === selectedNodeId)?.name || 'Unknown'),
    [isAllScope, nodes, selectedNodeId]
  );

  const loadNodes = async () => {
    const res = await api.get('/v1/nodes', { auth: getAuth() });
    const list: NodeItem[] = (res.data || []).map((n: any) => ({ id: n.id, name: n.name }));
    setNodes(list);
    if (!selectedScope && list.length > 0) {
      setSelectedScope('all');
    }
  };

  const fetchNodeHistory = async (nodeId: number, sinceSec: number, limit: number): Promise<HistoryPoint[]> => {
    const res = await api.get(`/v1/history/nodes/${nodeId}`, {
      auth: getAuth(),
      params: { since_sec: sinceSec, limit },
    });
    return (res.data?.points || []) as HistoryPoint[];
  };

  const loadHistory = async (scope: string, sinceSec: number) => {
    setLoadingHistory(true);
    try {
      if (scope === 'all') {
        if (nodes.length === 0) {
          setHistory([]);
          setAllScopeHistory([]);
          setLoadingHistory(false);
          return;
        }
        const perNodeLimit = sinceSec >= 7 * 24 * 3600 ? 900 : 1200;
        const allResults = await Promise.allSettled(
          nodes.map((n) => fetchNodeHistory(n.id, sinceSec, perNodeLimit))
        );
        const successful = allResults
          .filter((result): result is PromiseFulfilledResult<HistoryPoint[]> => result.status === 'fulfilled')
          .map((result) => result.value)
          .flat();

        setAllScopeHistory(successful);
        setHistory([]);

        const failed = allResults.length - allResults.filter((result) => result.status === 'fulfilled').length;
        if (failed > 0 && successful.length === 0) {
          setError(t('monitoringDashboard.loadAllHistoryFailed'));
        }
      } else {
        const nodeId = Number(scope);
        const data = await fetchNodeHistory(nodeId, sinceSec, 2000);
        setHistory(data);
        setAllScopeHistory([]);
      }
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || t('monitoringDashboard.loadHistoryFailed'));
    } finally {
      setLoadingHistory(false);
    }
  };

  const loadLatestSnapshot = async (): Promise<SnapshotNode[]> => {
    try {
      const res = await api.get('/v1/snapshots/latest', { auth: getAuth() });
      const parsed = (res.data?.nodes || []) as SnapshotNode[];
      setLatestSnapshotNodes(parsed);
      return parsed;
    } catch {
      setLatestSnapshotNodes([]);
      return [];
    }
  };

  const loadTrafficStats = async (
    groupBy: 'client' | 'inbound' | 'node',
    limit: number = 0,
  ): Promise<TrafficStatsResponse> => {
    const res = await api.get('/v1/traffic/stats', {
      auth: getAuth(),
      params: { group_by: groupBy, limit },
    });
    return (res.data || { stats: {}, group_by: groupBy }) as TrafficStatsResponse;
  };

  const sumTrafficTotals = (stats: Record<string, { total: number }>): number =>
    Object.values(stats || {}).reduce((sum, item) => sum + Number(item?.total || 0), 0);

  const loadDepsHealth = async () => {
    try {
      const res = await api.get('/v1/health/deps', { auth: getAuth() });
      setDepsHealth(res.data as DepsHealth);
    } catch {
      setDepsHealth(null);
    }
  };

  const loadAdguardSources = async () => {
    const res = await api.get('/v1/adguard/sources', { auth: getAuth() });
    setAdguardSources((res.data || []) as AdGuardSource[]);
  };

  const loadAdguardOverview = async () => {
    try {
      setAdguardLoading(true);
      const res = await api.get('/v1/adguard/overview', { auth: getAuth() });
      setAdguardOverview(res.data as AdGuardOverview);
      setAdguardError('');
    } catch (err: any) {
      setAdguardError(err?.response?.data?.detail || t('monitoringDashboard.loadAdguardOverviewFailed'));
      setAdguardOverview(null);
    } finally {
      setAdguardLoading(false);
    }
  };

  const loadAdguardHistory = async () => {
    try {
      const bucketSec = rangeSec <= 3600 ? 60 : rangeSec <= 6 * 3600 ? 120 : rangeSec <= 24 * 3600 ? 300 : 900;
      const res = await api.get('/v1/adguard/history', {
        auth: getAuth(),
        params: { range_sec: rangeSec, bucket_sec: bucketSec },
      });
      setAdguardHistory(res.data as AdGuardHistoryResponse);
    } catch {
      setAdguardHistory(null);
    }
  };

  const loadStackStatus = async () => {
    try {
      const res = await api.get('/v1/monitoring/stack', { auth: getAuth() });
      setStackStatus(res.data as StackStatusResponse);
    } catch {
      setStackStatus(null);
    }
  };

  const loadServerStatuses = async () => {
    try {
      setResourceLoading(true);
      const res = await api.get('/v1/servers/status', { auth: getAuth() });
      const payload = res.data as ServerStatusResponse;
      const parsed = Array.isArray(payload?.servers) ? payload.servers : [];
      setServerStatuses(parsed);
      setResourceError('');
      return parsed;
    } catch (err: any) {
      setServerStatuses([]);
      setResourceError(err?.response?.data?.detail || t('serverStatus.loadFailed'));
      return [];
    } finally {
      setResourceLoading(false);
    }
  };

  const loadCollectorStatus = async () => {
    try {
      const res = await api.get('/v1/collector/status', { auth: getAuth() });
      setCollectorStatus(res.data as CollectorStatus);
    } catch {
      setCollectorStatus(null);
    }
  };


  const collectAdguardNow = async () => {
    try {
      setAdguardLoading(true);
      await api.post('/v1/adguard/collect-now', {}, { auth: getAuth() });
      await Promise.all([loadAdguardOverview(), loadAdguardSources(), loadAdguardHistory(), loadStackStatus()]);
      setAdguardError('');
    } catch (err: any) {
      setAdguardError(err?.response?.data?.detail || t('monitoringDashboard.collectAdguardFailed'));
    } finally {
      setAdguardLoading(false);
    }
  };

  const resetAdguardForm = () => {
    setEditingAdguardSourceId(null);
    setAdguardForm({
      name: '',
      admin_url: '',
      dns_url: '',
      username: '',
      password: '',
      verify_tls: true,
      enabled: true,
    });
  };

  const editAdguardSource = (source: AdGuardSource) => {
    setEditingAdguardSourceId(source.id);
    setAdguardForm({
      name: source.name || '',
      admin_url: source.admin_url || '',
      dns_url: source.dns_url || '',
      username: source.username || '',
      password: '',
      verify_tls: source.verify_tls !== false,
      enabled: source.enabled !== false,
    });
  };

  const saveAdguardSource = async () => {
    try {
      setAdguardLoading(true);
      if (editingAdguardSourceId !== null) {
        await api.put(`/v1/adguard/sources/${editingAdguardSourceId}`, adguardForm, { auth: getAuth() });
      } else {
        await api.post('/v1/adguard/sources', adguardForm, { auth: getAuth() });
      }
      resetAdguardForm();
      await Promise.all([loadAdguardSources(), collectAdguardNow()]);
    } catch (err: any) {
      setAdguardError(err?.response?.data?.detail || t('monitoringDashboard.addAdguardSourceFailed'));
    } finally {
      setAdguardLoading(false);
    }
  };

  const deleteAdguardSource = async (source: AdGuardSource) => {
    if (!window.confirm(`${t('common.delete')} ${source.name}?`)) return;
    try {
      setAdguardLoading(true);
      await api.delete(`/v1/adguard/sources/${source.id}`, { auth: getAuth() });
      if (editingAdguardSourceId === source.id) {
        resetAdguardForm();
      }
      await Promise.all([loadAdguardSources(), loadAdguardOverview(), loadAdguardHistory()]);
    } catch (err: any) {
      setAdguardError(err?.response?.data?.detail || t('common.failed'));
    } finally {
      setAdguardLoading(false);
    }
  };

  useEffect(() => {
    loadNodes().catch((err: any) => {
      setError(err?.response?.data?.detail || 'Failed to load nodes');
    });
    loadLatestSnapshot();
    loadDepsHealth();
    loadAdguardSources().catch(() => undefined);
    loadAdguardOverview().catch(() => undefined);
    loadAdguardHistory().catch(() => undefined);
    loadStackStatus().catch(() => undefined);
    loadServerStatuses().catch(() => undefined);
    loadCollectorStatus().catch(() => undefined);
  }, []);

  useEffect(() => {
    loadHistory(selectedScope, rangeSec);
  }, [selectedScope, rangeSec, nodes.length]);

  const effectiveTrafficSource: TrafficSource = !isAllScope && trafficSource !== 'nodes' ? 'nodes' : trafficSource;
  const effectiveTrafficMode: TrafficMode = effectiveTrafficSource === 'nodes' ? trafficMode : 'live';
  const effectiveTrafficStepSec = normalizeStepForMode(effectiveTrafficMode, trafficStepSec);

  useEffect(() => {
    setLiveTrafficSeries([]);
    setLiveTrafficError('');
  }, [effectiveTrafficMode, effectiveTrafficSource, selectedScope, rangeSec]);

  useEffect(() => {
    if (effectiveTrafficMode !== 'live') return;

    let cancelled = false;

    const tick = async () => {
      try {
        const snapshot = await loadLatestSnapshot();
        if (cancelled) return;

        const nodeTotals: Record<string, number> = {};
        for (const node of snapshot) {
          nodeTotals[node.name] = Number(node.traffic_total || 0);
        }

        let peopleTotal = 0;
        let inboundsTotal = 0;
        if (effectiveTrafficSource === 'people') {
          const traffic = await loadTrafficStats('client', 1500);
          if (cancelled) return;
          peopleTotal = sumTrafficTotals(traffic.stats);
        } else if (effectiveTrafficSource === 'inbounds') {
          const traffic = await loadTrafficStats('inbound', 1500);
          if (cancelled) return;
          inboundsTotal = sumTrafficTotals(traffic.stats);
        }

        const nodesTotal = Object.values(nodeTotals).reduce((sum, v) => sum + Number(v || 0), 0);
        const ts = Math.floor(Date.now() / 1000);

        setLiveTrafficSeries((prev) => {
          const next = [...prev, { ts, nodesTotal, peopleTotal, inboundsTotal, nodeTotals }];
          const cutoff = ts - rangeSec;
          // Keep only visible window and remove accidental same-second duplicates.
          const filtered = next.filter((p) => p.ts >= cutoff);
          const dedup: LiveTrafficPoint[] = [];
          for (const p of filtered) {
            if (dedup.length > 0 && dedup[dedup.length - 1].ts === p.ts) {
              dedup[dedup.length - 1] = p;
            } else {
              dedup.push(p);
            }
          }
          return dedup;
        });

        setLiveTrafficError('');
      } catch (err: any) {
        if (!cancelled) {
          setLiveTrafficError(err?.response?.data?.detail || 'Live traffic sampling failed');
        }
      }
    };

    tick();
    const dispose = registerPollingTask({
      id: `monitoring-live:${effectiveTrafficSource}:${selectedScope}:${rangeSec}:${effectiveTrafficStepSec}`,
      intervalMs: effectiveTrafficStepSec * 1000,
      hiddenIntervalMs: Math.max(effectiveTrafficStepSec * 3000, 30_000),
      run: tick,
    });
    return () => {
      cancelled = true;
      dispose();
    };
  }, [effectiveTrafficMode, effectiveTrafficSource, effectiveTrafficStepSec, selectedScope, rangeSec]);

  useEffect(() => {
    return () => undefined;
  }, []);

  const handleRealtimeUpdate = useCallback(
    (update: TrafficUpdate) => {
      if (update.type !== 'server_status' && update.type !== 'traffic_update' && update.type !== 'client_update') {
        return;
      }
      const now = Date.now();
      if (now - realtimeRefreshRef.current < 3000) return;
      realtimeRefreshRef.current = now;

      loadHistory(selectedScope, rangeSec);
      loadLatestSnapshot();
      loadDepsHealth();
      loadStackStatus();
      loadServerStatuses();
      loadCollectorStatus();
    },
    [selectedScope, rangeSec],
  );

  useTrafficStatsSubscription({
    channels: ['server_status', 'traffic', 'clients'],
    onUpdate: handleRealtimeUpdate,
    onError: (err) => console.warn('[MonitoringDashboard] realtime error:', err),
    fallbackPollIntervalMs: 60_000,
    fallbackRun: () => {
      loadHistory(selectedScope, rangeSec);
      loadLatestSnapshot();
      loadDepsHealth();
      loadAdguardOverview();
      loadAdguardHistory();
      loadStackStatus();
      loadServerStatuses();
      loadCollectorStatus();
    },
  });

  const latestForSelected = useMemo(() => {
    if (isAllScope) return null;
    return (
      latestSnapshotNodes.find((n) => n.node_id === selectedNodeId || n.name === selectedNodeName) || null
    );
  }, [isAllScope, latestSnapshotNodes, selectedNodeId, selectedNodeName]);

  const allNodesStatus = useMemo(() => {
    const total = latestSnapshotNodes.length;
    const online = latestSnapshotNodes.filter((n) => n.available).length;
    const onlineClients = latestSnapshotNodes.reduce((sum, n) => sum + Number(n.online_clients || 0), 0);
    return { total, online, onlineClients };
  }, [latestSnapshotNodes]);

  const selectedServerStatus = useMemo(
    () =>
      isAllScope
        ? null
        : serverStatuses.find((status) => status.node === selectedNodeName) || null,
    [isAllScope, serverStatuses, selectedNodeName],
  );

  const activeServerStatuses = useMemo(
    () => serverStatuses.filter((status) => status.available && status.system),
    [serverStatuses],
  );

  const resourceSource = useMemo(
    () => (isAllScope ? activeServerStatuses : selectedServerStatus ? [selectedServerStatus] : []),
    [activeServerStatuses, isAllScope, selectedServerStatus],
  );

  const resourceSummary = useMemo(() => {
    if (!resourceSource.length) return null;
    const count = resourceSource.length;
    const cpuValues = resourceSource.map((status) => Number(status.system?.cpu || 0));
    const memCurrent = resourceSource.reduce((sum, status) => sum + Number(status.system?.mem?.current || 0), 0);
    const memTotal = resourceSource.reduce((sum, status) => sum + Number(status.system?.mem?.total || 0), 0);
    const diskCurrent = resourceSource.reduce((sum, status) => sum + Number(status.system?.disk?.current || 0), 0);
    const diskTotal = resourceSource.reduce((sum, status) => sum + Number(status.system?.disk?.total || 0), 0);
    const uptimeValues = resourceSource.map((status) => Number(status.system?.uptime || status.xray?.uptime || 0));
    const cpuAvg = cpuValues.reduce((sum, value) => sum + value, 0) / count;
    const memPercent = memTotal > 0 ? (memCurrent / memTotal) * 100 : 0;
    const diskPercent = diskTotal > 0 ? (diskCurrent / diskTotal) * 100 : 0;
    const uptimeAvg = uptimeValues.reduce((sum, value) => sum + value, 0) / count;
    return {
      count,
      cpuAvg,
      memCurrent,
      memTotal,
      memPercent,
      diskCurrent,
      diskTotal,
      diskPercent,
      uptimeAvg,
      uptimeMax: uptimeValues.reduce((max, value) => Math.max(max, value), 0),
    };
  }, [resourceSource]);

  const selectedLiveSnapshotPoint = useMemo(() => {
    if (isAllScope) return null;
    const node = latestSnapshotNodes.find((n) => n.node_id === selectedNodeId || n.name === selectedNodeName);
    if (!node) return null;
    return {
      ts: Math.floor(Date.now() / 1000),
      node_id: node.node_id,
      node_name: node.name,
      available: node.available ? 1 : 0,
      xray_running: node.xray_running ? 1 : 0,
      cpu: Number(node.cpu || 0),
      online_clients: Number(node.online_clients || 0),
      traffic_total: Number(node.traffic_total || 0),
      poll_ms: 0,
    } as HistoryPoint;
  }, [isAllScope, latestSnapshotNodes, selectedNodeId, selectedNodeName]);

  const effectiveHistory = useMemo(() => {
    if (history.length > 0) return history;
    if (selectedLiveSnapshotPoint) return [selectedLiveSnapshotPoint];
    return [] as HistoryPoint[];
  }, [history, selectedLiveSnapshotPoint]);

  const effectiveAllScopeHistory = useMemo(() => {
    if (allScopeHistory.length > 0) return allScopeHistory;
    if (!isAllScope) return [] as HistoryPoint[];
    if (!latestSnapshotNodes.length) return [] as HistoryPoint[];
    const ts = Math.floor(Date.now() / 1000);
    return latestSnapshotNodes.map((node) => ({
      ts,
      node_id: node.node_id,
      node_name: node.name,
      available: node.available ? 1 : 0,
      xray_running: node.xray_running ? 1 : 0,
      cpu: Number(node.cpu || 0),
      online_clients: Number(node.online_clients || 0),
      traffic_total: Number(node.traffic_total || 0),
      poll_ms: 0,
    }));
  }, [allScopeHistory, isAllScope, latestSnapshotNodes]);

  const labels = effectiveHistory.map((p) => formatTickLabel(p.ts, rangeSec));
  const allScopeSeries = useMemo(() => bucketizeAllNodesHistory(effectiveAllScopeHistory, rangeSec), [effectiveAllScopeHistory, rangeSec]);
  const allScopeLabels = allScopeSeries.buckets.map((ts) => formatTickLabel(ts, rangeSec));
  const historyTrafficBucketSec = normalizeStepForMode('history', trafficStepSec);
  const trafficHistorySeries = useMemo(
    () => bucketizeAllNodesHistory(effectiveAllScopeHistory, rangeSec, historyTrafficBucketSec),
    [effectiveAllScopeHistory, rangeSec, historyTrafficBucketSec]
  );
  const trafficHistoryLabels = trafficHistorySeries.buckets.map((ts) => formatTickLabel(ts, rangeSec));

  const liveTrafficWindow = useMemo(() => {
    if (!liveTrafficSeries.length) return [] as LiveTrafficPoint[];
    const cutoff = Math.floor(Date.now() / 1000) - rangeSec;
    return liveTrafficSeries.filter((p) => p.ts >= cutoff);
  }, [liveTrafficSeries, rangeSec]);
  const liveTrafficLabels = liveTrafficWindow.map((p) => formatTickLabel(p.ts, rangeSec));

  const trafficLineShape = useMemo(
    () =>
      trafficVisualStyle === 'smooth'
        ? { tension: 0.25, stepped: false as const }
        : trafficVisualStyle === 'stepped'
        ? { tension: 0, stepped: true as const }
        : { tension: 0, stepped: false as const },
    [trafficVisualStyle]
  );
  const renderTrafficAsBars = trafficVisualStyle === 'bars';

  const trafficUnitLabel = trafficUnit;
  const convertBytes = (bytes: number) => (trafficUnit === 'GB' ? bytesToGb(bytes) : bytesToMb(bytes));
  const toTrafficUnit = (value: number | null) => (value === null ? null : Number(convertBytes(value).toFixed(2)));
  const smoothTrafficSeries = (series: Array<number | null>) => smoothSeries(series, trafficSmoothing);
  const trafficConsumptionLabel = `${trafficUnitLabel}`;
  const trafficModeLabel = effectiveTrafficMode === 'live' ? 'Live' : 'History';
  const trafficSourceLabel = effectiveTrafficSource === 'nodes' ? 'Nodes' : effectiveTrafficSource === 'people' ? 'People' : 'Inbounds';
  const trafficSmoothingLabel = trafficSmoothing === 'raw' ? 'raw' : trafficSmoothing === 'sma3' ? 'SMA-3' : 'SMA-5';
  const showingLiveSnapshotFallback = effectiveTrafficMode === 'history' && (isAllScope
    ? allScopeHistory.length === 0 && effectiveAllScopeHistory.length > 0
    : history.length === 0 && effectiveHistory.length > 0);
  const chartPalette = useMemo(
    () => stylePreset === '3'
      ? ['#fafafa', '#d4d4d8', '#a3a3a3', '#737373', '#525252', '#facc15', '#4ade80', '#ef4444']
      : CHART_PALETTE,
    [stylePreset]
  );

  const cpuData = {
    labels: isAllScope ? allScopeLabels : labels,
    datasets: isAllScope
      ? allScopeSeries.perNode.map((node, idx) => {
          const c = chartPalette[idx % chartPalette.length];
          return {
            label: node.nodeName,
            data: node.points.map((p) => (p ? Number((p.cpu || 0).toFixed(2)) : null)),
            borderColor: c,
            backgroundColor: c + '33',
            borderWidth: 2.2,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 3,
            spanGaps: true,
          };
        })
      : [
          {
            label: t('monitoringDashboard.cpuPercent'),
            data: effectiveHistory.map((p) => Number((p.cpu || 0).toFixed(2))),
            borderColor: 'var(--warning)',
            backgroundColor: 'color-mix(in srgb, var(--warning) 20%, transparent)',
            borderWidth: 2.2,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 3,
          },
        ],
  };

  const onlineData = {
    labels: isAllScope ? allScopeLabels : labels,
    datasets: isAllScope
      ? allScopeSeries.perNode.map((node, idx) => {
          const c = chartPalette[idx % chartPalette.length];
          return {
            label: node.nodeName,
            data: node.points.map((p) => (p ? Number(p.online_clients || 0) : null)),
            borderColor: c,
            backgroundColor: c + '33',
            borderWidth: 2.2,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 3,
            spanGaps: true,
          };
        })
      : [
          {
            label: t('monitoringDashboard.onlineClients'),
            data: effectiveHistory.map((p) => Number(p.online_clients || 0)),
            borderColor: 'var(--accent)',
            backgroundColor: 'color-mix(in srgb, var(--accent) 20%, transparent)',
            borderWidth: 2.2,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 3,
          },
        ],
  };

  const trafficData = useMemo(() => {
    if (effectiveTrafficMode === 'history') {
      if (isAllScope) {
        return {
          labels: trafficHistoryLabels,
          datasets: [
            {
              label: t('monitoringDashboard.allServersUsage'),
              data: smoothTrafficSeries(
                buildBucketTrafficConsumptionSeries(trafficHistorySeries.perNode, trafficHistorySeries.buckets).map((bytes) =>
                  toTrafficUnit(Number(bytes || 0))
                )
              ),
              borderColor: 'var(--info)',
              backgroundColor: 'color-mix(in srgb, var(--info) 27%, transparent)',
              borderWidth: 2.8,
              pointRadius: 0,
              pointHoverRadius: 4,
              spanGaps: true,
              ...trafficLineShape,
            },
            ...trafficHistorySeries.perNode.map((node, idx) => {
              const c = chartPalette[idx % chartPalette.length];
              const usageSeries = buildTrafficConsumptionSeries(node.points);
              const convertedSeries = usageSeries.map((bytes) => toTrafficUnit(bytes));
              return {
                label: node.nodeName,
                data: smoothTrafficSeries(convertedSeries),
                borderColor: c,
                backgroundColor: c + '33',
                borderWidth: 2.2,
                pointRadius: 0,
                pointHoverRadius: 3,
                spanGaps: true,
                ...trafficLineShape,
              };
            }),
          ],
        };
      }

      return {
        labels,
        datasets: [
          {
            label: `Traffic consumption (${trafficConsumptionLabel})`,
            data: smoothTrafficSeries(buildTrafficConsumptionSeries(effectiveHistory).map((bytes) => toTrafficUnit(Number(bytes || 0)))),
            borderColor: 'var(--info)',
            backgroundColor: 'color-mix(in srgb, var(--info) 20%, transparent)',
            borderWidth: 2.2,
            pointRadius: 0,
            pointHoverRadius: 3,
            ...trafficLineShape,
          },
        ],
      };
    }

    // Live mode
    if (!liveTrafficWindow.length) {
      return { labels: [] as string[], datasets: [] as any[] };
    }

    if (effectiveTrafficSource === 'people') {
      const usage = buildUsageFromCumulative(liveTrafficWindow.map((p) => Number(p.peopleTotal || 0)));
      return {
        labels: liveTrafficLabels,
        datasets: [
          {
            label: `People usage (${trafficConsumptionLabel})`,
            data: smoothTrafficSeries(usage.map((v) => toTrafficUnit(v))),
            borderColor: 'var(--success)',
            backgroundColor: 'color-mix(in srgb, var(--success) 20%, transparent)',
            borderWidth: 2.3,
            pointRadius: 0,
            pointHoverRadius: 3,
            ...trafficLineShape,
          },
        ],
      };
    }

    if (effectiveTrafficSource === 'inbounds') {
      const usage = buildUsageFromCumulative(liveTrafficWindow.map((p) => Number(p.inboundsTotal || 0)));
      return {
        labels: liveTrafficLabels,
        datasets: [
          {
            label: `Inbound usage (${trafficConsumptionLabel})`,
            data: smoothTrafficSeries(usage.map((v) => toTrafficUnit(v))),
            borderColor: 'var(--warning)',
            backgroundColor: 'color-mix(in srgb, var(--warning) 20%, transparent)',
            borderWidth: 2.3,
            pointRadius: 0,
            pointHoverRadius: 3,
            ...trafficLineShape,
          },
        ],
      };
    }

    // Live + nodes source
    if (isAllScope) {
      const totalUsage = buildUsageFromCumulative(liveTrafficWindow.map((p) => Number(p.nodesTotal || 0)));
      const perNodeDatasets = nodes
        .map((node, idx) => {
          const usage = buildUsageFromCumulative(
            liveTrafficWindow.map((p) => (typeof p.nodeTotals[node.name] === 'number' ? p.nodeTotals[node.name] : null))
          );
          if (!usage.some((v) => v !== null)) return null;
          const c = chartPalette[idx % chartPalette.length];
          return {
            label: node.name,
            data: smoothTrafficSeries(usage.map((v) => toTrafficUnit(v))),
            borderColor: c,
            backgroundColor: c + '33',
            borderWidth: 2.0,
            pointRadius: 0,
            pointHoverRadius: 3,
            spanGaps: true,
            ...trafficLineShape,
          };
        })
        .filter(Boolean);

      return {
        labels: liveTrafficLabels,
        datasets: [
          {
            label: `All servers live usage (${trafficConsumptionLabel})`,
            data: smoothTrafficSeries(totalUsage.map((v) => toTrafficUnit(v))),
            borderColor: 'var(--info)',
            backgroundColor: 'color-mix(in srgb, var(--info) 27%, transparent)',
            borderWidth: 2.8,
            pointRadius: 0,
            pointHoverRadius: 4,
            spanGaps: true,
            ...trafficLineShape,
          },
          ...(perNodeDatasets as any[]),
        ],
      };
    }

    const selectedUsage = buildUsageFromCumulative(
      liveTrafficWindow.map((p) => (typeof p.nodeTotals[selectedNodeName] === 'number' ? p.nodeTotals[selectedNodeName] : null))
    );
    return {
      labels: liveTrafficLabels,
      datasets: [
        {
          label: `${selectedNodeName} live usage (${trafficConsumptionLabel})`,
          data: smoothTrafficSeries(selectedUsage.map((v) => toTrafficUnit(v))),
          borderColor: 'var(--info)',
          backgroundColor: 'color-mix(in srgb, var(--info) 20%, transparent)',
          borderWidth: 2.4,
          pointRadius: 0,
          pointHoverRadius: 3,
          spanGaps: true,
          ...trafficLineShape,
        },
      ],
    };
  }, [
    effectiveTrafficMode,
    effectiveTrafficSource,
    isAllScope,
    trafficHistoryLabels,
    trafficHistorySeries,
    labels,
    effectiveHistory,
    liveTrafficWindow,
    liveTrafficLabels,
    selectedNodeName,
    trafficConsumptionLabel,
    chartPalette,
    nodes,
    trafficLineShape,
    trafficSmoothing,
  ]);

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom' as const,
        align: 'start' as const,
        maxHeight: 84,
        labels: {
          color: '#e2e8f0',
          usePointStyle: true,
          pointStyle: 'circle' as const,
          boxWidth: 10,
          boxHeight: 10,
          padding: 12,
          font: {
            size: 11,
            weight: 600 as const,
          },
        },
      },
      tooltip: {
        backgroundColor: '#0f1420',
        borderColor: 'rgba(30, 41, 59, 0.6)',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#cbd5e1',
        padding: 10,
        cornerRadius: 10,
        displayColors: true,
        boxPadding: 3,
      },
    },
    interaction: {
      intersect: false,
      mode: 'index' as const,
    },
    elements: {
      line: {
        capBezierPoints: true,
      },
      point: {
        hoverRadius: 4,
        hoverBorderWidth: 1.5,
        hoverBorderColor: '#ffffff',
      },
    },
    scales: {
      x: {
        ticks: {
          color: '#94a3b8',
          maxTicksLimit: 10,
          font: {
            weight: 600 as const,
          },
        },
        grid: { color: 'rgba(30, 41, 59, 0.6)' },
      },
      y: {
        ticks: {
          color: '#94a3b8',
          font: {
            weight: 600 as const,
          },
        },
        grid: { color: 'rgba(30, 41, 59, 0.6)' },
      },
    },
  };

  const trafficChartOptions = {
    ...chartOptions,
    plugins: {
      ...chartOptions.plugins,
      tooltip: {
        ...chartOptions.plugins.tooltip,
        callbacks: {
          label: (context: any) => {
            const datasetLabel = context?.dataset?.label || '';
            const y = Number(context?.parsed?.y || 0);
            return `${datasetLabel}: ${y.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${trafficConsumptionLabel}`;
          },
          title: (items: any[]) => {
            const base = items?.[0]?.label || '';
            return `${base} â€¢ ${trafficModeLabel} â€¢ step ${effectiveTrafficStepSec}s â€¢ ${trafficSourceLabel} â€¢ ${trafficSmoothingLabel}`;
          },
        },
      },
    },
    scales: {
      ...chartOptions.scales,
      y: {
        ...chartOptions.scales.y,
        ticks: {
          ...chartOptions.scales.y.ticks,
          callback: (value: any) => `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${trafficConsumptionLabel}`,
        },
      },
    },
  };

  const topBlockedDomains = useMemo(() => {
    const agg = new Map<string, number>();
    (adguardOverview?.sources || [])
      .filter((s) => blockedSourceFilter === 'all' || String(s.source_id) === blockedSourceFilter)
      .forEach((s) => {
      (s.top_blocked_domains || []).forEach((it) => {
        agg.set(it.name, (agg.get(it.name) || 0) + Number(it.count || 0));
      });
      });
    const needle = blockedSearch.trim().toLowerCase();
    return Array.from(agg.entries())
      .filter(([name]) => !needle || name.toLowerCase().includes(needle))
      .sort((a, b) => b[1] - a[1])
      .slice(0, blockedShowCount)
      .map(([name, count]) => ({ name, count }));
  }, [adguardOverview, blockedSourceFilter, blockedSearch, blockedShowCount]);

  const topClients = useMemo(() => {
    const agg = new Map<string, number>();
    (adguardOverview?.sources || []).forEach((s) => {
      (s.top_clients || []).forEach((it) => {
        agg.set(it.name, (agg.get(it.name) || 0) + Number(it.count || 0));
      });
    });
    return Array.from(agg.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, count]) => ({ name, count }));
  }, [adguardOverview]);

  const adguardTrendLabels = useMemo(
    () => (adguardHistory?.buckets || []).map((ts) => formatTickLabel(ts, adguardHistory?.range_sec || rangeSec)),
    [adguardHistory, rangeSec]
  );

  const toRateSeries = (points: Array<AdGuardHistoryPoint | null>, key: 'queries_total' | 'blocked_total') => {
    let prev: number | null = null;
    return points.map((p) => {
      if (!p) return null;
      const cur = Number(p[key] || 0);
      if (prev === null) {
        prev = cur;
        return 0;
      }
      const delta = Math.max(0, cur - prev);
      prev = cur;
      const bucket = adguardHistory?.bucket_sec || 60;
      return Number((delta / bucket).toFixed(3));
    });
  };

  const adguardQpsData = useMemo(() => {
    return {
      labels: adguardTrendLabels,
      datasets: (adguardHistory?.series || []).map((s, idx) => {
        const c = chartPalette[idx % chartPalette.length];
        return {
          label: `${s.source_name} QPS`,
          data: toRateSeries(s.points || [], 'queries_total'),
          borderColor: c,
          backgroundColor: c + '33',
          borderWidth: 2.1,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: 3,
          spanGaps: true,
        };
      }),
    };
  }, [adguardHistory, adguardTrendLabels]);

  const adguardBlockRateData = useMemo(() => {
    return {
      labels: adguardTrendLabels,
      datasets: (adguardHistory?.series || []).map((s, idx) => {
        const c = chartPalette[idx % chartPalette.length];
        return {
          label: `${s.source_name} Block %`,
          data: (s.points || []).map((p) => (p ? Number((p.blocked_rate || 0).toFixed(2)) : null)),
          borderColor: c,
          backgroundColor: c + '33',
          borderWidth: 2.1,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: 3,
          spanGaps: true,
        };
      }),
    };
  }, [adguardHistory, adguardTrendLabels]);

  const adguardLatencyData = useMemo(() => {
    return {
      labels: adguardTrendLabels,
      datasets: (adguardHistory?.series || []).map((s, idx) => {
        const c = chartPalette[idx % chartPalette.length];
        return {
          label: `${s.source_name} Latency ms`,
          data: (s.points || []).map((p) => (p ? Number((p.avg_latency_ms || 0).toFixed(2)) : null)),
          borderColor: c,
          backgroundColor: c + '33',
          borderWidth: 2.1,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: 3,
          spanGaps: true,
        };
      }),
    };
  }, [adguardHistory, adguardTrendLabels]);

  const inputClass =
    'min-w-0 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-xs font-light text-slate-100 outline-none transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10 placeholder:text-slate-600';
  const selectClass = `${inputClass} pr-8`;
  const primaryButtonClass =
    'inline-flex h-9 min-w-0 items-center justify-center rounded-md border border-cyan-300/25 bg-gradient-to-r from-cyan-500 to-blue-500 px-3 text-xs font-medium tracking-wide text-white transition hover:from-cyan-400 hover:to-blue-400 disabled:cursor-not-allowed disabled:opacity-45';
  const secondaryButtonClass =
    'inline-flex h-9 min-w-0 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs font-medium text-slate-100 transition hover:border-cyan-300/40 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
  const sectionTitleClass = 'text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400';
  const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420]';
  const subtlePanelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a]';
  const metricValueClass = 'font-mono tabular-nums whitespace-nowrap text-sm font-medium text-slate-100';
  const compactMetricClass = 'font-mono tabular-nums whitespace-nowrap text-xs font-medium text-slate-100';
  const chartCardClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4';
  const renderChartSkeleton = () => (
    <div className="relative h-full min-w-0 overflow-hidden rounded-lg bg-[#0a0e1a] p-4">
      <div className="absolute inset-x-4 top-10 h-px bg-cyan-500/10" />
      <div className="absolute inset-x-4 top-1/3 h-px bg-cyan-500/10" />
      <div className="absolute inset-x-4 top-2/3 h-px bg-cyan-500/10" />
      <div className="absolute inset-x-4 bottom-8 h-px bg-cyan-500/10" />
      <div className="flex h-full items-end gap-3 pt-12">
        {[38, 56, 44, 70, 62, 82, 52, 66].map((height, idx) => (
          <div key={idx} className="flex min-w-0 flex-1 items-end">
            <div
              className="w-full animate-pulse rounded-t-md bg-cyan-300/20"
              style={{ height: `${height}%`, animationDelay: `${idx * 85}ms` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
  const toneClass = (ok: boolean) => (ok ? 'text-emerald-300' : 'text-rose-300');
  const gaugeTone = (value: number) =>
    value >= 85
      ? { fill: 'from-rose-500 to-red-600', text: 'text-rose-300' }
      : value >= 60
      ? { fill: 'from-amber-400 to-orange-500', text: 'text-amber-300' }
      : { fill: 'from-cyan-500 to-blue-500', text: 'text-cyan-300' };
  const usageCards = [
    {
      label: 'Collector',
      value: collectorStatus?.running ? t('serverStatus.running') : t('serverStatus.stopped'),
      percent: collectorStatus?.running ? 100 : 0,
      helper: `${collectorStatus?.mode || 'unknown'} | WS ${collectorStatus?.ws_connections ?? 0}`,
    },
    {
      label: 'Redis',
      value: depsHealth?.redis?.enabled ? (depsHealth?.redis?.ok ? 'ok' : 'degraded') : 'disabled',
      percent: depsHealth?.redis?.enabled ? (depsHealth?.redis?.ok ? 100 : 62) : 0,
      helper: depsHealth?.redis?.enabled ? (depsHealth?.redis?.error || 'cache layer') : 'cache off',
    },
    {
      label: isAllScope ? t('monitoringDashboard.nodesOnline') : t('monitoringDashboard.nodeStatus'),
      value: isAllScope
        ? `${allNodesStatus.online}/${allNodesStatus.total}`
        : latestForSelected?.available
        ? t('nodes.online')
        : t('nodes.offline'),
      percent: isAllScope
        ? allNodesStatus.total > 0
          ? Math.round((allNodesStatus.online / allNodesStatus.total) * 100)
          : 0
        : latestForSelected?.available
        ? 100
        : 0,
      helper: isAllScope ? 'available fleet' : selectedNodeName,
    },
    {
      label: isAllScope ? t('monitoringDashboard.currentOnlineClients') : t('monitoringDashboard.currentOnlineClients'),
      value: String(isAllScope ? allNodesStatus.onlineClients : latestForSelected?.online_clients ?? 0),
      percent: Math.min(100, (isAllScope ? allNodesStatus.onlineClients : latestForSelected?.online_clients ?? 0) * 5),
      helper: isAllScope ? 'active sessions' : 'node sessions',
    },
  ];
  const resourceScopeHelper = isAllScope
    ? `${resourceSummary?.count || 0}/${serverStatuses.length || nodes.length} ${t('serverStatus.online').toLowerCase()}`
    : selectedNodeName;
  const resourceCards = [
    {
      label: t('serverStatus.cpu'),
      value: resourceSummary ? `${resourceSummary.cpuAvg.toFixed(1)}%` : '-',
      percent: clampPercent(resourceSummary?.cpuAvg),
      helper: resourceScopeHelper,
      detail: '',
    },
    {
      label: t('serverStatus.ram'),
      value: resourceSummary ? `${resourceSummary.memPercent.toFixed(1)}%` : '-',
      percent: clampPercent(resourceSummary?.memPercent),
      helper: resourceSummary ? `${formatBytes(resourceSummary.memCurrent)} / ${formatBytes(resourceSummary.memTotal)}` : resourceScopeHelper,
      detail: resourceScopeHelper,
    },
    {
      label: t('serverStatus.disk'),
      value: resourceSummary ? `${resourceSummary.diskPercent.toFixed(1)}%` : '-',
      percent: clampPercent(resourceSummary?.diskPercent),
      helper: resourceSummary ? `${formatBytes(resourceSummary.diskCurrent)} / ${formatBytes(resourceSummary.diskTotal)}` : resourceScopeHelper,
      detail: resourceScopeHelper,
    },
    {
      label: 'Uptime',
      value: formatUptime(isAllScope ? resourceSummary?.uptimeMax : resourceSummary?.uptimeAvg),
      percent: resourceSummary?.uptimeMax || resourceSummary?.uptimeAvg ? 100 : 0,
      helper: isAllScope ? 'max uptime' : selectedNodeName,
      detail: resourceScopeHelper,
    },
  ];
  const stackCards = [
    {
      label: 'Prometheus',
      ok: Boolean(stackStatus?.services?.prometheus?.ok),
      value: stackStatus?.services?.prometheus?.ok ? t('nodes.online') : t('nodes.offline'),
      percent: stackStatus?.services?.prometheus?.ok ? 100 : 0,
    },
    {
      label: 'Loki',
      ok: Boolean(stackStatus?.services?.loki?.ok),
      value: stackStatus?.services?.loki?.ok ? t('nodes.online') : t('nodes.offline'),
      percent: stackStatus?.services?.loki?.ok ? 100 : 0,
    },
    {
      label: 'Grafana',
      ok: Boolean(stackStatus?.services?.grafana?.ok),
      value: stackStatus?.services?.grafana?.ok ? t('nodes.online') : t('nodes.offline'),
      percent: stackStatus?.services?.grafana?.ok ? 100 : 0,
    },
  ];

  return (
    <div className="min-h-screen min-w-0 overflow-hidden bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6">
      <div className="mb-6 flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">{t('nav.monitoring')}</h2>
        </div>
        <a className={primaryButtonClass} href={grafanaUrl} target="_blank" rel="noreferrer">
          {t('monitoringDashboard.openGrafana')}
        </a>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-rose-500/45 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <section className="mb-4 grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('common.server')}</div>
          </div>
          <div className="min-w-0 p-4">
            <ChoiceChips
              className="min-w-0"
              options={[
                { value: 'all', label: t('common.all') },
                ...nodes.map((n) => ({ value: String(n.id), label: n.name })),
              ]}
              value={selectedScope}
              onChange={(value) => setSelectedScope(value)}
            />
          </div>
        </div>
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('monitoringDashboard.range')}</div>
          </div>
          <div className="min-w-0 p-4">
            <ChoiceChips
              className="min-w-0"
              options={RANGE_OPTIONS.map((range) => ({ value: range.value, label: range.label }))}
              value={rangeSec}
              onChange={(value) => setRangeSec(value)}
            />
          </div>
        </div>
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('traffic.title')}</div>
          </div>
          <div className="flex min-w-0 flex-col gap-3 p-4">
            <ChoiceChips
              className="min-w-0"
              options={[
                { value: 'MB', label: 'MB' },
                { value: 'GB', label: 'GB' },
              ]}
              value={trafficUnit}
              onChange={(value) => setTrafficUnit(value as 'MB' | 'GB')}
            />
            <button
              className={secondaryButtonClass}
              onClick={() => {
                loadHistory(selectedScope, rangeSec);
                loadLatestSnapshot();
                loadDepsHealth();
                loadAdguardOverview();
                loadAdguardHistory();
                loadStackStatus();
                loadServerStatuses();
                loadCollectorStatus();
              }}
              disabled={loadingHistory || resourceLoading}
            >
              {loadingHistory || resourceLoading ? t('header.updating') : t('common.refresh')}
            </button>
          </div>
        </div>
      </section>

      <section className="mb-6 grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-5">
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('monitoringDashboard.trafficMode')}</div>
          </div>
          <div className="min-w-0 p-4">
            <ChoiceChips
              className="min-w-0"
              options={[
                { value: 'history', label: 'History' },
                { value: 'live', label: 'Live' },
              ]}
              value={trafficMode}
              onChange={(value) => setTrafficMode(value as TrafficMode)}
            />
          </div>
        </div>
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('monitoringDashboard.source')}</div>
          </div>
          <div className="min-w-0 p-4">
            <ChoiceChips
              className="min-w-0"
              options={[
                { value: 'nodes', label: 'Nodes' },
                { value: 'people', label: t('monitoringDashboard.people') },
                { value: 'inbounds', label: t('nav.inbounds') },
              ]}
              value={trafficSource}
              onChange={(value) => setTrafficSource(value as TrafficSource)}
            />
          </div>
        </div>
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('monitoringDashboard.step')}</div>
          </div>
          <div className="min-w-0 p-4">
            <ChoiceChips
              className="min-w-0"
              options={TRAFFIC_STEP_OPTIONS.map((step) => ({ value: step.value, label: step.label }))}
              value={trafficStepSec}
              onChange={(value) => setTrafficStepSec(Number(value))}
            />
          </div>
        </div>
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('monitoringDashboard.style')}</div>
          </div>
          <div className="min-w-0 p-4">
            <ChoiceChips
              className="min-w-0"
              options={[
                { value: 'stepped', label: 'Stepped' },
                { value: 'bars', label: 'Bars' },
                { value: 'smooth', label: 'Smooth' },
              ]}
              value={trafficVisualStyle}
              onChange={(value) => setTrafficVisualStyle(value as TrafficVisualStyle)}
            />
          </div>
        </div>
        <div className={panelClass}>
          <div className="border-b border-cyan-500/20 px-4 py-3">
            <div className={sectionTitleClass}>{t('monitoringDashboard.smoothing')}</div>
          </div>
          <div className="min-w-0 p-4">
            <ChoiceChips
              className="min-w-0"
              options={[
                { value: 'raw', label: 'Raw' },
                { value: 'sma3', label: 'SMA-3' },
                { value: 'sma5', label: 'SMA-5' },
              ]}
              value={trafficSmoothing}
              onChange={(value) => setTrafficSmoothing(value as TrafficSmoothing)}
            />
          </div>
        </div>
      </section>

      <section className="mb-6 grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-3">
        {usageCards.map((card) => {
          const tone = gaugeTone(card.percent);
          return (
            <article key={card.label} className={chartCardClass}>
              <div className="flex items-center justify-between gap-3">
                <span className={sectionTitleClass}>{card.label}</span>
                <span className={cn('font-mono tabular-nums whitespace-nowrap text-xs font-medium', tone.text)}>
                  {card.percent}%
                </span>
              </div>
              <div className="mt-3 flex items-baseline justify-between gap-3">
                <strong className={metricValueClass}>{card.value}</strong>
                <span className="truncate text-right text-[11px] text-slate-500">{card.helper}</span>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#0a0e1a]">
                <div className={cn('h-full rounded-full bg-gradient-to-r', tone.fill)} style={{ width: `${card.percent}%` }} />
              </div>
            </article>
          );
        })}
      </section>

      {resourceError && (
        <div className="mb-4 rounded-lg border border-rose-500/45 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {resourceError}
        </div>
      )}

      <section className="mb-6 grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-4">
        {resourceCards.map((card) => {
          const tone = gaugeTone(card.percent);
          const isSkeleton = resourceLoading && !resourceSummary;
          return (
            <article key={card.label} className={chartCardClass}>
              <div className="flex items-center justify-between gap-3">
                <span className={sectionTitleClass}>{card.label}</span>
                <span className={cn('font-mono tabular-nums whitespace-nowrap text-xs font-medium', tone.text)}>
                  {isSkeleton ? '...' : `${card.percent}%`}
                </span>
              </div>
              <div className="mt-3 flex items-baseline justify-between gap-3">
                {isSkeleton ? (
                  <div className="h-6 w-24 animate-pulse rounded-md bg-cyan-300/10" />
                ) : (
                  <strong className={metricValueClass}>{card.value}</strong>
                )}
                <span className="truncate text-right text-[11px] text-slate-500">
                  {isSkeleton ? t('serverStatus.loadingLiveMetrics') : card.helper}
                </span>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#0a0e1a]">
                <div
                  className={cn('h-full rounded-full bg-gradient-to-r', tone.fill, isSkeleton && 'animate-pulse')}
                  style={{ width: isSkeleton ? '72%' : `${card.percent}%` }}
                />
              </div>
            </article>
          );
        })}
      </section>

      <div className="grid min-w-0 grid-cols-1 gap-6">
        {trafficSource !== 'nodes' && (
          <div className="rounded-lg border border-cyan-500/35 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-200">
              {t('monitoringDashboard.liveSourceHint')}
          </div>
        )}
        {!isAllScope && trafficSource !== 'nodes' && (
          <div className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              {t('monitoringDashboard.singleServerFallbackHint')}
          </div>
        )}
        {liveTrafficError && (
          <div className="rounded-lg border border-rose-500/45 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
              {liveTrafficError}
          </div>
        )}
        {showingLiveSnapshotFallback && (
          <div className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              {t('monitoringDashboard.liveSnapshotFallbackHint')}
          </div>
        )}
        <section className={chartCardClass}>
          <div className="mb-4 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <h3 className="text-sm font-medium uppercase tracking-[0.14em] text-cyan-300">{t('monitoringDashboard.adguardTitle')}</h3>
            </div>
            <button className={primaryButtonClass} onClick={collectAdguardNow} disabled={adguardLoading}>
              {adguardLoading ? t('monitoringDashboard.collecting') : t('monitoringDashboard.collectNow')}
            </button>
          </div>

            {adguardError && (
              <div className="mb-4 rounded-lg border border-rose-500/45 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
                {adguardError}
              </div>
            )}

            <div className="mb-5 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
              {[
                { label: t('monitoringDashboard.sources'), value: `${adguardOverview?.summary?.sources_online || 0}/${adguardOverview?.summary?.sources_total || 0}`, tone: 'text-slate-100' },
                { label: t('monitoringDashboard.queries'), value: Math.round(adguardOverview?.summary?.queries_total || 0).toLocaleString(), tone: stylePreset === '3' ? 'text-slate-100' : 'text-cyan-300' },
                { label: t('monitoringDashboard.blockRate'), value: `${(adguardOverview?.summary?.blocked_rate || 0).toFixed(2)}%`, tone: 'text-amber-300' },
                { label: t('monitoringDashboard.latency'), value: `${(adguardOverview?.summary?.avg_latency_ms || 0).toFixed(1)} ms`, tone: 'text-emerald-300' },
                { label: t('monitoringDashboard.cacheHit'), value: `${(adguardOverview?.summary?.cache_hit_ratio || 0).toFixed(2)}%`, tone: stylePreset === '3' ? 'text-slate-100' : 'text-cyan-300' },
                { label: t('monitoringDashboard.upstreamErrors'), value: Math.round(adguardOverview?.summary?.upstream_errors || 0).toLocaleString(), tone: 'text-rose-300' },
              ].map((item) => (
                <article key={item.label} className={subtlePanelClass}>
                  <div className="px-4 py-3">
                    <div className={sectionTitleClass}>{item.label}</div>
                    <strong className={cn('mt-2 block font-mono tabular-nums whitespace-nowrap text-sm font-medium', item.tone)}>{item.value}</strong>
                  </div>
                </article>
              ))}
            </div>

            <div className="mb-5 grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-3">
              {stackCards.map((card) => {
                const tone = gaugeTone(card.percent);
                return (
                  <article key={card.label} className={chartCardClass}>
                    <div className="flex items-center justify-between gap-3">
                      <span className={sectionTitleClass}>{card.label}</span>
                      <span className={cn('font-mono tabular-nums whitespace-nowrap text-xs font-medium', tone.text)}>{card.percent}%</span>
                    </div>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <strong className={cn(metricValueClass, toneClass(card.ok))}>{card.value}</strong>
                    </div>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#0a0e1a]">
                      <div className={cn('h-full rounded-full bg-gradient-to-r', tone.fill)} style={{ width: `${card.percent}%` }} />
                    </div>
                  </article>
                );
              })}
            </div>
            <div className="mb-5 flex items-center justify-between rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-3">
              <span className={sectionTitleClass}>{t('monitoringDashboard.promUp')}</span>
              <strong className={metricValueClass}>{Math.round(Number(stackStatus?.prometheus_metrics?.up_sum || 0))}</strong>
            </div>

            {!!(adguardHistory?.series || []).length && (
              <div className="mb-5 grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="lg:col-span-2">
                  <div className={chartCardClass}>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <h6 className="mb-0 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('monitoringDashboard.adguardQpsTitle')}</h6>
                      <span className="font-mono tabular-nums whitespace-nowrap text-[11px] text-slate-500">
                        Î”queries: {Math.round(adguardHistory?.summary?.queries_delta || 0).toLocaleString()} | QPS: {(adguardHistory?.summary?.queries_per_sec || 0).toFixed(3)}
                      </span>
                    </div>
                    <div style={{ height: 220 }}>
                      <Line data={adguardQpsData} options={chartOptions} />
                    </div>
                  </div>
                </div>
                <div>
                  <div className={chartCardClass}>
                    <h6 className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('monitoringDashboard.adguardBlockRateTitle')}</h6>
                    <div style={{ height: 220 }}>
                      <Line data={adguardBlockRateData} options={chartOptions} />
                    </div>
                  </div>
                </div>
                <div>
                  <div className={chartCardClass}>
                    <h6 className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('monitoringDashboard.adguardLatencyTitle')}</h6>
                    <div style={{ height: 220 }}>
                      <Line data={adguardLatencyData} options={chartOptions} />
                    </div>
                  </div>
                </div>
              </div>
            )}

            <section className="mb-5">
              <div className="hidden min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 lg:block">
                <div className="min-w-0 overflow-x-auto">
                  <table className="w-full min-w-[980px] table-fixed border-collapse text-left text-sm">
                    <thead className="bg-[#0a0e1a] text-[10px] uppercase tracking-wider text-slate-500">
                      <tr className="border-b border-cyan-500/20">
                        <th className="px-4 py-3">{t('monitoringDashboard.source')}</th>
                        <th className="px-4 py-3">{t('common.status')}</th>
                        <th className="px-4 py-3 text-right">{t('monitoringDashboard.queries')}</th>
                        <th className="px-4 py-3 text-right">{t('monitoringDashboard.blocked')}</th>
                        <th className="px-4 py-3 text-right">{t('monitoringDashboard.blockPercent')}</th>
                        <th className="px-4 py-3 text-right">{t('monitoringDashboard.latency')}</th>
                        <th className="px-4 py-3 text-right">{t('monitoringDashboard.cachePercent')}</th>
                        <th className="px-4 py-3 text-right">{t('monitoringDashboard.errors')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/50">
                      {(adguardOverview?.sources || []).map((s) => (
                        <tr key={s.source_id} className="hover:bg-cyan-400/5">
                          <td className="px-4 py-3 font-mono whitespace-nowrap text-slate-100">{s.source_name}</td>
                          <td className={cn('px-4 py-3 font-mono whitespace-nowrap', s.available ? 'text-emerald-300' : 'text-rose-300')}>{s.available ? t('nodes.online') : t('nodes.offline')}</td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums whitespace-nowrap">{Math.round(s.queries_total || 0).toLocaleString()}</td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums whitespace-nowrap">{Math.round(s.blocked_total || 0).toLocaleString()}</td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums whitespace-nowrap">{(s.blocked_rate || 0).toFixed(2)}%</td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums whitespace-nowrap">{(s.avg_latency_ms || 0).toFixed(1)} ms</td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums whitespace-nowrap">{(s.cache_hit_ratio || 0).toFixed(2)}%</td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums whitespace-nowrap">{Math.round(s.upstream_errors || 0).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="grid min-w-0 grid-cols-1 gap-2 lg:hidden">
                {(adguardOverview?.sources || []).map((s) => (
                  <article key={s.source_id} className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-sm font-medium text-slate-100">{s.source_name}</div>
                        <div className={cn('mt-1 font-mono text-xs whitespace-nowrap', s.available ? 'text-emerald-300' : 'text-rose-300')}>{s.available ? t('nodes.online') : t('nodes.offline')}</div>
                      </div>
                      <div className="text-right font-mono tabular-nums whitespace-nowrap text-xs text-slate-400">{(s.blocked_rate || 0).toFixed(2)}%</div>
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                      <div className="flex items-center justify-between rounded-md bg-[#0f1420] px-3 py-2"><span className="text-slate-500">{t('monitoringDashboard.queries')}</span><span className={compactMetricClass}>{Math.round(s.queries_total || 0).toLocaleString()}</span></div>
                      <div className="flex items-center justify-between rounded-md bg-[#0f1420] px-3 py-2"><span className="text-slate-500">{t('monitoringDashboard.blocked')}</span><span className={compactMetricClass}>{Math.round(s.blocked_total || 0).toLocaleString()}</span></div>
                      <div className="flex items-center justify-between rounded-md bg-[#0f1420] px-3 py-2"><span className="text-slate-500">{t('monitoringDashboard.latency')}</span><span className={compactMetricClass}>{(s.avg_latency_ms || 0).toFixed(1)} ms</span></div>
                      <div className="flex items-center justify-between rounded-md bg-[#0f1420] px-3 py-2"><span className="text-slate-500">{t('monitoringDashboard.cachePercent')}</span><span className={compactMetricClass}>{(s.cache_hit_ratio || 0).toFixed(2)}%</span></div>
                    </div>
                  </article>
                ))}
                {!(adguardOverview?.sources || []).length && (
                  <div className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-3 text-sm text-slate-500">{t('monitoringDashboard.noAdguardData')}</div>
                )}
              </div>
            </section>

            <div className="mb-5 grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
              <div className={chartCardClass}>
                <h6 className="mb-3 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('monitoringDashboard.topBlockedDomains')}</h6>
                <div className="mb-3 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-[180px_minmax(0,1fr)_110px]">
                  <select className={selectClass} value={blockedSourceFilter} onChange={(e) => setBlockedSourceFilter(e.target.value)}>
                    <option value="all">{t('monitoringDashboard.allSources')}</option>
                    {(adguardOverview?.sources || []).map((s) => (
                      <option key={s.source_id} value={String(s.source_id)}>{s.source_name}</option>
                    ))}
                  </select>
                  <input
                    className={inputClass}
                    placeholder={t('monitoringDashboard.searchDomainPlaceholder')}
                    value={blockedSearch}
                    onChange={(e) => setBlockedSearch(e.target.value)}
                  />
                  <select className={selectClass} value={String(blockedShowCount)} onChange={(e) => setBlockedShowCount(Number(e.target.value))}>
                    <option value="10">10</option>
                    <option value="25">25</option>
                    <option value="50">50</option>
                    <option value="100">100</option>
                  </select>
                </div>
                <div className="max-h-[360px] overflow-x-auto rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-2">
                <ul className="space-y-2">
                  {topBlockedDomains.map((it) => (
                    <li key={it.name} className="flex min-w-0 items-center justify-between gap-3 rounded-md bg-[#0f1420] px-3 py-2">
                      <span className="truncate font-mono text-sm text-slate-200">{it.name}</span>
                      <strong className={compactMetricClass}>{it.count}</strong>
                    </li>
                  ))}
                  {!topBlockedDomains.length && (
                    <li className="rounded-md bg-[#0f1420] px-3 py-2 text-sm text-slate-500">
                      {t('monitoringDashboard.noDataYet')}
                    </li>
                  )}
                </ul>
                </div>
              </div>
              <div className={chartCardClass}>
                <h6 className="mb-3 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('monitoringDashboard.topClients')}</h6>
                <div className="max-h-[360px] overflow-x-auto rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-2">
                <ul className="space-y-2">
                  {topClients.map((it) => (
                    <li key={it.name} className="flex min-w-0 items-center justify-between gap-3 rounded-md bg-[#0f1420] px-3 py-2">
                      <span className="truncate font-mono text-sm text-slate-200">{it.name}</span>
                      <strong className={compactMetricClass}>{it.count}</strong>
                    </li>
                  ))}
                  {!topClients.length && (
                    <li className="rounded-md bg-[#0f1420] px-3 py-2 text-sm text-slate-500">
                      {t('monitoringDashboard.noDataYet')}
                    </li>
                  )}
                </ul>
                </div>
              </div>
            </div>

            <div className="mb-4 border-t border-cyan-500/20 pt-4">
            <h6 className="mb-3 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">
              {editingAdguardSourceId === null ? t('monitoringDashboard.addAdguardSource') : t('common.edit')}
            </h6>
            <div className="grid min-w-0 grid-cols-1 gap-2 lg:grid-cols-[1fr_1.4fr_1fr_1fr_1fr_auto_auto]">
                <input
                  className={inputClass}
                  placeholder={t('common.name')}
                  value={adguardForm.name}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, name: e.target.value }))}
                />
                <input
                  className={inputClass}
                  placeholder={t('monitoringDashboard.adminUrl')}
                  value={adguardForm.admin_url}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, admin_url: e.target.value }))}
                />
                <input
                  className={inputClass}
                  placeholder={t('monitoringDashboard.dnsUrlOptional')}
                  value={adguardForm.dns_url}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, dns_url: e.target.value }))}
                />
                <input
                  className={inputClass}
                  placeholder={t('auth.username')}
                  value={adguardForm.username}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, username: e.target.value }))}
                />
                <input
                  className={inputClass}
                  type="password"
                  placeholder={t('auth.password')}
                  value={adguardForm.password}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, password: e.target.value }))}
                />
                <label className="inline-flex h-9 items-center gap-2 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={adguardForm.enabled}
                    onChange={(e) => setAdguardForm((s) => ({ ...s, enabled: e.target.checked }))}
                  />
                  {t('common.enabled')}
                </label>
                <button
                  className={primaryButtonClass}
                  onClick={() => void saveAdguardSource()}
                  disabled={adguardLoading}
                >
                  {editingAdguardSourceId === null ? t('common.add') : t('common.save')}
                </button>
                {editingAdguardSourceId !== null && (
                  <button className={secondaryButtonClass} onClick={resetAdguardForm} disabled={adguardLoading}>
                    {t('common.cancel')}
                  </button>
                )}
            </div>
            <label className="mt-2 inline-flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={adguardForm.verify_tls}
                onChange={(e) => setAdguardForm((s) => ({ ...s, verify_tls: e.target.checked }))}
              />
              {t('monitoringDashboard.verifyTls', { defaultValue: 'verify TLS' })}
            </label>
            </div>
            {!!adguardSources.length && (
              <div className="space-y-2 text-xs text-slate-500">
                <div>{t('monitoringDashboard.sourcesConfigured', { sources: adguardSources.map((s) => s.name).join(', ') })}</div>
                <div className="grid min-w-0 grid-cols-1 gap-2 lg:grid-cols-2">
                  {adguardSources.map((source) => (
                    <div key={source.id} className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-xs text-slate-200" title={source.name}>{source.name}</div>
                        <div className="mt-0.5 truncate font-mono text-[11px] text-slate-500" title={source.admin_url}>{source.admin_url}</div>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        <button className={secondaryButtonClass} type="button" onClick={() => editAdguardSource(source)} disabled={adguardLoading}>
                          {t('common.edit')}
                        </button>
                        <button
                          className={`${secondaryButtonClass} border-rose-400/30 text-rose-200 hover:border-rose-300/50 hover:text-rose-100`}
                          type="button"
                          onClick={() => void deleteAdguardSource(source)}
                          disabled={adguardLoading}
                        >
                          {t('common.delete')}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
        </section>

        <section className={chartCardClass}>
            <h6 className="mb-3 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">CPU <span className="font-mono tabular-nums whitespace-nowrap text-slate-500">({selectedNodeName})</span></h6>
            <div style={{ height: 260 }}>
              {loadingHistory && !(isAllScope ? allScopeLabels.length : labels.length) ? renderChartSkeleton() : <Line data={cpuData} options={chartOptions} />}
            </div>
        </section>
        <section className={chartCardClass}>
            <h6 className="mb-3 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('monitoringDashboard.onlineClientsChart', { node: selectedNodeName })}</h6>
            <div style={{ height: 260 }}>
              {loadingHistory && !(isAllScope ? allScopeLabels.length : labels.length) ? renderChartSkeleton() : <Line data={onlineData} options={chartOptions} />}
            </div>
        </section>
        <section className={chartCardClass}>
            <h6 className="mb-3 text-xs font-medium uppercase tracking-[0.14em] text-slate-300">
              {t('monitoringDashboard.trafficConsumptionTitle', { label: trafficConsumptionLabel, node: selectedNodeName, mode: trafficModeLabel, source: trafficSourceLabel, step: effectiveTrafficStepSec, smoothing: trafficSmoothingLabel })}
            </h6>
            <div style={{ height: 260 }}>
              {loadingHistory && !trafficData.labels.length ? (
                renderChartSkeleton()
              ) : renderTrafficAsBars ? (
                <Bar data={trafficData} options={trafficChartOptions as any} />
              ) : (
                <Line data={trafficData} options={trafficChartOptions} />
              )}
            </div>
        </section>
      </div>
    </div>
  );
};
