import React, { useEffect, useMemo, useState } from 'react';
import api from '../api';
import { getAuth } from '../auth';
import { useTheme } from '../contexts/ThemeContext';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

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

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, lineGlowPlugin);

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

function buildGrafanaUrl(): string {
  const explicitPath = (import.meta.env.VITE_GRAFANA_PATH as string | undefined)?.trim();
  if (explicitPath) {
    const normalized = explicitPath.startsWith('/') ? explicitPath : `/${explicitPath}`;
    return `${window.location.origin}${normalized.replace(/\/$/, '')}/`;
  }

  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
  const legacyPath = base ? `${base}/grafana` : '/grafana';
  return `${window.location.origin}${legacyPath}/`;
}

const bytesToGb = (bytes: number) => bytes / (1024 * 1024 * 1024);
const CHART_PALETTE = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#06b6d4', '#e11d48', '#84cc16', '#f97316', '#14b8a6'];

function getBucketSec(rangeSec: number): number {
  if (rangeSec <= 3600) return 60;
  if (rangeSec <= 6 * 3600) return 120;
  if (rangeSec <= 24 * 3600) return 300;
  return 900;
}

function bucketizeAllNodesHistory(points: HistoryPoint[], rangeSec: number): {
  buckets: number[];
  perNode: Array<{ nodeId: number; nodeName: string; points: Array<HistoryPoint | null> }>;
} {
  const bucketSec = getBucketSec(rangeSec);

  // Keep only latest point per node in each bucket.
  const perNodeBucket = new Map<number, Map<number, HistoryPoint>>();
  for (const p of points) {
    const bucketTs = Math.floor(p.ts / bucketSec) * bucketSec;
    const nodeMap = perNodeBucket.get(p.node_id) || new Map<number, HistoryPoint>();
    const prev = nodeMap.get(bucketTs);
    if (!prev || p.ts > prev.ts) {
      nodeMap.set(bucketTs, { ...p, ts: bucketTs });
    }
    perNodeBucket.set(p.node_id, nodeMap);
  }

  const allBuckets = new Set<number>();
  for (const nodeMap of perNodeBucket.values()) {
    for (const ts of nodeMap.keys()) allBuckets.add(ts);
  }
  const buckets = Array.from(allBuckets).sort((a, b) => a - b);

  const perNode = Array.from(perNodeBucket.entries())
    .map(([nodeId, nodeMap]) => {
      const first = nodeMap.values().next().value as HistoryPoint | undefined;
      const nodeName = first?.node_name || `Node ${nodeId}`;
      return {
        nodeId,
        nodeName,
        points: buckets.map((ts) => nodeMap.get(ts) || null),
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
  const { colors } = useTheme();
  const grafanaUrl = buildGrafanaUrl();

  const [nodes, setNodes] = useState<NodeItem[]>([]);
  const [selectedScope, setSelectedScope] = useState<string>('all'); // "all" | node id as string
  const [rangeSec, setRangeSec] = useState<number>(24 * 3600);
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
  const [adguardForm, setAdguardForm] = useState({
    name: '',
    admin_url: '',
    dns_url: '',
    username: '',
    password: '',
    verify_tls: true,
    enabled: true,
  });

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
          setLoadingHistory(false);
          return;
        }
        const perNodeLimit = sinceSec >= 7 * 24 * 3600 ? 900 : 1200;
        const all = await Promise.all(nodes.map((n) => fetchNodeHistory(n.id, sinceSec, perNodeLimit)));
        setAllScopeHistory(all.flat());
        setHistory([]);
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

  const loadLatestSnapshot = async () => {
    try {
      const res = await api.get('/v1/snapshots/latest', { auth: getAuth() });
      setLatestSnapshotNodes((res.data?.nodes || []) as SnapshotNode[]);
    } catch {
      setLatestSnapshotNodes([]);
    }
  };

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

  useEffect(() => {
    const timer = setInterval(() => {
      loadHistory(selectedScope, rangeSec);
      loadLatestSnapshot();
      loadDepsHealth();
      loadAdguardOverview();
      loadAdguardHistory();
      loadStackStatus();
    }, 60_000);
    return () => clearInterval(timer);
  }, [selectedScope, rangeSec, nodes.length]);

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

  const labels = history.map((p) => formatTickLabel(p.ts, rangeSec));
  const allScopeSeries = useMemo(() => bucketizeAllNodesHistory(allScopeHistory, rangeSec), [allScopeHistory, rangeSec]);
  const allScopeLabels = allScopeSeries.buckets.map((ts) => formatTickLabel(ts, rangeSec));

  const cpuData = {
    labels: isAllScope ? allScopeLabels : labels,
    datasets: isAllScope
      ? allScopeSeries.perNode.map((node, idx) => {
          const c = CHART_PALETTE[idx % CHART_PALETTE.length];
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
            data: history.map((p) => Number((p.cpu || 0).toFixed(2))),
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
          const c = CHART_PALETTE[idx % CHART_PALETTE.length];
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
            data: history.map((p) => Number(p.online_clients || 0)),
            borderColor: colors.accent,
            backgroundColor: colors.accent + '33',
            borderWidth: 2.2,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 3,
          },
        ],
  };

  const trafficData = {
    labels: isAllScope ? allScopeLabels : labels,
    datasets: isAllScope
      ? allScopeSeries.perNode.map((node, idx) => {
          const c = CHART_PALETTE[idx % CHART_PALETTE.length];
          return {
            label: node.nodeName,
            data: node.points.map((p) => (p ? Number(bytesToGb(p.traffic_total || 0).toFixed(2)) : null)),
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
            label: 'Traffic total (GB)',
            data: history.map((p) => Number(bytesToGb(p.traffic_total || 0).toFixed(2))),
            borderColor: colors.info,
            backgroundColor: colors.info + '33',
            borderWidth: 2.2,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 3,
          },
        ],
  };

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
        backgroundColor: 'rgba(8, 17, 32, 0.96)',
        borderColor: 'rgba(125, 211, 252, 0.45)',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#bae6fd',
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
        hoverBorderColor: '#e0f2fe',
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
        const c = CHART_PALETTE[idx % CHART_PALETTE.length];
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
        const c = CHART_PALETTE[idx % CHART_PALETTE.length];
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
        const c = CHART_PALETTE[idx % CHART_PALETTE.length];
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
    <div className="monitoring-panel card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
      <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
        <h4 className="mb-0" style={{ color: colors.text.primary }}>
          Monitoring
        </h4>
        <a
          className="btn btn-sm"
          href={grafanaUrl}
          target="_blank"
          rel="noreferrer"
          style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#fff' }}
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
        <div className="col-md-4">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Сервер
          </label>
          <select
            className="form-select form-select-sm"
            value={selectedScope}
            onChange={(e) => setSelectedScope(e.target.value)}
            style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
          >
            <option value="all">Все серверы</option>
            {nodes.map((n) => (
              <option key={n.id} value={String(n.id)}>
                {n.name}
              </option>
            ))}
          </select>
        </div>
        <div className="col-md-4">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Диапазон
          </label>
          <select
            className="form-select form-select-sm"
            value={rangeSec}
            onChange={(e) => setRangeSec(Number(e.target.value))}
            style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
          >
            {RANGE_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
        <div className="col-md-4 d-flex align-items-end">
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
        <div className="col-12">
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
              <h6 className="mb-0" style={{ color: colors.text.primary }}>AdGuard DNS Monitoring</h6>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.info, borderColor: colors.info, color: '#fff' }}
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
                  <strong style={{ color: colors.accent }}>{Math.round(adguardOverview?.summary?.queries_total || 0).toLocaleString()}</strong>
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
                  <strong style={{ color: colors.info }}>{(adguardOverview?.summary?.cache_hit_ratio || 0).toFixed(2)}%</strong>
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
                  style={{ backgroundColor: colors.success, borderColor: colors.success, color: '#fff' }}
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

        <div className="col-12">
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <h6 style={{ color: colors.text.primary }}>CPU ({selectedNodeName})</h6>
            <div style={{ height: 260 }}>
              <Line data={cpuData} options={chartOptions} />
            </div>
          </div>
        </div>
        <div className="col-12">
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <h6 style={{ color: colors.text.primary }}>Online clients ({selectedNodeName})</h6>
            <div style={{ height: 260 }}>
              <Line data={onlineData} options={chartOptions} />
            </div>
          </div>
        </div>
        <div className="col-12">
          <div className="card p-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <h6 style={{ color: colors.text.primary }}>Traffic total ({selectedNodeName})</h6>
            <div style={{ height: 260 }}>
              <Line data={trafficData} options={chartOptions} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
