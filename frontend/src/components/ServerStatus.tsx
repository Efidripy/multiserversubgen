import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useTheme } from '../contexts/ThemeContext';

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
      const res = await axios.get('/api/v1/servers/status', {
        auth: getAuth()
      });

      setServers(res.data.servers || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load server status');
    } finally {
      setLoading(false);
    }
  };

  const handleRestartXray = async (nodeId: number) => {
    if (!window.confirm('Are you sure you want to restart Xray on this server?')) return;

    try {
      await axios.post(`/api/v1/servers/${nodeId}/restart-xray`, {}, {
        auth: getAuth()
      });
      alert('Xray restart command sent successfully');
      setTimeout(loadServersStatus, 3000);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to restart Xray');
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  };

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  };

  const getStatusColor = (percent: number) => {
    if (percent < 50) return '#3fb950';
    if (percent < 80) return '#d29922';
    return '#f85149';
  };

  return (
    <div className="server-status">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h4 style={{ color: colors.accent }}>🖥️ Server Status & Monitoring</h4>
        <div>
          <div className="form-check form-check-inline">
            <input
              className="form-check-input"
              type="checkbox"
              id="autoRefresh"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <label className="form-check-label small" style={{ color: colors.text.secondary }} htmlFor="autoRefresh">
              Auto-refresh ({refreshInterval}s)
            </label>
          </div>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
            onClick={loadServersStatus}
            disabled={loading}
          >
            {loading ? '⏳ Loading...' : '🔄 Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
          {error}
        </div>
      )}

      <div className="row">
        {servers.map((server, idx) => (
          <div className="col-md-6 mb-4" key={idx}>
            <div className="card h-100" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="card-body">
                {/* Server Header */}
                <div className="d-flex justify-content-between align-items-center mb-3">
                  <h5 className="mb-0" style={{ color: colors.accent }}>
                    {server.available ? '🟢' : '🔴'} {server.node}
                  </h5>
                  {server.available && (
                    <span className="badge" style={{ backgroundColor: colors.success }}>Online</span>
                  )}
                  {!server.available && (
                    <span className="badge" style={{ backgroundColor: colors.danger }}>Offline</span>
                  )}
                </div>

                {!server.available && (
                  <div className="alert alert-warning" style={{ backgroundColor: colors.warning + '22', borderColor: colors.warning, color: colors.warning }}>
                    <strong>⚠️ Server unavailable</strong>
                    <p className="mb-0 small mt-1">{server.error || 'Connection failed'}</p>
                  </div>
                )}

                {server.available && server.system && (
                  <>
                    {/* CPU & Memory */}
                    <div className="mb-3">
                      <div className="d-flex justify-content-between small mb-1">
                        <span style={{ color: colors.text.secondary }}>CPU Usage</span>
                        <span style={{ color: getStatusColor(server.system.cpu) }}>
                          {server.system.cpu.toFixed(1)}%
                        </span>
                      </div>
                      <div className="progress" style={{ height: '8px', backgroundColor: colors.bg.tertiary }}>
                        <div
                          className="progress-bar"
                          style={{ 
                            width: `${server.system.cpu}%`,
                            backgroundColor: getStatusColor(server.system.cpu)
                          }}
                        ></div>
                      </div>
                    </div>

                    <div className="mb-3">
                      <div className="d-flex justify-content-between small mb-1">
                        <span style={{ color: colors.text.secondary }}>Memory</span>
                        <span style={{ color: getStatusColor(server.system.mem.percent) }}>
                          {formatBytes(server.system.mem.current)} / {formatBytes(server.system.mem.total)} 
                          ({server.system.mem.percent.toFixed(1)}%)
                        </span>
                      </div>
                      <div className="progress" style={{ height: '8px', backgroundColor: colors.bg.tertiary }}>
                        <div
                          className="progress-bar"
                          style={{ 
                            width: `${server.system.mem.percent}%`,
                            backgroundColor: getStatusColor(server.system.mem.percent)
                          }}
                        ></div>
                      </div>
                    </div>

                    <div className="mb-3">
                      <div className="d-flex justify-content-between small mb-1">
                        <span style={{ color: colors.text.secondary }}>Disk</span>
                        <span style={{ color: getStatusColor(server.system.disk.percent) }}>
                          {formatBytes(server.system.disk.current)} / {formatBytes(server.system.disk.total)}
                          ({server.system.disk.percent.toFixed(1)}%)
                        </span>
                      </div>
                      <div className="progress" style={{ height: '8px', backgroundColor: colors.bg.tertiary }}>
                        <div
                          className="progress-bar"
                          style={{ 
                            width: `${server.system.disk.percent}%`,
                            backgroundColor: getStatusColor(server.system.disk.percent)
                          }}
                        ></div>
                      </div>
                    </div>

                    {/* System Info */}
                    <div className="row g-2 mb-3">
                      <div className="col-6">
                        <div className="small" style={{ color: colors.text.secondary }}>Uptime</div>
                        <div style={{ color: colors.text.primary }}>{formatUptime(server.system.uptime)}</div>
                      </div>
                      <div className="col-6">
                        <div className="small" style={{ color: colors.text.secondary }}>Load Avg</div>
                        <div style={{ color: colors.text.primary }}>
                          {server.system.loads.map(l => l.toFixed(2)).join(' ')}
                        </div>
                      </div>
                    </div>

                    {/* Xray Status */}
                    {server.xray && (
                      <div className="border-top pt-3" style={{ borderColor: colors.border }}>
                        <div className="d-flex justify-content-between align-items-center mb-2">
                          <div>
                            <strong style={{ color: colors.text.primary }}>Xray Core</strong>
                            {server.xray.running ? (
                              <span className="badge ms-2" style={{ backgroundColor: colors.success }}>Running</span>
                            ) : (
                              <span className="badge ms-2" style={{ backgroundColor: colors.danger }}>Stopped</span>
                            )}
                          </div>
                          <button
                            className="btn btn-sm"
                            style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: '#000' }}
                            onClick={() => handleRestartXray(idx + 1)}
                            disabled={!server.xray.running}
                          >
                            🔄 Restart
                          </button>
                        </div>
                        <div className="row g-2 small">
                          <div className="col-6">
                            <span style={{ color: colors.text.secondary }}>Version:</span>
                            <span style={{ color: colors.text.primary }} className="ms-1">{server.xray.version}</span>
                          </div>
                          <div className="col-6">
                            <span style={{ color: colors.text.secondary }}>Uptime:</span>
                            <span style={{ color: colors.text.primary }} className="ms-1">{formatUptime(server.xray.uptime)}</span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Network Stats */}
                    {server.network && (
                      <div className="border-top pt-3 mt-3" style={{ borderColor: colors.border }}>
                        <div className="small mb-2" style={{ color: colors.text.secondary }}>Network Traffic</div>
                        <div className="row g-2 small">
                          <div className="col-6">
                            <span style={{ color: colors.text.secondary }}>↑ Upload:</span>
                            <span style={{ color: colors.text.primary }} className="ms-1">{formatBytes(server.network.upload)}</span>
                          </div>
                          <div className="col-6">
                            <span style={{ color: colors.text.secondary }}>↓ Download:</span>
                            <span style={{ color: colors.text.primary }} className="ms-1">{formatBytes(server.network.download)}</span>
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {server.timestamp && (
                  <div className="small mt-3" style={{ color: colors.text.secondary }}>
                    Last updated: {new Date(server.timestamp).toLocaleTimeString()}
                  </div>
                )}
              </div>
            </div>
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
