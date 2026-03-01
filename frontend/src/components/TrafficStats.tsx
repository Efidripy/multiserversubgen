import React, { useState, useEffect } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
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
  inbound_id: number;
}

export const TrafficStats: React.FC = () => {
  const { colors } = useTheme();
  const [trafficData, setTrafficData] = useState<TrafficData[]>([]);
  const [onlineClients, setOnlineClients] = useState<OnlineClient[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [groupBy, setGroupBy] = useState<'client' | 'inbound' | 'node'>('client');
  const [topN, setTopN] = useState(10);
  const [trafficSortField, setTrafficSortField] = useState<'name' | 'download' | 'total'>('download');
  const [trafficSortDir, setTrafficSortDir] = useState<'asc' | 'desc'>('desc');
  const [onlineSortField, setOnlineSortField] = useState<'email' | 'node' | 'inbound'>('email');
  const [onlineSortDir, setOnlineSortDir] = useState<'asc' | 'desc'>('asc');

  useEffect(() => {
    loadTrafficStats();
    loadOnlineClients();
  }, [groupBy]);

  useEffect(() => {
    const timer = setInterval(() => {
      loadTrafficStats();
      loadOnlineClients();
    }, 60000);
    return () => clearInterval(timer);
  }, [groupBy]);

  const loadTrafficStats = async () => {
    setLoading(true);
    setError('');

    try {
      const res = await api.get('/v1/traffic/stats', {
        auth: getAuth(),
        params: { group_by: groupBy },
      });
      const statsObj: Record<string, { up: number; down: number; total: number }> = res.data?.stats || {};
      const parsed: TrafficData[] = Object.entries(statsObj).map(([key, s]) => {
        if (groupBy === 'node') {
          return {
            email: key,
            node_name: key,
            upload: s.up || 0,
            download: s.down || 0,
            total: (s.total || 0) === 0 ? (s.up || 0) + (s.down || 0) : (s.total || 0),
          };
        }
        if (groupBy === 'inbound') {
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
      setTrafficData(parsed);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load traffic stats');
    } finally {
      setLoading(false);
    }
  };

  const loadOnlineClients = async () => {
    try {
      const res = await api.get('/v1/clients/online', { auth: getAuth() });
      const items: Array<{ email: string; node?: string; node_name?: string; inbound_id?: number }> =
        res.data?.online_clients || [];
      setOnlineClients(
        items.map((c) => ({
          email: c.email,
          node_name: c.node_name || c.node || 'unknown',
          inbound_id: c.inbound_id || 0,
        }))
      );
    } catch (err: any) {
      console.error('Failed to load online clients:', err);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 GB';
    const gb = bytes / 1073741824;
    return gb.toFixed(2) + ' GB';
  };

  const compareText = (a: string, b: string) =>
    a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });
  const trafficSortFactor = trafficSortDir === 'asc' ? 1 : -1;
  const onlineSortFactor = onlineSortDir === 'asc' ? 1 : -1;

  const sortedTraffic = [...trafficData]
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
      const byTotal = a.total - b.total;
      if (byTotal !== 0) return byTotal * trafficSortFactor;
      if (byName !== 0) return byName;
      if (byNode !== 0) return byNode;
      return a.download - b.download;
    })
    .slice(0, topN);

  const sortedOnlineClients = [...onlineClients].sort((a, b) => {
    const byEmail = compareText(a.email, b.email);
    const byNode = compareText(a.node_name, b.node_name);
    const byInbound = a.inbound_id - b.inbound_id;

    if (onlineSortField === 'email') {
      if (byEmail !== 0) return byEmail * onlineSortFactor;
      if (byNode !== 0) return byNode * onlineSortFactor;
      return byInbound * onlineSortFactor;
    }
    if (onlineSortField === 'node') {
      if (byNode !== 0) return byNode * onlineSortFactor;
      if (byEmail !== 0) return byEmail * onlineSortFactor;
      return byInbound * onlineSortFactor;
    }
    if (byInbound !== 0) return byInbound * onlineSortFactor;
    if (byEmail !== 0) return byEmail;
    return byNode;
  });

  // Top Clients Bar Chart
  const topClientsData = {
    labels: sortedTraffic.map(d => d.email || d.node_name || 'Unknown'),
    datasets: [
      {
        label: 'Download (GB)',
        data: sortedTraffic.map(d => (d.download / 1073741824).toFixed(2)),
        backgroundColor: colors.accent + 'CC',
        borderColor: colors.accent,
        borderWidth: 1.2,
        borderRadius: 10,
        hoverBackgroundColor: colors.accent,
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
          color: colors.text.primary,
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
        backgroundColor: 'rgba(8, 17, 32, 0.96)',
        borderColor: 'rgba(125, 211, 252, 0.45)',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#bae6fd',
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
          color: colors.text.secondary,
          font: {
            size: 10,
            weight: 600 as const,
          }
        },
        grid: {
          color: colors.border + '55'
        }
      },
      y: {
        ticks: {
          color: colors.text.secondary,
          font: {
            weight: 600 as const,
          }
        },
        grid: {
          color: colors.border + '55'
        }
      }
    }
  };

  // Traffic Distribution Pie Chart
  const totalDownload = trafficData.reduce((sum, d) => sum + d.download, 0);
  const totalTraffic = trafficData.reduce((sum, d) => sum + d.total, 0);

  return (
    <div className="traffic-stats">
      <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0" style={{ color: colors.accent }}>Traffic Statistics</h5>
          <div>
            <button
              className="btn btn-sm"
              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
              onClick={() => {
                loadTrafficStats();
                loadOnlineClients();
              }}
              disabled={loading}
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
            {error}
          </div>
        )}

        {/* Filters */}
        <div className="row g-2 mb-3">
          <div className="col-md-4">
            <label className="form-label small" style={{ color: colors.text.secondary }}>Group By</label>
            <select
              className="form-select form-select-sm"
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value as any)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="client">Client (Email)</option>
              <option value="inbound">Inbound</option>
              <option value="node">Node (Server)</option>
            </select>
          </div>
          <div className="col-md-4">
            <label className="form-label small" style={{ color: colors.text.secondary }}>Show Top</label>
            <select
              className="form-select form-select-sm"
              value={topN}
              onChange={(e) => setTopN(parseInt(e.target.value))}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="5">5</option>
              <option value="10">10</option>
              <option value="20">20</option>
              <option value="50">50</option>
            </select>
          </div>
          <div className="col-md-2">
            <label className="form-label small" style={{ color: colors.text.secondary }}>Sort Top by</label>
            <select
              className="form-select form-select-sm"
              value={trafficSortField}
              onChange={(e) => setTrafficSortField(e.target.value as 'name' | 'download' | 'total')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="download">Download</option>
              <option value="total">Total</option>
              <option value="name">Name</option>
            </select>
          </div>
          <div className="col-md-2">
            <label className="form-label small" style={{ color: colors.text.secondary }}>Direction</label>
            <select
              className="form-select form-select-sm"
              value={trafficSortDir}
              onChange={(e) => setTrafficSortDir(e.target.value as 'asc' | 'desc')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="asc">Asc</option>
              <option value="desc">Desc</option>
            </select>
          </div>
        </div>
      </div>

      {/* Stats Summary */}
      <div className="row mb-3">
          <div className="col-md-4">
            <div className="card kpi-card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="small" style={{ color: colors.text.secondary }}>Total Download</div>
              <h4 style={{ color: colors.accent }}>{formatBytes(totalDownload)}</h4>
            </div>
          </div>
          <div className="col-md-4">
            <div className="card kpi-card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="small" style={{ color: colors.text.secondary }}>Total Traffic</div>
              <h4 style={{ color: colors.info }}>{formatBytes(totalTraffic)}</h4>
            </div>
          </div>
          <div className="col-md-4">
            <div className="card kpi-card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="small" style={{ color: colors.text.secondary }}>Online Clients</div>
              <h4 style={{ color: colors.warning }}>{onlineClients.length}</h4>
            </div>
          </div>
      </div>

      {/* Charts */}
      <div className="row mb-3">
        <div className="col-12">
          <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <h6 className="mb-3" style={{ color: colors.text.primary }}>
              Top {topN} by {groupBy === 'client' ? 'Client' : groupBy === 'inbound' ? 'Inbound' : 'Server'}
            </h6>
            <div style={{ height: '400px' }}>
              {loading ? (
                <div className="d-flex justify-content-center align-items-center h-100">
                  <div className="spinner-border"></div>
                </div>
              ) : (
                <Bar data={topClientsData} options={chartOptions} />
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Online Clients */}
      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3 gap-2">
          <h6 className="mb-0" style={{ color: colors.text.primary }}>Online Clients ({onlineClients.length})</h6>
          <div className="d-flex gap-2">
            <select
              className="form-select form-select-sm"
              value={onlineSortField}
              onChange={(e) => setOnlineSortField(e.target.value as 'email' | 'node' | 'inbound')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, minWidth: 130 }}
            >
              <option value="email">Sort: Email</option>
              <option value="node">Sort: Node</option>
              <option value="inbound">Sort: Inbound ID</option>
            </select>
            <select
              className="form-select form-select-sm"
              value={onlineSortDir}
              onChange={(e) => setOnlineSortDir(e.target.value as 'asc' | 'desc')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, minWidth: 90 }}
            >
              <option value="asc">Asc</option>
              <option value="desc">Desc</option>
            </select>
          </div>
        </div>
        {onlineClients.length === 0 ? (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>No clients online</p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-hover" style={{ color: colors.text.primary }}>
              <thead>
                <tr style={{ borderColor: colors.border }}>
                  <th style={{ color: colors.text.secondary }}>Email</th>
                  <th style={{ color: colors.text.secondary }}>Node</th>
                  <th style={{ color: colors.text.secondary }}>Inbound ID</th>
                </tr>
              </thead>
              <tbody>
                {sortedOnlineClients.map((client, idx) => (
                  <tr key={idx} style={{ borderColor: colors.border }}>
                    <td>
                      <span style={{ color: colors.success }}>● </span>
                      <strong style={{ color: colors.text.primary }}>{client.email}</strong>
                    </td>
                    <td>
                      <span className="badge" style={{ backgroundColor: colors.bg.tertiary, color: colors.text.primary }}>
                        {client.node_name}
                      </span>
                    </td>
                    <td style={{ color: colors.text.secondary }}>{client.inbound_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Top Traffic Table */}
      <div className="card p-3 mt-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <h6 className="mb-3" style={{ color: colors.text.primary }}>
          Top {topN} Traffic Usage
        </h6>
        {loading ? (
          <div className="text-center py-3"><div className="spinner-border spinner-border-sm"></div></div>
        ) : sortedTraffic.length === 0 ? (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>No traffic data available</p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-hover" style={{ color: colors.text.primary }}>
              <thead>
                <tr style={{ borderColor: colors.border }}>
                  <th style={{ color: colors.text.secondary }}>#</th>
                  <th style={{ color: colors.text.secondary }}>
                    {groupBy === 'client' ? 'Email' : groupBy === 'inbound' ? 'Inbound' : 'Node'}
                  </th>
                  <th style={{ color: colors.text.secondary }}>Download</th>
                  <th style={{ color: colors.text.secondary }}>Total</th>
                </tr>
              </thead>
              <tbody>
                {sortedTraffic.map((item, idx) => (
                  <tr key={idx} style={{ borderColor: colors.border }}>
                    <td style={{ color: colors.text.secondary }}>{idx + 1}</td>
                    <td>
                      <strong style={{ color: colors.text.primary }}>
                        {item.email || item.node_name || 'Unknown'}
                      </strong>
                      {item.protocol && (
                        <span className="badge ms-2" style={{ backgroundColor: colors.accent }}>
                          {item.protocol.toUpperCase()}
                        </span>
                      )}
                    </td>
                    <td style={{ color: colors.accent }}>{formatBytes(item.download)}</td>
                    <td>
                      <strong style={{ color: colors.info }}>{formatBytes(item.total)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
