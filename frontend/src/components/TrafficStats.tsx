import React, { useState, useEffect } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  PointElement,
  LineElement,
} from 'chart.js';
import { Bar, Pie } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  PointElement,
  LineElement
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

  useEffect(() => {
    loadTrafficStats();
    loadOnlineClients();
  }, [groupBy]);

  const loadTrafficStats = async () => {
    setLoading(true);
    setError('');

    try {
      const res = await api.get('/v1/traffic/stats', {
        params: { group_by: groupBy },
        auth: getAuth()
      });

      setTrafficData(res.data.traffic || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load traffic stats');
    } finally {
      setLoading(false);
    }
  };

  const loadOnlineClients = async () => {
    try {
      const res = await api.get('/v1/clients/online', {
        auth: getAuth()
      });

      setOnlineClients(res.data.online_clients || []);
    } catch (err: any) {
      console.error('Failed to load online clients:', err);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 GB';
    const gb = bytes / 1073741824;
    return gb.toFixed(2) + ' GB';
  };

  const sortedTraffic = [...trafficData].sort((a, b) => b.total - a.total).slice(0, topN);

  // Top Clients Bar Chart
  const topClientsData = {
    labels: sortedTraffic.map(d => d.email || d.node_name || 'Unknown'),
    datasets: [
      {
        label: 'Upload (GB)',
        data: sortedTraffic.map(d => (d.upload / 1073741824).toFixed(2)),
        backgroundColor: colors.success + 'CC',
        borderColor: colors.success,
        borderWidth: 1,
      },
      {
        label: 'Download (GB)',
        data: sortedTraffic.map(d => (d.download / 1073741824).toFixed(2)),
        backgroundColor: colors.accent + 'CC',
        borderColor: colors.accent,
        borderWidth: 1,
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
            size: 12
          }
        }
      },
      title: {
        display: false,
      },
    },
    scales: {
      x: {
        ticks: {
          color: colors.text.secondary,
          font: {
            size: 10
          }
        },
        grid: {
          color: colors.border
        }
      },
      y: {
        ticks: {
          color: colors.text.secondary
        },
        grid: {
          color: colors.border
        }
      }
    }
  };

  // Traffic Distribution Pie Chart
  const totalUpload = trafficData.reduce((sum, d) => sum + d.upload, 0);
  const totalDownload = trafficData.reduce((sum, d) => sum + d.download, 0);

  const pieData = {
    labels: ['Upload', 'Download'],
    datasets: [
      {
        data: [
          (totalUpload / 1073741824).toFixed(2),
          (totalDownload / 1073741824).toFixed(2)
        ],
        backgroundColor: [colors.success + 'CC', colors.accent + 'CC'],
        borderColor: [colors.success, colors.accent],
        borderWidth: 2,
      },
    ],
  };

  const pieOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom' as const,
        labels: {
          color: colors.text.primary,
          font: {
            size: 12
          }
        }
      },
    },
  };

  return (
    <div className="traffic-stats">
      <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0" style={{ color: colors.accent }}>📈 Traffic Statistics</h5>
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
              {loading ? '⏳' : '🔄'} Refresh
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
        </div>
      </div>

      {/* Stats Summary */}
      <div className="row mb-3">
        <div className="col-md-3">
          <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Total Upload</div>
            <h4 style={{ color: colors.success }}>{formatBytes(totalUpload)}</h4>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Total Download</div>
            <h4 style={{ color: colors.accent }}>{formatBytes(totalDownload)}</h4>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Total Traffic</div>
            <h4 style={{ color: colors.info }}>{formatBytes(totalUpload + totalDownload)}</h4>
          </div>
        </div>
        <div className="col-md-3">
          <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <div className="small" style={{ color: colors.text.secondary }}>Online Clients</div>
            <h4 style={{ color: colors.warning }}>{onlineClients.length}</h4>
          </div>
        </div>
      </div>

      {/* Charts */}
      <div className="row mb-3">
        <div className="col-md-8">
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
        <div className="col-md-4">
          <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <h6 className="mb-3" style={{ color: colors.text.primary }}>Traffic Distribution</h6>
            <div style={{ height: '400px' }}>
              {loading ? (
                <div className="d-flex justify-content-center align-items-center h-100">
                  <div className="spinner-border"></div>
                </div>
              ) : (
                <Pie data={pieData} options={pieOptions} />
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Online Clients */}
      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <h6 className="mb-3" style={{ color: colors.text.primary }}>🟢 Online Clients ({onlineClients.length})</h6>
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
                {onlineClients.map((client, idx) => (
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
                  <th style={{ color: colors.text.secondary }}>Upload</th>
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
                    <td style={{ color: colors.success }}>{formatBytes(item.upload)}</td>
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

function getAuth() {
  if (typeof window !== 'undefined') {
    const auth = localStorage.getItem('sub_auth');
    if (auth) {
      const parsed = JSON.parse(auth);
      return { username: parsed.user, password: parsed.password };
    }
  }
  return { username: '', password: '' };
}
