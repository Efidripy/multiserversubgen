import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import api from '../api';
import { getAuth } from '../auth';
import { useTheme } from '../contexts/ThemeContext';
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

function getBucketSec(rangeSec: number, preferredStepSec?: number): number {
  if (preferredStepSec && preferredStepSec > 0) return preferredStepSec;
  if (rangeSec <= 3600) return 60;
  if (rangeSec <= 6 * 3600) return 120;
  if (rangeSec <= 24 * 3600) return 300;
  return 900;
}

function buildUsageFromCumulative(points: Array<number | null>): Array<number | null> {
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

function smoothSeries(values: Array<number | null>, mode: TrafficSmoothing): Array<number | null> {
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

function buildTrafficUsageSeries(points: Array<HistoryPoint | null>): Array<number | null> {
  let prevTotal: number | null = null;
  return points.map((point) => {
    if (!point) return null;
    const curTotal = Number(point.traffic_total || 0);
    if (prevTotal === null) {
      prevTotal = curTotal;
      return 0;
    }
    let delta = curTotal - prevTotal;
    // If node counter has reset, treat current total as usage since reset.
    if (delta < 0) {
      delta = curTotal;
    }
    prevTotal = curTotal;
    return Math.max(0, delta);
  });
}

function buildBucketTrafficUsageSeries(
  perNode: Array<{ nodeId: number; nodeName: string; points: Array<HistoryPoint | null>; bucketsRaw: Map<number, HistoryPoint[]> }>,
  buckets: number[]
): Array<number | null> {
  return buckets.map((bucketTs) => {
    let totalUsage = 0;
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
      // Handle counter reset: if delta is negative, treat last total as the usage
      if (delta < 0) {
        delta = lastTotal;
      }
      totalUsage += Math.max(0, delta);
    }
    return totalUsage;
  });
}

function bucketizeAllNodesHistory(points: HistoryPoint[], rangeSec: number, preferredStepSec?: number): {
  buckets: number[];
  perNode: Array<{ nodeId: number; nodeName: string; points: Array<HistoryPoint | null>; bucketsRaw: Map<number, HistoryPoint[]> }>;
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
  const { colors, stylePreset, theme } = useTheme();

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
  const [adguardLoading, setAdguardLoading] = useState(false);
  const [adguardError, setAdguardError] = useState('');
  const realtimeRefreshRef = useRef(0);
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
          setError('Failed to load node history for all servers');
        }
      } else {
        const nodeId = Number(scope);
        const data = await fetchNodeHistory(nodeId, sinceSec, 2000);
        setHistory(data);
        setAllScopeHistory([]);
      }
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load node history');
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
      setAdguardError(err?.response?.data?.detail || 'Failed to load AdGuard overview');
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


  const collectAdguardNow = async () => {
    try {
      setAdguardLoading(true);
      await api.post('/v1/adguard/collect-now', {}, { auth: getAuth() });
      await Promise.all([loadAdguardOverview(), loadAdguardSources(), loadAdguardHistory(), loadStackStatus()]);
      setAdguardError('');
    } catch (err: any) {
      setAdguardError(err?.response?.data?.detail || 'Failed to collect AdGuard data');
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
  const trafficUnitPerIntervalLabel = `${trafficUnitLabel}/interval`;
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
            label: 'CPU %',
            data: effectiveHistory.map((p) => Number((p.cpu || 0).toFixed(2))),
            borderColor: colors.warning,
            backgroundColor: colors.warning + '33',
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
            label: 'Online clients',
            data: effectiveHistory.map((p) => Number(p.online_clients || 0)),
            borderColor: colors.accent,
            backgroundColor: colors.accent + '33',
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
              label: 'All servers usage',
              data: smoothTrafficSeries(
                buildBucketTrafficUsageSeries(trafficHistorySeries.perNode, trafficHistorySeries.buckets).map((bytes) =>
                  toTrafficUnit(Number(bytes || 0))
                )
              ),
              borderColor: colors.info,
              backgroundColor: colors.info + '44',
              borderWidth: 2.8,
              pointRadius: 0,
              pointHoverRadius: 4,
              spanGaps: true,
              ...trafficLineShape,
            },
            ...trafficHistorySeries.perNode.map((node, idx) => {
              const c = chartPalette[idx % chartPalette.length];
              const usageSeries = buildTrafficUsageSeries(node.points);
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
            label: `Traffic usage (${trafficUnitPerIntervalLabel})`,
            data: smoothTrafficSeries(buildTrafficUsageSeries(effectiveHistory).map((bytes) => toTrafficUnit(Number(bytes || 0)))),
            borderColor: colors.info,
            backgroundColor: colors.info + '33',
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
            label: `People usage (${trafficUnitPerIntervalLabel})`,
            data: smoothTrafficSeries(usage.map((v) => toTrafficUnit(v))),
            borderColor: colors.success,
            backgroundColor: colors.success + '33',
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
            label: `Inbound usage (${trafficUnitPerIntervalLabel})`,
            data: smoothTrafficSeries(usage.map((v) => toTrafficUnit(v))),
            borderColor: colors.warning,
            backgroundColor: colors.warning + '33',
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
            label: `All servers live usage (${trafficUnitPerIntervalLabel})`,
            data: smoothTrafficSeries(totalUsage.map((v) => toTrafficUnit(v))),
            borderColor: colors.info,
            backgroundColor: colors.info + '44',
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
          label: `${selectedNodeName} live usage (${trafficUnitPerIntervalLabel})`,
          data: smoothTrafficSeries(selectedUsage.map((v) => toTrafficUnit(v))),
          borderColor: colors.info,
          backgroundColor: colors.info + '33',
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
    trafficUnitPerIntervalLabel,
    chartPalette,
    nodes,
    trafficLineShape,
    trafficSmoothing,
    colors.info,
    colors.success,
    colors.warning,
  ]);

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: {
          color: colors.text.primary,
          usePointStyle: true,
          pointStyle: 'circle' as const,
          font: {
            size: 12,
            weight: 600 as const,
          },
        },
      },
      tooltip: {
        backgroundColor:
          theme === 'light'
            ? 'rgba(255, 255, 255, 0.98)'
            : stylePreset === '3'
            ? 'rgba(8, 8, 8, 0.96)'
            : 'rgba(8, 17, 32, 0.96)',
        borderColor:
          theme === 'light'
            ? 'rgba(148, 163, 184, 0.5)'
            : stylePreset === '3'
            ? 'rgba(255, 255, 255, 0.18)'
            : 'rgba(125, 211, 252, 0.45)',
        borderWidth: 1,
        titleColor: theme === 'light' ? '#0f172a' : stylePreset === '3' ? '#fafafa' : '#e2e8f0',
        bodyColor: theme === 'light' ? '#334155' : stylePreset === '3' ? '#d4d4d8' : '#bae6fd',
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
        hoverBorderColor: theme === 'light' ? '#1d4ed8' : stylePreset === '3' ? '#ffffff' : '#e0f2fe',
      },
    },
    scales: {
      x: {
        ticks: {
          color: colors.text.secondary,
          maxTicksLimit: 10,
          font: {
            weight: 600 as const,
          },
        },
        grid: { color: colors.border + '55' },
      },
      y: {
        ticks: {
          color: colors.text.secondary,
          font: {
            weight: 600 as const,
          },
        },
        grid: { color: colors.border + '55' },
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
            return `${datasetLabel}: ${y.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${trafficUnitPerIntervalLabel}`;
          },
          title: (items: any[]) => {
            const base = items?.[0]?.label || '';
            return `${base} • ${trafficModeLabel} • step ${effectiveTrafficStepSec}s • ${trafficSourceLabel} • ${trafficSmoothingLabel}`;
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
          callback: (value: any) => `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${trafficUnitPerIntervalLabel}`,
        },
      },
    },
  };

  const topBlockedDomains = useMemo(() => {
    const agg = new Map<string, number>();
    (adguardOverview?.sources || []).forEach((s) => {
      (s.top_blocked_domains || []).forEach((it) => {
        agg.set(it.name, (agg.get(it.name) || 0) + Number(it.count || 0));
      });
    });
    return Array.from(agg.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, count]) => ({ name, count }));
  }, [adguardOverview]);

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

  return (
    <div className="monitoring-panel panel-block" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
      <div className="monitoring-panel__header mb-3">
        <h4 className="mb-0" style={{ color: colors.text.primary }}>
          Monitoring
        </h4>
        <a
          className="btn btn-sm"
          href={grafanaUrl}
          target="_blank"
          rel="noreferrer"
          style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
        >
          Открыть Grafana
        </a>
      </div>

      {error && (
        <div className="alert mb-3" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
          {error}
        </div>
      )}

      <div className="row g-2 mb-3">
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Сервер
          </label>
          <ChoiceChips
            options={[
              { value: 'all', label: 'Все' },
              ...nodes.map((n) => ({ value: String(n.id), label: n.name })),
            ]}
            value={selectedScope}
            onChange={(value) => setSelectedScope(value)}
            colors={colors}
          />
        </div>
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Диапазон
          </label>
          <ChoiceChips
            options={RANGE_OPTIONS.map((range) => ({ value: range.value, label: range.label }))}
            value={rangeSec}
            onChange={(value) => setRangeSec(value)}
            colors={colors}
          />
        </div>
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Трафик
          </label>
          <ChoiceChips
            options={[
              { value: 'MB', label: 'MB' },
              { value: 'GB', label: 'GB' },
            ]}
            value={trafficUnit}
            onChange={(value) => setTrafficUnit(value as 'MB' | 'GB')}
            colors={colors}
          />
        </div>
        <div className="col-md-3 d-flex align-items-end">
          <button
            className="btn btn-sm w-100"
            style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
            onClick={() => {
              loadHistory(selectedScope, rangeSec);
              loadLatestSnapshot();
              loadDepsHealth();
              loadAdguardOverview();
              loadAdguardHistory();
              loadStackStatus();
            }}
            disabled={loadingHistory}
          >
            {loadingHistory ? 'Обновление...' : 'Обновить'}
          </button>
        </div>
      </div>

      <div className="row g-2 mb-3">
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Режим трафика
          </label>
          <ChoiceChips
            options={[
              { value: 'history', label: 'History' },
              { value: 'live', label: 'Live' },
            ]}
            value={trafficMode}
            onChange={(value) => setTrafficMode(value as TrafficMode)}
            colors={colors}
          />
        </div>
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Источник
          </label>
          <ChoiceChips
            options={[
              { value: 'nodes', label: 'Nodes' },
              { value: 'people', label: 'Люди' },
              { value: 'inbounds', label: 'Инбаунды' },
            ]}
            value={trafficSource}
            onChange={(value) => setTrafficSource(value as TrafficSource)}
            colors={colors}
          />
        </div>
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Шаг
          </label>
          <ChoiceChips
            options={TRAFFIC_STEP_OPTIONS.map((step) => ({ value: step.value, label: step.label }))}
            value={trafficStepSec}
            onChange={(value) => setTrafficStepSec(Number(value))}
            colors={colors}
          />
        </div>
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Стиль
          </label>
          <ChoiceChips
            options={[
              { value: 'stepped', label: 'Stepped' },
              { value: 'bars', label: 'Bars' },
              { value: 'smooth', label: 'Smooth' },
            ]}
            value={trafficVisualStyle}
            onChange={(value) => setTrafficVisualStyle(value as TrafficVisualStyle)}
            colors={colors}
          />
        </div>
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Сглаживание
          </label>
          <ChoiceChips
            options={[
              { value: 'raw', label: 'Raw' },
              { value: 'sma3', label: 'SMA-3' },
              { value: 'sma5', label: 'SMA-5' },
            ]}
            value={trafficSmoothing}
            onChange={(value) => setTrafficSmoothing(value as TrafficSmoothing)}
            colors={colors}
          />
        </div>
      </div>

      <div className="row g-2 mb-3">
        <div className="col-md-3">
          <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Collector</div>
            <strong style={{ color: depsHealth?.collector_running ? colors.success : colors.danger }}>
              {depsHealth?.collector_running ? 'running' : 'stopped'}
            </strong>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Redis</div>
            <strong style={{ color: depsHealth?.redis?.ok ? colors.success : colors.warning }}>
              {depsHealth?.redis?.enabled ? (depsHealth?.redis?.ok ? 'ok' : 'degraded') : 'disabled'}
            </strong>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>
              {isAllScope ? 'Nodes online' : 'Node status'}
            </div>
            <strong style={{ color: isAllScope ? colors.success : latestForSelected?.available ? colors.success : colors.danger }}>
              {isAllScope
                ? `${allNodesStatus.online}/${allNodesStatus.total}`
                : latestForSelected?.available
                ? 'online'
                : 'offline'}
            </strong>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>
              {isAllScope ? 'Online clients (all)' : 'Current online clients'}
            </div>
            <strong style={{ color: colors.accent }}>
              {isAllScope ? allNodesStatus.onlineClients : latestForSelected?.online_clients ?? 0}
            </strong>
          </div>
        </div>
      </div>

      <div className="row g-3">
        {trafficSource !== 'nodes' && (
          <div className="col-12">
            <div className="alert mb-0" style={{ backgroundColor: colors.info + '22', borderColor: colors.info, color: colors.info }}>
              Источник «Люди/Инбаунды» работает в live-режиме (исторические серии per-client/per-inbound сейчас не хранятся).
            </div>
          </div>
        )}
        {!isAllScope && trafficSource !== 'nodes' && (
          <div className="col-12">
            <div className="alert mb-0" style={{ backgroundColor: colors.warning + '22', borderColor: colors.warning, color: colors.warning }}>
              Для отдельного сервера включён fallback на source=Nodes (агрегация «Люди» корректна только для scope=All servers).
            </div>
          </div>
        )}
        {liveTrafficError && (
          <div className="col-12">
            <div className="alert mb-0" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
              {liveTrafficError}
            </div>
          </div>
        )}
        {showingLiveSnapshotFallback && (
          <div className="col-12">
            <div className="alert mb-0" style={{ backgroundColor: colors.warning + '22', borderColor: colors.warning, color: colors.warning }}>
              История пока пустая — отображается текущий live snapshot.
            </div>
          </div>
        )}
        <div className="col-12" style={{ order: 100 }}>
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
              <h6 className="mb-0" style={{ color: colors.text.primary }}>AdGuard DNS Monitoring</h6>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.info, borderColor: colors.info, color: colors.infoText }}
                onClick={collectAdguardNow}
                disabled={adguardLoading}
              >
                {adguardLoading ? 'Сбор...' : 'Собрать сейчас'}
              </button>
            </div>

            {adguardError && (
              <div className="alert mb-3" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
                {adguardError}
              </div>
            )}

            <div className="row g-2 mb-3">
              <div className="col-md-2">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Sources</div>
                  <strong style={{ color: colors.text.primary }}>{adguardOverview?.summary?.sources_online || 0}/{adguardOverview?.summary?.sources_total || 0}</strong>
                </div>
              </div>
              <div className="col-md-2">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Queries</div>
                  <strong style={{ color: stylePreset === '3' ? colors.text.primary : colors.accent }}>{Math.round(adguardOverview?.summary?.queries_total || 0).toLocaleString()}</strong>
                </div>
              </div>
              <div className="col-md-2">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Block rate</div>
                  <strong style={{ color: colors.warning }}>{(adguardOverview?.summary?.blocked_rate || 0).toFixed(2)}%</strong>
                </div>
              </div>
              <div className="col-md-2">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Latency</div>
                  <strong style={{ color: colors.success }}>{(adguardOverview?.summary?.avg_latency_ms || 0).toFixed(1)} ms</strong>
                </div>
              </div>
              <div className="col-md-2">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Cache hit</div>
                  <strong style={{ color: stylePreset === '3' ? colors.text.primary : colors.info }}>{(adguardOverview?.summary?.cache_hit_ratio || 0).toFixed(2)}%</strong>
                </div>
              </div>
              <div className="col-md-2">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Upstream errors</div>
                  <strong style={{ color: colors.danger }}>{Math.round(adguardOverview?.summary?.upstream_errors || 0).toLocaleString()}</strong>
                </div>
              </div>
            </div>

            <div className="row g-2 mb-3">
              <div className="col-md-3">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Prometheus</div>
                  <strong style={{ color: stackStatus?.services?.prometheus?.ok ? colors.success : colors.warning }}>
                    {stackStatus?.services?.prometheus?.ok ? 'online' : 'offline'}
                  </strong>
                </div>
              </div>
              <div className="col-md-3">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Loki</div>
                  <strong style={{ color: stackStatus?.services?.loki?.ok ? colors.success : colors.warning }}>
                    {stackStatus?.services?.loki?.ok ? 'online' : 'offline'}
                  </strong>
                </div>
              </div>
              <div className="col-md-3">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Grafana</div>
                  <strong style={{ color: stackStatus?.services?.grafana?.ok ? colors.success : colors.warning }}>
                    {stackStatus?.services?.grafana?.ok ? 'online' : 'offline'}
                  </strong>
                </div>
              </div>
              <div className="col-md-3">
                <div className="card kpi-card p-2" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="small" style={{ color: colors.text.secondary }}>Prom up</div>
                  <strong style={{ color: colors.text.primary }}>
                    {Math.round(Number(stackStatus?.prometheus_metrics?.up_sum || 0))}
                  </strong>
                </div>
              </div>
            </div>

            {!!(adguardHistory?.series || []).length && (
              <div className="row g-3 mb-3">
                <div className="col-12">
                  <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                    <div className="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
                      <h6 className="mb-0" style={{ color: colors.text.primary }}>AdGuard Queries/sec (per source)</h6>
                      <small style={{ color: colors.text.secondary }}>
                        Δqueries: {Math.round(adguardHistory?.summary?.queries_delta || 0).toLocaleString()} | QPS: {(adguardHistory?.summary?.queries_per_sec || 0).toFixed(3)}
                      </small>
                    </div>
                    <div style={{ height: 220 }}>
                      <Line data={adguardQpsData} options={chartOptions} />
                    </div>
                  </div>
                </div>
                <div className="col-md-6">
                  <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                    <h6 className="mb-2" style={{ color: colors.text.primary }}>AdGuard Block rate %</h6>
                    <div style={{ height: 220 }}>
                      <Line data={adguardBlockRateData} options={chartOptions} />
                    </div>
                  </div>
                </div>
                <div className="col-md-6">
                  <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                    <h6 className="mb-2" style={{ color: colors.text.primary }}>AdGuard Latency ms</h6>
                    <div style={{ height: 220 }}>
                      <Line data={adguardLatencyData} options={chartOptions} />
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div className="table-responsive mb-3">
              <table className="table table-sm align-middle mb-0" style={{ color: colors.text.primary }}>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Status</th>
                    <th>Queries</th>
                    <th>Blocked</th>
                    <th>Block %</th>
                    <th>Latency</th>
                    <th>Cache %</th>
                    <th>Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {(adguardOverview?.sources || []).map((s) => (
                    <tr key={s.source_id}>
                      <td>{s.source_name}</td>
                      <td style={{ color: s.available ? colors.success : colors.danger }}>{s.available ? 'online' : 'offline'}</td>
                      <td>{Math.round(s.queries_total || 0).toLocaleString()}</td>
                      <td>{Math.round(s.blocked_total || 0).toLocaleString()}</td>
                      <td>{(s.blocked_rate || 0).toFixed(2)}%</td>
                      <td>{(s.avg_latency_ms || 0).toFixed(1)} ms</td>
                      <td>{(s.cache_hit_ratio || 0).toFixed(2)}%</td>
                      <td>{Math.round(s.upstream_errors || 0).toLocaleString()}</td>
                    </tr>
                  ))}
                  {!(adguardOverview?.sources || []).length && (
                    <tr>
                      <td colSpan={8} style={{ color: colors.text.secondary }}>Нет данных AdGuard. Добавьте источник ниже и нажмите «Собрать сейчас».</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="row g-3 mb-2">
              <div className="col-md-6">
                <h6 style={{ color: colors.text.primary }}>Top blocked domains</h6>
                <ul className="list-group">
                  {topBlockedDomains.map((it) => (
                    <li key={it.name} className="list-group-item d-flex justify-content-between" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}>
                      <span>{it.name}</span>
                      <strong>{it.count}</strong>
                    </li>
                  ))}
                  {!topBlockedDomains.length && (
                    <li className="list-group-item" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.secondary }}>
                      Пока нет данных
                    </li>
                  )}
                </ul>
              </div>
              <div className="col-md-6">
                <h6 style={{ color: colors.text.primary }}>Top clients</h6>
                <ul className="list-group">
                  {topClients.map((it) => (
                    <li key={it.name} className="list-group-item d-flex justify-content-between" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}>
                      <span>{it.name}</span>
                      <strong>{it.count}</strong>
                    </li>
                  ))}
                  {!topClients.length && (
                    <li className="list-group-item" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.secondary }}>
                      Пока нет данных
                    </li>
                  )}
                </ul>
              </div>
            </div>

            <hr style={{ borderColor: colors.border }} />
            <h6 className="mb-2" style={{ color: colors.text.primary }}>Добавить источник AdGuard</h6>
            <div className="row g-2">
              <div className="col-md-2">
                <input
                  className="form-control form-control-sm"
                  placeholder="Name"
                  value={adguardForm.name}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, name: e.target.value }))}
                  style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}
                />
              </div>
              <div className="col-md-3">
                <input
                  className="form-control form-control-sm"
                  placeholder="Admin URL"
                  value={adguardForm.admin_url}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, admin_url: e.target.value }))}
                  style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}
                />
              </div>
              <div className="col-md-2">
                <input
                  className="form-control form-control-sm"
                  placeholder="DNS URL (optional)"
                  value={adguardForm.dns_url}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, dns_url: e.target.value }))}
                  style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}
                />
              </div>
              <div className="col-md-2">
                <input
                  className="form-control form-control-sm"
                  placeholder="Username"
                  value={adguardForm.username}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, username: e.target.value }))}
                  style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}
                />
              </div>
              <div className="col-md-2">
                <input
                  className="form-control form-control-sm"
                  type="password"
                  placeholder="Password"
                  value={adguardForm.password}
                  onChange={(e) => setAdguardForm((s) => ({ ...s, password: e.target.value }))}
                  style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}
                />
              </div>
              <div className="col-md-1 d-grid">
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.success, borderColor: colors.success, color: colors.successText }}
                  onClick={async () => {
                    try {
                      await api.post('/v1/adguard/sources', adguardForm, { auth: getAuth() });
                      setAdguardForm({
                        name: '',
                        admin_url: '',
                        dns_url: '',
                        username: '',
                        password: '',
                        verify_tls: true,
                        enabled: true,
                      });
                      await Promise.all([loadAdguardSources(), collectAdguardNow()]);
                    } catch (err: any) {
                      setAdguardError(err?.response?.data?.detail || 'Failed to add AdGuard source');
                    }
                  }}
                >
                  Add
                </button>
              </div>
            </div>
            {!!adguardSources.length && (
              <div className="small mt-2" style={{ color: colors.text.secondary }}>
                Sources configured: {adguardSources.map((s) => s.name).join(', ')}
              </div>
            )}
          </div>
        </div>

        <div className="col-12" style={{ order: 10 }}>
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <h6 style={{ color: colors.text.primary }}>CPU ({selectedNodeName})</h6>
            <div style={{ height: 260 }}>
              <Line data={cpuData} options={chartOptions} />
            </div>
          </div>
        </div>
        <div className="col-12" style={{ order: 20 }}>
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <h6 style={{ color: colors.text.primary }}>Online clients ({selectedNodeName})</h6>
            <div style={{ height: 260 }}>
              <Line data={onlineData} options={chartOptions} />
            </div>
          </div>
        </div>
        <div className="col-12" style={{ order: 30 }}>
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <h6 style={{ color: colors.text.primary }}>
              Traffic usage {trafficUnitPerIntervalLabel} ({selectedNodeName}) • {trafficModeLabel} • {trafficSourceLabel} • step {effectiveTrafficStepSec}s • {trafficSmoothingLabel}
            </h6>
            <div style={{ height: 260 }}>
              {renderTrafficAsBars ? (
                <Bar data={trafficData} options={trafficChartOptions as any} />
              ) : (
                <Line data={trafficData} options={trafficChartOptions} />
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
