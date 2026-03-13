import React, { useState, useEffect } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';

interface ServerStatus {
  nodeId?: number;
  node: string;
  available: boolean;
  loadingDetails?: boolean;
  status?: string;
  reason?: string;
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

interface SnapshotNode {
  node_id?: number;
  name: string;
  available: boolean;
  status?: string;
  reason?: string;
  error?: string;
  xray_running?: boolean;
  timestamp?: number;
}

const SERVER_STATUS_CACHE_KEY = 'sub_manager_server_status_cache_v1';

export const ServerStatus: React.FC = () => {
  const { colors, stylePreset } = useTheme();
  const [servers, setServers] = useState<ServerStatus[]>([]);
  const [nodeIds, setNodeIds] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval] = useState(30);
  const [showLogsModal, setShowLogsModal] = useState(false);
  const [logsNodeId, setLogsNodeId] = useState<number | null>(null);
  const [logsNodeName, setLogsNodeName] = useState('');
  const [logsLevel, setLogsLevel] = useState<'debug' | 'info' | 'warning' | 'error'>('info');
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState('');
  const [logsLines, setLogsLines] = useState<string[]>([]);

  const formatStatusReason = (server: ServerStatus) => {
    const reason = server.reason || '';
    if (reason === 'auth_failed') return 'Auth failed';
    if (reason === 'two_factor_required') return '2FA required';
    if (reason === 'tls_error') return 'TLS error';
    if (reason === 'timeout') return 'Timeout';
    if (reason.startsWith('http_')) return reason.replace('_', ' ').toUpperCase();
    return server.error || 'Connection failed';
  };

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SERVER_STATUS_CACHE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as ServerStatus[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        setServers(parsed);
      }
    } catch {
      // Ignore malformed cache.
    }
  }, []);

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
      const auth = getAuth();
      const nodesRes = await api.get('/v1/nodes', { auth });
      const nodes: Array<{ id: number; name: string }> = nodesRes.data || [];
      setServers((prev) => {
        const byId = new Map(prev.map((server) => [server.nodeId, server]));
        return nodes.map((node) => {
          const existing = byId.get(node.id);
          return existing
            ? { ...existing, loadingDetails: true }
            : {
                nodeId: node.id,
                node: node.name,
                available: false,
                loadingDetails: true,
                status: 'loading',
                reason: 'loading',
                error: '',
              };
        });
      });

      const snapshotRes = await api.get('/v1/snapshots/latest', { auth });
      const snapshotNodes: SnapshotNode[] = Array.isArray(snapshotRes.data?.nodes) ? snapshotRes.data.nodes : [];
      const snapshotByNodeId = new Map<number, SnapshotNode>();
      const snapshotByName = new Map<string, SnapshotNode>();
      snapshotNodes.forEach((snapshot) => {
        if (typeof snapshot.node_id === 'number') snapshotByNodeId.set(snapshot.node_id, snapshot);
        snapshotByName.set(snapshot.name, snapshot);
      });

      const idMap: Record<string, number> = {};
      nodes.forEach(n => { idMap[n.name] = n.id; });
      setNodeIds(idMap);

      const baseStatuses: ServerStatus[] = nodes.map((node) => {
        const snapshot = snapshotByNodeId.get(node.id) || snapshotByName.get(node.name);
        return {
          nodeId: node.id,
          node: node.name,
          available: Boolean(snapshot?.available),
          loadingDetails: Boolean(snapshot?.available),
          status: snapshot?.status || (snapshot?.available ? 'online' : 'offline'),
          reason: snapshot?.reason || (snapshot?.available ? 'ok' : 'unknown'),
          error: snapshot?.error || '',
          timestamp: snapshot?.timestamp ? new Date(snapshot.timestamp * 1000).toISOString() : undefined,
          xray: snapshot ? { state: snapshot.xray_running ? 'running' : 'stopped', running: Boolean(snapshot.xray_running), version: '', uptime: 0 } : undefined,
        };
      });
      setServers(baseStatuses);
      try {
        localStorage.setItem(SERVER_STATUS_CACHE_KEY, JSON.stringify(baseStatuses));
      } catch {}
      setLoading(false);

      nodes.forEach((node) => {
        const snapshot = snapshotByNodeId.get(node.id) || snapshotByName.get(node.name);
        if (!snapshot?.available) {
          return;
        }

        api.get(`/v1/nodes/${node.id}/server-status`, { auth })
          .then((response) => {
            const live = response.data as ServerStatus;
            setServers((prev) => {
              const next = prev.map((server) => (
                server.nodeId !== node.id
                  ? server
                  : {
                      ...server,
                      ...live,
                      nodeId: node.id,
                      node: live.node || node.name,
                      available: true,
                      loadingDetails: false,
                      status: server.status,
                      reason: server.reason,
                      error: server.error,
                    }
              ));
              try {
                localStorage.setItem(SERVER_STATUS_CACHE_KEY, JSON.stringify(next));
              } catch {}
              return next;
            });
          })
          .catch(() => {
            setServers((prev) => {
              const next = prev.map((server) => (
                server.nodeId !== node.id
                  ? server
                  : {
                      ...server,
                      loadingDetails: false,
                    }
              ));
              try {
                localStorage.setItem(SERVER_STATUS_CACHE_KEY, JSON.stringify(next));
              } catch {}
              return next;
            });
          });
      });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load server status');
      setLoading(false);
    }
  };

  const forceRefresh = async () => {
    try {
      await api.post('/v1/nodes/refresh-now', {}, { auth: getAuth() });
      await loadServersStatus();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Force refresh failed');
    }
  };

  const handleRestartCore = async (nodeName: string) => {
    if (!window.confirm('Are you sure you want to restart core service on this server?')) return;

    const nodeId = nodeIds[nodeName];
    if (!nodeId) {
      alert('Node ID not found');
      return;
    }

    try {
      await api.post(`/v1/servers/${nodeId}/restart-xray`, {}, {
        auth: getAuth()
      });
      alert('Core service restart command sent successfully');
      setTimeout(loadServersStatus, 3000);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to restart core service');
    }
  };

  const loadServerLogs = async (nodeId: number, level: 'debug' | 'info' | 'warning' | 'error') => {
    setLogsLoading(true);
    setLogsError('');
    try {
      const res = await api.get(`/v1/servers/${nodeId}/logs`, {
        params: { count: 200, level },
        auth: getAuth()
      });
      const payload = res.data || {};
      if (payload.error) {
        setLogsError(String(payload.error));
        setLogsLines([]);
      } else {
        setLogsLines(Array.isArray(payload.logs) ? payload.logs : []);
      }
    } catch (err: any) {
      setLogsError(err.response?.data?.detail || 'Failed to load logs');
      setLogsLines([]);
    } finally {
      setLogsLoading(false);
    }
  };

  const handleViewLogs = async (nodeName: string) => {
    const nodeId = nodeIds[nodeName];
    if (!nodeId) {
      alert('Node ID not found');
      return;
    }
    setLogsNodeId(nodeId);
    setLogsNodeName(nodeName);
    setShowLogsModal(true);
    await loadServerLogs(nodeId, logsLevel);
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
  const isMinimalPreset = stylePreset === '3';

  return (
    <section className="panel-block server-status">
      <div className="panel-block__header mb-3">
        <h4 className="mb-0" style={{ color: colors.text.primary }}>Server Status</h4>
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
            style={{
              backgroundColor: colors.accent,
              borderColor: colors.accent,
              color: colors.accentText
            }}
            onClick={forceRefresh}
            disabled={loading}
            title="Refresh server status"
          >
            <UIIcon name="refresh" size={14} />
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
          <div
            className="server-card"
            key={idx}
            style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, boxShadow: isMinimalPreset ? 'none' : undefined }}
          >
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
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="warning" size={13} />
                  {formatStatusReason(server)}
                </span>
              </p>
            )}

            {server.available && server.loadingDetails && (
              <p className="server-card__error small" style={{ color: colors.text.secondary }}>
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="spinner" size={13} />
                  Loading live metrics...
                </span>
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
                    <span className="d-inline-flex align-items-center gap-1">
                      <UIIcon name="clock" size={13} />
                      {formatUptime(server.system.uptime)}
                    </span>
                  </span>
                  {server.timestamp && (
                    <span className="small" style={{ color: colors.text.secondary }}>
                      {new Date(server.timestamp).toLocaleTimeString()}
                    </span>
                  )}
                </div>

                {/* Core service + restart */}
                {server.xray && (
                  <div className="server-card__xray" style={{ borderTop: `1px solid ${colors.border}` }}>
                    <span className="small" style={{ color: colors.text.secondary }}>
                      Core {server.xray.version}
                      {server.xray.running ? (
                        <span className="badge ms-1 d-inline-flex align-items-center justify-content-center" style={{ backgroundColor: colors.success }}>
                          <UIIcon name="statusOn" size={12} />
                        </span>
                      ) : (
                        <span className="badge ms-1 d-inline-flex align-items-center justify-content-center" style={{ backgroundColor: colors.danger }}>
                          <UIIcon name="statusOff" size={12} />
                        </span>
                      )}
                    </span>
                    <button
                      className="btn btn-sm"
                      style={{
                        backgroundColor: isMinimalPreset ? colors.bg.tertiary : colors.warning + '33',
                        borderColor: isMinimalPreset ? colors.border : colors.warning + '66',
                        color: isMinimalPreset ? colors.text.primary : colors.warning,
                        padding: '1px 8px',
                        fontSize: '0.75rem'
                      }}
                      onClick={() => handleRestartCore(server.node)}
                      disabled={!server.xray.running}
                      title="Restart core"
                    >
                      <UIIcon name="refresh" size={13} />
                    </button>
                    <button
                      className="btn btn-sm"
                      style={{
                        backgroundColor: isMinimalPreset ? colors.bg.tertiary : colors.accent + '33',
                        borderColor: isMinimalPreset ? colors.border : colors.accent + '66',
                        color: isMinimalPreset ? colors.text.primary : colors.accent,
                        padding: '1px 8px',
                        fontSize: '0.75rem'
                      }}
                      onClick={() => handleViewLogs(server.node)}
                      title="View logs"
                    >
                      Logs
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

      {showLogsModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-lg modal-dialog-centered">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>Logs: {logsNodeName}</h6>
                <button
                  type="button"
                  className="btn-close"
                  aria-label="Close"
                  onClick={() => setShowLogsModal(false)}
                />
              </div>
              <div className="modal-body">
                <div className="d-flex gap-2 align-items-center mb-2">
                  <ChoiceChips
                    options={[
                      { value: 'debug', label: 'debug' },
                      { value: 'info', label: 'info' },
                      { value: 'warning', label: 'warning' },
                      { value: 'error', label: 'error' },
                    ]}
                    value={logsLevel}
                    onChange={(value) => setLogsLevel(value)}
                    colors={colors}
                  />
                  <button
                    className="btn btn-sm"
                    style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                    disabled={logsLoading || !logsNodeId}
                    onClick={() => { if (logsNodeId) { loadServerLogs(logsNodeId, logsLevel); } }}
                  >
                    {logsLoading ? '...' : 'Refresh'}
                  </button>
                </div>
                {logsError && (
                  <div className="alert alert-danger py-2" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
                    {logsError}
                  </div>
                )}
                <pre
                  style={{
                    backgroundColor: colors.bg.primary,
                    color: colors.text.primary,
                    border: `1px solid ${colors.border}`,
                    borderRadius: '8px',
                    padding: '10px',
                    minHeight: '320px',
                    maxHeight: '55vh',
                    overflow: 'auto',
                    marginBottom: 0,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {logsLines.length > 0 ? logsLines.join('\n') : (logsLoading ? 'Loading logs...' : 'No logs')}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
