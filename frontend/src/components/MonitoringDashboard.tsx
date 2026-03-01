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

  useEffect(() => {
    loadNodes().catch((err: any) => {
      setError(err?.response?.data?.detail || 'Failed to load nodes');
    });
    loadLatestSnapshot();
    loadDepsHealth();
  }, []);

  useEffect(() => {
    loadHistory(selectedScope, rangeSec);
  }, [selectedScope, rangeSec, nodes.length]);

  useEffect(() => {
    const timer = setInterval(() => {
      loadHistory(selectedScope, rangeSec);
      loadLatestSnapshot();
      loadDepsHealth();
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
