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

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

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

function getBucketSec(rangeSec: number): number {
  if (rangeSec <= 3600) return 60;
  if (rangeSec <= 6 * 3600) return 120;
  if (rangeSec <= 24 * 3600) return 300;
  return 900;
}

function aggregateAllNodesHistory(points: HistoryPoint[], rangeSec: number): HistoryPoint[] {
  const bucketSec = getBucketSec(rangeSec);

  // Keep only latest point per node in each bucket.
  const perNodeBucket = new Map<string, HistoryPoint>();
  for (const p of points) {
    const bucketTs = Math.floor(p.ts / bucketSec) * bucketSec;
    const key = `${bucketTs}:${p.node_id}`;
    const prev = perNodeBucket.get(key);
    if (!prev || p.ts > prev.ts) {
      perNodeBucket.set(key, { ...p, ts: bucketTs });
    }
  }

  // Aggregate all nodes inside each bucket.
  const bucketMap = new Map<number, { cpuSum: number; nodeCount: number; onlineSum: number; trafficSum: number }>();
  for (const p of perNodeBucket.values()) {
    const curr = bucketMap.get(p.ts) || { cpuSum: 0, nodeCount: 0, onlineSum: 0, trafficSum: 0 };
    curr.cpuSum += Number(p.cpu || 0);
    curr.nodeCount += 1;
    curr.onlineSum += Number(p.online_clients || 0);
    curr.trafficSum += Number(p.traffic_total || 0);
    bucketMap.set(p.ts, curr);
  }

  return Array.from(bucketMap.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([ts, v]) => ({
      ts,
      node_id: 0,
      node_name: 'ALL',
      available: 1,
      xray_running: 1,
      cpu: v.nodeCount > 0 ? v.cpuSum / v.nodeCount : 0,
      online_clients: v.onlineSum,
      traffic_total: v.trafficSum,
      poll_ms: 0,
    }));
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
        const merged = all.flat();
        setHistory(aggregateAllNodesHistory(merged, sinceSec));
      } else {
        const nodeId = Number(scope);
        const data = await fetchNodeHistory(nodeId, sinceSec, 2000);
        setHistory(data);
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

  const cpuData = {
    labels,
    datasets: [
      {
        label: isAllScope ? 'Avg CPU % (all nodes)' : 'CPU %',
        data: history.map((p) => Number((p.cpu || 0).toFixed(2))),
        borderColor: colors.warning,
        backgroundColor: colors.warning + '33',
        tension: 0.25,
        pointRadius: 0,
      },
    ],
  };

  const onlineData = {
    labels,
    datasets: [
      {
        label: isAllScope ? 'Online clients (sum)' : 'Online clients',
        data: history.map((p) => Number(p.online_clients || 0)),
        borderColor: colors.accent,
        backgroundColor: colors.accent + '33',
        tension: 0.25,
        pointRadius: 0,
      },
    ],
  };

  const trafficData = {
    labels,
    datasets: [
      {
        label: isAllScope ? 'Traffic total GB (sum)' : 'Traffic total (GB)',
        data: history.map((p) => Number(bytesToGb(p.traffic_total || 0).toFixed(2))),
        borderColor: colors.info,
        backgroundColor: colors.info + '33',
        tension: 0.25,
        pointRadius: 0,
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
        },
      },
    },
    scales: {
      x: {
        ticks: { color: colors.text.secondary, maxTicksLimit: 10 },
        grid: { color: colors.border },
      },
      y: {
        ticks: { color: colors.text.secondary },
        grid: { color: colors.border },
      },
    },
  };

  return (
    <div className="monitoring-panel card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
      <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
        <h4 className="mb-0" style={{ color: colors.text.primary }}>
          📉 Monitoring
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
            {loadingHistory ? '⏳ Обновление...' : '🔄 Обновить'}
          </button>
        </div>
      </div>

      <div className="row g-2 mb-3">
        <div className="col-md-3">
          <div className="card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Collector</div>
            <strong style={{ color: depsHealth?.collector_running ? colors.success : colors.danger }}>
              {depsHealth?.collector_running ? 'running' : 'stopped'}
            </strong>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Redis</div>
            <strong style={{ color: depsHealth?.redis?.ok ? colors.success : colors.warning }}>
              {depsHealth?.redis?.enabled ? (depsHealth?.redis?.ok ? 'ok' : 'degraded') : 'disabled'}
            </strong>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
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
          <div className="card p-2" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
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

