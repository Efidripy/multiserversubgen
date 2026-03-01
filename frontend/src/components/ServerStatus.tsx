import React, { useState, useEffect } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';

interface ServerStatus {
  node: string;
  available: boolean;
  timestamp?: string;
  error?: string;
  system?: {
    cpu: number;
    mem: {
      current: number;
      total: number;
      percent: number;
    };
    disk: {
      current: number;
      total: number;
      percent: number;
    };
    uptime: number;
    loads: number[];
  };
  xray?: {
    state: string;
    running: boolean;
    version: string;
    uptime: number;
  };
  network?: {
    upload: number;
    download: number;
  };
}

export const ServerStatus: React.FC = () => {
  const { colors } = useTheme();
  const [servers, setServers] = useState<ServerStatus[]>([]);
  const [nodeIds, setNodeIds] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval] = useState(30);

  useEffect(() => {
    loadServersStatus();
  }, []);

  useEffect(() => {
    if (autoRefresh) {
      const timer = setInterval(() => {
        loadServersStatus();
      }, refreshInterval * 1000);
      return () => clearInterval(timer);
    }
  }, [autoRefresh, refreshInterval]);

  const loadServersStatus = async () => {
    setLoading(true);
    setError('');

    try {
      const nodesRes = await api.get('/v1/nodes', { auth: getAuth() });
      const nodes: Array<{ id: number; name: string }> = nodesRes.data || [];

      const idMap: Record<string, number> = {};
      nodes.forEach(n => { idMap[n.name] = n.id; });
      setNodeIds(idMap);

      const statuses = await Promise.all(
        nodes.map(n =>
          api.get(`/v1/nodes/${n.id}/server-status`, { auth: getAuth() })
            .then(r => r.data as ServerStatus)
            .catch(() => ({ node: n.name, available: false, error: 'Connection failed' } as ServerStatus))
        )
      );
      setServers(statuses);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load server status');
    } finally {
      setLoading(false);
    }
  };

  const handleRestartXray = async (nodeName: string) => {
    if (!window.confirm('Are you sure you want to restart Xray on this server?')) return;

    const nodeId = nodeIds[nodeName];
    if (!nodeId) {
      alert('Node ID not found');
      return;
    }

    try {
      await api.post(`/v1/servers/${nodeId}/restart-xray`, {}, {
        auth: getAuth()
      });
      alert('Xray restart command sent successfully');
      setTimeout(loadServersStatus, 3000);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to restart Xray');
    }
  };

  const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m`;
    return `${seconds}s`;
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  };

  const getStatusColor = (percent: number) => {
    if (percent < 50) return '#3fb950';
    if (percent < 80) return '#d29922';
    return '#f85149';
  };

  return (
    <div className="server-status">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h4 className="mb-0" style={{ color: colors.accent }}>Server Status</h4>
        <div className="d-flex align-items-center gap-2">
          <div className="form-check form-check-inline mb-0">
            <input
              className="form-check-input"
              type="checkbox"
              id="autoRefresh"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <label className="form-check-label small" style={{ color: colors.text.secondary }} htmlFor="autoRefresh">
              Auto ({refreshInterval}s)
            </label>
          </div>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
            onClick={loadServersStatus}
            disabled={loading}
          >
            {loading ? '⏳' : '🔄'}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
          {error}
        </div>
      )}

      <div className="server-grid">
        {servers.map((server, idx) => (
          <div className="server-card" key={idx} style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            {/* Card header */}
            <div className="server-card__header">
              <div className="server-card__name" style={{ color: colors.text.primary }}>
                <span
                  className="server-card__dot"
                  style={{ backgroundColor: server.available ? '#22c55e' : '#ef4444' }}
                />
                {server.node}
              </div>
              <span
                className="badge"
                style={{ backgroundColor: server.available ? colors.success : colors.danger }}
              >
                {server.available ? 'Online' : 'Offline'}
              </span>
            </div>

            {!server.available && (
              <p className="server-card__error small" style={{ color: colors.warning }}>
                ⚠️ {server.error || 'Connection failed'}
              </p>
            )}

            {server.available && server.system && (
              <div className="server-card__metrics">
                {/* CPU */}
                <div className="server-card__metric">
                  <div className="server-card__metric-row">
                    <span className="small" style={{ color: colors.text.secondary }}>CPU</span>
                    <span className="small" style={{ color: getStatusColor(server.system.cpu) }}>
                      {server.system.cpu.toFixed(1)}%
                    </span>
                  </div>
                  <div className="progress" style={{ height: '5px', backgroundColor: colors.bg.tertiary }}>
                    <div className="progress-bar" style={{ width: `${server.system.cpu}%`, backgroundColor: getStatusColor(server.system.cpu) }} />
                  </div>
                </div>
                {/* Memory */}
                <div className="server-card__metric">
                  <div className="server-card__metric-row">
                    <span className="small" style={{ color: colors.text.secondary }}>MEM</span>
                    <span className="small" style={{ color: getStatusColor(server.system.mem.percent) }}>
                      {server.system.mem.percent.toFixed(0)}%
                    </span>
                  </div>
                  <div className="progress" style={{ height: '5px', backgroundColor: colors.bg.tertiary }}>
                    <div className="progress-bar" style={{ width: `${server.system.mem.percent}%`, backgroundColor: getStatusColor(server.system.mem.percent) }} />
                  </div>
                </div>
                {/* Disk */}
                <div className="server-card__metric">
                  <div className="server-card__metric-row">
                    <span className="small" style={{ color: colors.text.secondary }}>DISK</span>
                    <span className="small" style={{ color: getStatusColor(server.system.disk.percent) }}>
                      {server.system.disk.percent.toFixed(0)}%
                    </span>
                  </div>
                  <div className="progress" style={{ height: '5px', backgroundColor: colors.bg.tertiary }}>
                    <div className="progress-bar" style={{ width: `${server.system.disk.percent}%`, backgroundColor: getStatusColor(server.system.disk.percent) }} />
                  </div>
                </div>

                {/* Footer row */}
                <div className="server-card__footer-row">
                  {server.network && (
                    <span className="small" style={{ color: colors.text.secondary }}>
                      ↓ {formatBytes(server.network.download)}
                    </span>
                  )}
                  <span className="small" style={{ color: colors.text.secondary }}>
                    ⏱ {formatUptime(server.system.uptime)}
                  </span>
                  {server.timestamp && (
                    <span className="small" style={{ color: colors.text.secondary }}>
                      {new Date(server.timestamp).toLocaleTimeString()}
                    </span>
                  )}
                </div>

                {/* Xray + restart */}
                {server.xray && (
                  <div className="server-card__xray" style={{ borderTop: `1px solid ${colors.border}` }}>
                    <span className="small" style={{ color: colors.text.secondary }}>
                      Xray {server.xray.version}
                      {server.xray.running ? (
                        <span className="badge ms-1" style={{ backgroundColor: colors.success }}>▶</span>
                      ) : (
                        <span className="badge ms-1" style={{ backgroundColor: colors.danger }}>■</span>
                      )}
                    </span>
                    <button
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.warning + '33', borderColor: colors.warning + '66', color: colors.warning, padding: '1px 8px', fontSize: '0.75rem' }}
                      onClick={() => handleRestartXray(server.node)}
                      disabled={!server.xray.running}
                    >
                      🔄
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {servers.length === 0 && !loading && (
        <div className="text-center py-5" style={{ color: colors.text.secondary }}>
          <p>No servers configured. Add servers in the Servers tab.</p>
        </div>
      )}
    </div>
  );
};
