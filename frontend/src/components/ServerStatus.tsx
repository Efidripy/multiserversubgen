import React, { useState, useEffect } from 'react';
import { useToast } from './Toast';
import { useTranslation } from 'react-i18next';
import { Line } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler } from 'chart.js';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler);

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
    swap?: {
      current: number;
      total: number;
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
  const { toast } = useToast();
  const { t } = useTranslation();
  const [servers, setServers] = useState<ServerStatus[]>([]);
  const [nodeIds, setNodeIds] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [onlineCountByNode, setOnlineCountByNode] = useState<Record<number, number>>({});
  const [latencyByNode, setLatencyByNode] = useState<Record<number, number>>({});
  const [updateAvailableNodes, setUpdateAvailableNodes] = useState<Set<number>>(new Set());
  const [collectorStatus, setCollectorStatus] = useState<{ running: boolean; mode: string; ws: number } | null>(null);
  const _ssSaved = (() => { try { return JSON.parse(localStorage.getItem('sub_manager_ss_prefs_v1') || '{}'); } catch { return {}; } })();
  const [cardSort, setCardSort] = useState<'name' | 'cpu' | 'status' | 'clients'>(_ssSaved.cardSort ?? 'name');
  const SS_PREFS_KEY = 'sub_manager_ss_prefs_v1';
  const _ssPrefs = (() => { try { return JSON.parse(localStorage.getItem(SS_PREFS_KEY) || '{}'); } catch { return {}; } })();
  const [autoRefresh, setAutoRefresh] = useState<boolean>(_ssPrefs.autoRefresh ?? false);
  const [refreshInterval, setRefreshInterval] = useState<number>(_ssPrefs.refreshInterval ?? 30);

  useEffect(() => {
    try { localStorage.setItem(SS_PREFS_KEY, JSON.stringify({ autoRefresh, refreshInterval, cardSort })); } catch {}
  }, [autoRefresh, refreshInterval, cardSort]);
  const [showLogsModal, setShowLogsModal] = useState(false);
  const [logsNodeId, setLogsNodeId] = useState<number | null>(null);
  const [logsNodeName, setLogsNodeName] = useState('');
  const [logsLevel, setLogsLevel] = useState<'debug' | 'info' | 'warning' | 'error'>('info');
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState('');
  const [logsLines, setLogsLines] = useState<string[]>([]);
  const [logsTab, setLogsTab] = useState<'panel' | 'xray'>('xray');
  // Key generator
  const [showKeyGen, setShowKeyGen] = useState(false);
  const [keyGenNodeId, setKeyGenNodeId] = useState<number | null>(null);
  const [keyGenResult, setKeyGenResult] = useState<Record<string, string>>({});
  const [keyGenLoading, setKeyGenLoading] = useState(false);
  // Xray version manager
  const [showVersionModal, setShowVersionModal] = useState(false);
  const [versionNodeId, setVersionNodeId] = useState<number | null>(null);
  const [versionNodeName, setVersionNodeName] = useState('');
  const [xrayVersions, setXrayVersions] = useState<string[]>([]);
  const [versionLoading, setVersionLoading] = useState(false);
  const [versionInstalling, setVersionInstalling] = useState('');
  // Outbound traffic modal
  const [showOutboundsModal, setShowOutboundsModal] = useState(false);
  const [outboundsNodeName, setOutboundsNodeName] = useState('');
  const [outboundsData, setOutboundsData] = useState<any[]>([]);
  const [outboundsLoading, setOutboundsLoading] = useState(false);
  // Xray metrics modal
  const [showMetricsModal, setShowMetricsModal] = useState(false);
  const [metricsNodeName, setMetricsNodeName] = useState('');
  const [metricsData, setMetricsData] = useState<any>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  // API Tokens modal
  const [showApiTokensModal, setShowApiTokensModal] = useState(false);
  const [apiTokensNodeId, setApiTokensNodeId] = useState<number | null>(null);
  const [apiTokensNodeName, setApiTokensNodeName] = useState('');
  const [apiTokensList, setApiTokensList] = useState<any[]>([]);
  const [apiTokensLoading, setApiTokensLoading] = useState(false);
  const [apiTokenNewName, setApiTokenNewName] = useState('');
  // Xray Config modal
  const [showXrayConfig, setShowXrayConfig] = useState(false);
  const [xrayConfigNodeName, setXrayConfigNodeName] = useState('');
  const [xrayConfigData, setXrayConfigData] = useState<any>(null);
  const [xrayConfigLoading, setXrayConfigLoading] = useState(false);
  // Server History Chart modal
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [historyNodeId, setHistoryNodeId] = useState<number | null>(null);
  const [historyNodeName, setHistoryNodeName] = useState('');
  const [historyMetric, setHistoryMetric] = useState<'cpu' | 'mem' | 'disk' | 'netSent' | 'netRecv'>('cpu');
  const [historyBucket, setHistoryBucket] = useState<'1m' | '5m' | '15m' | '1h' | '6h' | '24h'>('5m');
  const [historyData, setHistoryData] = useState<Array<{t: number; v: number}>>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  // Panel Update Info modal
  const [showUpdateInfoModal, setShowUpdateInfoModal] = useState(false);
  const [updateInfoNodeName, setUpdateInfoNodeName] = useState('');
  const [updateInfoData, setUpdateInfoData] = useState<any>(null);
  const [updateInfoLoading, setUpdateInfoLoading] = useState(false);
  // Xray Observatory modal
  const [showObservatoryModal, setShowObservatoryModal] = useState(false);
  const [observatoryNodeName, setObservatoryNodeName] = useState('');
  const [observatoryData, setObservatoryData] = useState<any>(null);
  const [observatoryLoading, setObservatoryLoading] = useState(false);

  const formatStatusReason = (server: ServerStatus) => {
    const reason = server.reason || '';
    if (reason === 'auth_failed') return t('serverStatus.authFailed');
    if (reason === 'two_factor_required') return t('serverStatus.twoFactorRequired');
    if (reason === 'tls_error') return t('serverStatus.tlsError');
    if (reason === 'timeout') return t('serverStatus.timeout');
    if (reason.startsWith('http_')) return reason.replace('_', ' ').toUpperCase();
    return server.error || t('serverStatus.connectionFailed');
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
    loadOnlineCounts();
    api.get('/v1/collector/status', { auth: getAuth() })
      .then(res => setCollectorStatus({ running: res.data?.running, mode: res.data?.mode, ws: res.data?.ws_connections ?? 0 }))
      .catch(() => {});
  }, []);

  const checkForUpdates = async (nodeIds: number[]) => {
    for (const id of nodeIds) {
      api.get(`/v1/nodes/${id}/panel-update-info`, { auth: getAuth() })
        .then(res => {
          const hasUpdate = res.data?.isUpdatable ?? res.data?.has_update ?? false;
          if (hasUpdate) setUpdateAvailableNodes(prev => new Set([...prev, id]));
        })
        .catch(() => {});
    }
  };

  const loadOnlineCounts = async () => {
    try {
      const res = await api.get('/v1/clients/online', { auth: getAuth() });
      const list: Array<{ email: string; node_name?: string; node_id?: number }> = res.data?.online || [];
      const counts: Record<number, number> = {};
      // Also fetch node list to resolve name→id if needed
      const nodesRes = await api.get('/v1/nodes', { auth: getAuth() });
      const nodeList: Array<{ id: number; name: string }> = nodesRes.data || [];
      const nameToId = new Map(nodeList.map(n => [n.name, n.id]));
      list.forEach(c => {
        const nid = c.node_id ?? (c.node_name ? nameToId.get(c.node_name) : undefined);
        if (nid) counts[nid] = (counts[nid] || 0) + 1;
      });
      setOnlineCountByNode(counts);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    if (autoRefresh) {
      const timer = setInterval(() => {
        loadServersStatus();
      }, refreshInterval * 1000);
      return () => clearInterval(timer);
    }
  }, [autoRefresh, refreshInterval]);

  const refreshSingleNode = async (nodeId: number, _nodeName?: string) => {
    setServers(prev => prev.map(s => s.nodeId === nodeId ? { ...s, loadingDetails: true } : s));
    try {
      const res = await api.get(`/v1/servers/${nodeId}/status`, { auth: getAuth() });
      const status = res.data;
      setServers(prev => prev.map(s => {
        if (s.nodeId !== nodeId) return s;
        return {
          ...s, loadingDetails: false,
          available: Boolean(status?.available),
          system: status?.system,
          xray: status?.xray,
          network: status?.network,
        };
      }));
      const count = await api.get(`/v1/clients/count`, { auth: getAuth(), params: { node_id: nodeId } }).then(r => r.data?.count ?? 0).catch(() => 0);
      if (count > 0) setOnlineCountByNode(prev => ({ ...prev, [nodeId]: count }));
    } catch {
      setServers(prev => prev.map(s => s.nodeId === nodeId ? { ...s, loadingDetails: false, available: false } : s));
    }
  };

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
      // Check for panel updates in background
      const onlineNodeIds = nodes.filter(n => snapshotByNodeId.get(n.id)?.available).map(n => n.id);
      if (onlineNodeIds.length > 0) checkForUpdates(onlineNodeIds);

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

        const t0 = Date.now();
        api.get(`/v1/nodes/${node.id}/server-status`, { auth })
          .then((response) => {
            const ms = Date.now() - t0;
            setLatencyByNode(prev => ({ ...prev, [node.id]: ms }));
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
      setError(err.response?.data?.detail || t('serverStatus.loadFailed'));
      setLoading(false);
    }
  };

  const forceRefresh = async () => {
    try {
      await api.post('/v1/nodes/refresh-now', {}, { auth: getAuth() });
      await loadServersStatus();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('serverStatus.forceRefreshFailed'));
    }
  };

  const handleRestartCore = async (nodeName: string) => {
    if (!window.confirm(t('serverStatus.confirmRestart'))) return;

    const nodeId = nodeIds[nodeName];
    if (!nodeId) {
      toast(t('serverStatus.nodeIdMissing'), 'warning');
      return;
    }

    try {
      await api.post(`/v1/servers/${nodeId}/restart-xray`, {}, {
        auth: getAuth()
      });
      toast(t('serverStatus.restartSent'), 'success');
      setTimeout(loadServersStatus, 3000);
    } catch (err: any) {
      toast(err.response?.data?.detail || t('serverStatus.restartFailed'), 'error');
    }
  };

  // loadServerLogs kept for backward compat; new code uses loadServerLogs2
  const _loadServerLogsLegacy = async (nodeId: number, level: string) => {
    await loadServerLogs2(nodeId, level, logsTab);
  };
  void _loadServerLogsLegacy;

  const handleViewLogs = async (nodeName: string) => {
    const nodeId = nodeIds[nodeName];
    if (!nodeId) { toast(t('serverStatus.nodeIdMissing'), 'warning'); return; }
    setLogsNodeId(nodeId);
    setLogsNodeName(nodeName);
    setShowLogsModal(true);
    await loadServerLogs2(nodeId, logsLevel, logsTab);
  };

  const loadServerLogs2 = async (nodeId: number, level: string, tab: 'panel' | 'xray') => {
    setLogsLoading(true);
    setLogsError('');
    const endpoint = tab === 'xray'
      ? `/v1/nodes/${nodeId}/xray-logs`
      : `/v1/nodes/${nodeId}/server-logs`;
    try {
      const res = await api.get(endpoint, { params: { count: 200, level }, auth: getAuth() });
      const payload = res.data || {};
      if (payload.error) { setLogsError(String(payload.error)); setLogsLines([]); }
      else setLogsLines(Array.isArray(payload.logs) ? payload.logs : []);
    } catch (err: any) {
      setLogsError(err.response?.data?.detail || 'Failed to load logs');
      setLogsLines([]);
    } finally {
      setLogsLoading(false);
    }
  };

  const handleOpenKeyGen = (nodeId: number) => {
    setKeyGenNodeId(nodeId);
    setKeyGenResult({});
    setShowKeyGen(true);
  };

  const generateKey = async (type: 'uuid' | 'x25519' | 'vless-enc' | 'mldsa65') => {
    if (!keyGenNodeId) return;
    setKeyGenLoading(true);
    try {
      const res = await api.get(`/v1/nodes/${keyGenNodeId}/generate-${type}`, { auth: getAuth() });
      const data = res.data || {};
      setKeyGenResult(prev => ({ ...prev, ...data }));
    } catch (e) { console.error(e); }
    finally { setKeyGenLoading(false); }
  };

  const handleOpenVersions = async (nodeId: number, nodeName: string) => {
    setVersionNodeId(nodeId);
    setVersionNodeName(nodeName);
    setShowVersionModal(true);
    setVersionLoading(true);
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/xray-versions`, { auth: getAuth() });
      setXrayVersions(res.data?.versions || []);
    } catch (e) { setXrayVersions([]); }
    finally { setVersionLoading(false); }
  };

  const handleInstallXray = async (version: string) => {
    if (!versionNodeId || !window.confirm(`Install Xray ${version}?`)) return;
    setVersionInstalling(version);
    try {
      await api.post(`/v1/nodes/${versionNodeId}/install-xray/${version}`, {}, { auth: getAuth() });
      await loadServersStatus();
    } catch (e) { console.error(e); }
    finally { setVersionInstalling(''); }
  };

  const handleOpenOutbounds = async (nodeId: number, nodeName: string) => {
    setOutboundsNodeName(nodeName);
    setShowOutboundsModal(true);
    setOutboundsLoading(true);
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/outbounds-traffic`, { auth: getAuth() });
      setOutboundsData(res.data?.outbounds || []);
    } catch (e) { setOutboundsData([]); }
    finally { setOutboundsLoading(false); }
  };

  const handleStopXray = async (nodeId: number) => {
    if (!window.confirm('Stop Xray service on this node?')) return;
    try {
      const res = await api.post(`/v1/nodes/${nodeId}/stop-xray`, {}, { auth: getAuth() });
      if (res.data?.success) { toast('Xray stopped', 'success'); setTimeout(loadServersStatus, 2000); }
      else toast('Failed to stop Xray', 'error');
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleUpdatePanel = async (nodeId: number) => {
    if (!window.confirm('Update 3x-ui panel? The panel will restart.')) return;
    try {
      const res = await api.post(`/v1/nodes/${nodeId}/update-panel`, {}, { auth: getAuth() });
      toast(res.data?.msg || (res.data?.success ? 'Panel update started' : 'Failed'), res.data?.success ? 'success' : 'error');
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleOpenMetrics = async (nodeId: number, nodeName: string) => {
    setMetricsNodeName(nodeName);
    setShowMetricsModal(true);
    setMetricsLoading(true);
    setMetricsData(null);
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/xray-metrics`, { auth: getAuth() });
      setMetricsData(res.data);
    } catch (e) { setMetricsData(null); }
    finally { setMetricsLoading(false); }
  };

  const handleOpenApiTokens = async (nodeId: number, nodeName: string) => {
    setApiTokensNodeId(nodeId);
    setApiTokensNodeName(nodeName);
    setShowApiTokensModal(true);
    setApiTokensLoading(true);
    setApiTokenNewName('');
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/api-tokens`, { auth: getAuth() });
      setApiTokensList(res.data?.tokens || res.data || []);
    } catch (e) { setApiTokensList([]); }
    finally { setApiTokensLoading(false); }
  };

  const handleCreateApiToken = async () => {
    if (!apiTokensNodeId || !apiTokenNewName.trim()) return;
    try {
      await api.post(`/v1/nodes/${apiTokensNodeId}/api-tokens`, { name: apiTokenNewName.trim() }, { auth: getAuth() });
      setApiTokenNewName('');
      await handleOpenApiTokens(apiTokensNodeId, apiTokensNodeName);
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleDeleteApiToken = async (tokenId: number) => {
    if (!apiTokensNodeId || !window.confirm('Delete this API token?')) return;
    try {
      await api.delete(`/v1/nodes/${apiTokensNodeId}/api-tokens/${tokenId}`, { auth: getAuth() });
      setApiTokensList(prev => prev.filter(t => t.id !== tokenId));
      toast('Token deleted', 'success');
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleToggleApiToken = async (tokenId: number, enabled: boolean) => {
    if (!apiTokensNodeId) return;
    try {
      await api.post(`/v1/nodes/${apiTokensNodeId}/api-tokens/${tokenId}/set-enabled`, { enabled }, { auth: getAuth() });
      setApiTokensList(prev => prev.map(t => t.id === tokenId ? { ...t, enable: enabled } : t));
      toast(enabled ? 'Token enabled' : 'Token disabled', 'info');
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleOpenUpdateInfo = async (nodeId: number, nodeName: string) => {
    setUpdateInfoNodeName(nodeName);
    setShowUpdateInfoModal(true);
    setUpdateInfoLoading(true);
    setUpdateInfoData(null);
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/panel-update-info`, { auth: getAuth() });
      setUpdateInfoData(res.data);
    } catch (e) { setUpdateInfoData(null); }
    finally { setUpdateInfoLoading(false); }
  };

  const handleOpenObservatory = async (nodeId: number, nodeName: string) => {
    setObservatoryNodeName(nodeName);
    setShowObservatoryModal(true);
    setObservatoryLoading(true);
    setObservatoryData(null);
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/xray-observatory`, { auth: getAuth() });
      setObservatoryData(res.data);
    } catch (e) { setObservatoryData(null); }
    finally { setObservatoryLoading(false); }
  };

  const handleOpenXrayConfig = async (nodeId: number, nodeName: string) => {
    setXrayConfigNodeName(nodeName);
    setShowXrayConfig(true);
    setXrayConfigLoading(true);
    setXrayConfigData(null);
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/xray-config`, { auth: getAuth() });
      setXrayConfigData(res.data);
    } catch (e) { setXrayConfigData(null); }
    finally { setXrayConfigLoading(false); }
  };

  const loadHistoryData = async (nodeId: number, metric: string, bucket: string) => {
    setHistoryLoading(true);
    setHistoryData([]);
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/server-history/${metric}`, { params: { bucket }, auth: getAuth() });
      setHistoryData(res.data?.data || []);
    } catch { setHistoryData([]); }
    finally { setHistoryLoading(false); }
  };

  const handleOpenHistory = async (nodeId: number, nodeName: string) => {
    setHistoryNodeId(nodeId);
    setHistoryNodeName(nodeName);
    setShowHistoryModal(true);
    await loadHistoryData(nodeId, historyMetric, historyBucket);
  };

  const handleUpdateGeofile = async (nodeId: number) => {
    try {
      const res = await api.post(`/v1/nodes/${nodeId}/update-geofile`, {}, { auth: getAuth() });
      toast(res.data?.msg || 'Geofile updated', 'success');
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleBackupTelegram = async (nodeId: number) => {
    try {
      const res = await api.post(`/v1/nodes/${nodeId}/backup-telegram`, {}, { auth: getAuth() });
      toast(res.data?.msg || (res.data?.success ? 'Backup sent to Telegram' : 'Failed'), res.data?.success !== false ? 'success' : 'error');
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
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
        <h4 className="mb-0 d-flex align-items-center gap-2" style={{ color: colors.text.primary }}>
          {t('serverStatus.title')}
          {servers.length > 0 && (
            <span className="small" style={{ color: colors.text.secondary, fontWeight: 400, fontSize: '0.8rem' }}>
              {servers.filter(s => s.available).length}/{servers.length} online
            </span>
          )}
          {collectorStatus && (
            <span className="badge" title={`Polling: ${collectorStatus.mode} | WS: ${collectorStatus.ws}`}
              style={{ backgroundColor: collectorStatus.running ? colors.success : colors.warning, fontSize: '0.65rem', fontWeight: 400 }}>
              {collectorStatus.running ? `● ${collectorStatus.mode}` : '○ stopped'}
            </span>
          )}
        </h4>
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
              {t('serverStatus.autoRefresh')}
            </label>
          </div>
          <select
            className="form-select form-select-sm"
            value={refreshInterval}
            onChange={e => setRefreshInterval(Number(e.target.value))}
            style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.secondary, width: 'auto', fontSize: '0.75rem', padding: '2px 20px 2px 6px' }}
          >
            {[10, 15, 30, 60, 120, 300].map(s => (
              <option key={s} value={s}>{s}s</option>
            ))}
          </select>
          <button
            className="btn btn-sm"
            style={{
              backgroundColor: colors.accent,
              borderColor: colors.accent,
              color: colors.accentText
            }}
            onClick={forceRefresh}
            disabled={loading}
            title={t('common.refresh')}
          >
            <UIIcon name="refresh" size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-danger">
          {error}
        </div>
      )}

      {servers.length > 1 && (
        <div className="d-flex gap-2 mb-2 align-items-center flex-wrap">
          <span className="small" style={{ color: colors.text.secondary }}>Sort:</span>
          {(['name', 'cpu', 'status', 'clients'] as const).map(s => (
            <button key={s}
              className={`seg-tab seg-tab--xs${cardSort === s ? ' seg-tab--active' : ''}`}
              onClick={() => setCardSort(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      {servers.filter(s => s.available && s.nodeId).length > 1 && (
        <div className="d-flex gap-2 mb-3 flex-wrap">
          <button className="btn btn-sm btn-ghost-warning"
            title="Restart Xray on ALL online nodes"
            onClick={async () => {
              const online = servers.filter(s => s.available && s.nodeId);
              if (!window.confirm(`Restart Xray on all ${online.length} online nodes?`)) return;
              let ok = 0; let fail = 0;
              for (const s of online) {
                try {
                  await api.post(`/v1/servers/${s.nodeId}/restart-xray`, {}, { auth: getAuth() });
                  ok++;
                } catch { fail++; }
              }
              toast(`Restart sent: ${ok} OK, ${fail} failed`, ok > 0 ? 'success' : 'error');
              setTimeout(loadServersStatus, 5000);
            }}
          >
            ⟳ Restart All Xray
          </button>
          <button className="btn btn-sm btn-ghost-accent"
            title="Update geofiles on ALL online nodes"
            onClick={async () => {
              const online = servers.filter(s => s.available && s.nodeId);
              if (!window.confirm(`Update geofiles on all ${online.length} online nodes?`)) return;
              let ok = 0;
              for (const s of online) {
                try {
                  await api.post(`/v1/nodes/${s.nodeId}/update-geofile`, {}, { auth: getAuth() });
                  ok++;
                } catch { /* continue */ }
              }
              toast(`Geofiles updated on ${ok} nodes`, 'success');
            }}
          >
            🌍 Update All Geofiles
          </button>
          <button className="btn btn-sm btn-ghost-accent"
            title="Copy fleet status summary to clipboard"
            onClick={() => {
              const lines: string[] = [`Fleet Status — ${new Date().toLocaleString()}`, ''];
              for (const s of servers) {
                const status = s.available ? '✓ Online' : '✗ Offline';
                const cpu = s.system ? `CPU: ${s.system.cpu.toFixed(1)}%` : '';
                const ram = s.system?.mem ? `RAM: ${((s.system.mem.current / s.system.mem.total) * 100).toFixed(0)}%` : '';
                const clients = onlineCountByNode[s.nodeId ?? 0] !== undefined ? `Clients: ${onlineCountByNode[s.nodeId ?? 0]}` : '';
                const latency = s.nodeId && latencyByNode[s.nodeId] !== undefined ? `Ping: ${latencyByNode[s.nodeId]}ms` : '';
                const parts = [status, cpu, ram, clients, latency].filter(Boolean).join(' | ');
                lines.push(`${s.node}: ${parts}`);
              }
              navigator.clipboard.writeText(lines.join('\n'))
                .then(() => toast('Fleet summary copied to clipboard', 'success'))
                .catch(() => toast('Clipboard unavailable', 'error'));
            }}
          >
            📋 Copy Summary
          </button>
        </div>
      )}

      {servers.length > 1 && (() => {
        const onlineServers = servers.filter(s => s.available);
        const withSystem = onlineServers.filter(s => s.system);
        const avgCpu = withSystem.length > 0 ? withSystem.reduce((s, srv) => s + (srv.system!.cpu || 0), 0) / withSystem.length : 0;
        const maxCpuNode = withSystem.length > 0 ? withSystem.reduce((a, b) => ((a.system?.cpu ?? 0) > (b.system?.cpu ?? 0) ? a : b)) : null;
        const totalOnlineClients = Object.values(onlineCountByNode).reduce((s, n) => s + n, 0);
        const totalRam = withSystem.reduce((s, srv) => s + (srv.system!.mem?.total || 0), 0);
        const usedRam = withSystem.reduce((s, srv) => s + (srv.system!.mem?.current || 0), 0);
        return (
          <div className="d-flex flex-wrap gap-2 mb-2">
            {[
              { label: 'Online', value: `${onlineServers.length}/${servers.length}`, color: onlineServers.length === servers.length ? colors.success : onlineServers.length === 0 ? colors.danger : colors.warning },
              { label: 'Avg CPU', value: withSystem.length > 0 ? `${avgCpu.toFixed(1)}%` : '—', color: getStatusColor(avgCpu) },
              ...(totalRam > 0 ? [{ label: 'Fleet RAM', value: `${(usedRam / 1073741824).toFixed(1)}/${(totalRam / 1073741824).toFixed(1)} GB`, color: getStatusColor((usedRam / totalRam) * 100) }] : []),
              ...(maxCpuNode && (maxCpuNode.system?.cpu ?? 0) > 80 ? [{ label: 'Hot', value: `${maxCpuNode.node} ${(maxCpuNode.system!.cpu).toFixed(0)}%`, color: colors.danger }] : []),
              { label: 'Online clients', value: totalOnlineClients > 0 ? String(totalOnlineClients) : '—', color: colors.accent },
            ].map(stat => (
              <span key={stat.label} className="badge px-2 py-1" style={{ backgroundColor: colors.bg.tertiary, color: stat.color, fontWeight: 400, fontSize: '0.78rem' }}>
                {stat.label}: <strong>{stat.value}</strong>
              </span>
            ))}
          </div>
        );
      })()}

      <div className="server-grid">
        {[...servers].sort((a, b) => {
          if (cardSort === 'name') return a.node.localeCompare(b.node);
          if (cardSort === 'cpu') return ((b as any).system?.cpu || 0) - ((a as any).system?.cpu || 0);
          if (cardSort === 'status') return Number(b.available) - Number(a.available);
          if (cardSort === 'clients') return (onlineCountByNode[b.nodeId ?? 0] || 0) - (onlineCountByNode[a.nodeId ?? 0] || 0);
          return 0;
        }).map((server, idx) => (
          <div
            className="server-card"
            key={idx}
            style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, boxShadow: isMinimalPreset ? 'none' : undefined }}
          >
            {/* Card header */}
            <div className="server-card__header">
              <div className="server-card__name" style={{ color: colors.text.primary }}>
                <span
                  className={`status-dot ${server.available ? 'is-online' : 'is-offline'}`}
                />
                {server.node}
                {server.nodeId && updateAvailableNodes.has(server.nodeId) && (
                  <span className="chip is-warning is-clickable ms-1"
                    title="Panel update available — click to view"
                    onClick={() => server.nodeId && handleOpenUpdateInfo(server.nodeId, server.node)}>
                    ⬆ update
                  </span>
                )}
                {server.nodeId && (
                  <button
                    className="btn btn-sm p-0 ms-1"
                    style={{ background: 'none', border: 'none', color: colors.text.tertiary, fontSize: '0.75rem' }}
                    title="Refresh this node"
                    disabled={Boolean(server.loadingDetails)}
                    onClick={() => refreshSingleNode(server.nodeId!, server.node)}
                  >
                    {server.loadingDetails ? (
                      <span className="spinner-border spinner-border-sm spinner-accent" style={{ width: '10px', height: '10px', borderWidth: '0.12em' }} />
                    ) : '↺'}
                  </button>
                )}
              </div>
              <div className="d-flex align-items-center gap-1">
                <span className={`chip ${server.available ? 'is-success' : 'is-danger'}`} style={{ fontSize: '0.65rem', padding: '1px 7px' }}>
                  {server.available ? t('nodes.online') : t('nodes.offline')}
                </span>
                {server.nodeId && onlineCountByNode[server.nodeId] !== undefined && onlineCountByNode[server.nodeId] > 0 && (
                  <span className="chip is-accent" style={{ fontSize: '0.65rem', padding: '1px 7px' }}
                    title="Online clients on this node">
                    👤 {onlineCountByNode[server.nodeId]}
                  </span>
                )}
                {server.nodeId && latencyByNode[server.nodeId] !== undefined && (
                  <span
                    className={`latency-badge ${latencyByNode[server.nodeId] < 100 ? 'is-fast' : latencyByNode[server.nodeId] < 300 ? 'is-ok' : 'is-slow'}`}
                    title="Panel API latency"
                  >
                    {latencyByNode[server.nodeId]}ms
                  </span>
                )}
              </div>
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
                    {t('serverStatus.loadingLiveMetrics')}
                </span>
              </p>
            )}

            {server.available && server.system && (
              <div className="server-card__metrics">
                {/* CPU */}
                <div className="server-card__metric">
                  <div className="server-card__metric-row">
                    <span className="small" style={{ color: colors.text.secondary }}>{t('serverStatus.cpu')}</span>
                    <span className="small" style={{ color: getStatusColor(server.system.cpu) }}>
                      {server.system.cpu.toFixed(1)}%
                    </span>
                  </div>
                  <div className="progress server-card__progress">
                    <div className="progress-bar" style={{ width: `${server.system.cpu}%`, backgroundColor: getStatusColor(server.system.cpu) }} />
                  </div>
                </div>
                {/* Memory */}
                <div className="server-card__metric">
                  <div className="server-card__metric-row">
                    <span className="small" style={{ color: colors.text.secondary }}>{t('serverStatus.ram')}</span>
                    <span className="small" style={{ color: getStatusColor(server.system.mem.percent) }}>
                      {server.system.mem.percent.toFixed(0)}%
                      {server.system.mem.total > 0 && (
                        <span style={{ color: colors.text.secondary, fontSize: '0.7rem', marginLeft: '4px' }}>
                          {formatBytes(server.system.mem.current)}/{formatBytes(server.system.mem.total)}
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="progress server-card__progress">
                    <div className="progress-bar" style={{ width: `${server.system.mem.percent}%`, backgroundColor: getStatusColor(server.system.mem.percent) }} />
                  </div>
                </div>
                {/* Disk */}
                <div className="server-card__metric">
                  <div className="server-card__metric-row">
                    <span className="small" style={{ color: colors.text.secondary }}>{t('serverStatus.disk')}</span>
                    <span className="small" style={{ color: getStatusColor(server.system.disk.percent) }}>
                      {server.system.disk.percent.toFixed(0)}%
                      {server.system.disk.total > 0 && (
                        <span style={{ color: colors.text.secondary, fontSize: '0.7rem', marginLeft: '4px' }}>
                          {formatBytes(server.system.disk.current)}/{formatBytes(server.system.disk.total)}
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="progress server-card__progress">
                    <div className="progress-bar" style={{ width: `${server.system.disk.percent}%`, backgroundColor: getStatusColor(server.system.disk.percent) }} />
                  </div>
                </div>

                {/* Footer row */}
                <div className="server-card__footer-row">
                  {server.network && (
                    <span className="small" style={{ color: colors.text.secondary }} title="Network: ↑ upload / ↓ download since reboot">
                      ↑{formatBytes(server.network.upload)} ↓{formatBytes(server.network.download)}
                    </span>
                  )}
                  <span className="small" style={{ color: colors.text.secondary }}>
                    <span className="d-inline-flex align-items-center gap-1">
                      <UIIcon name="clock" size={13} />
                      {formatUptime(server.system.uptime)}
                    </span>
                  </span>
                  {server.system.loads && server.system.loads.length > 0 && (
                    <span className="small" title="Load averages 1m / 5m / 15m" style={{ color: colors.text.secondary }}>
                      LA: {server.system.loads.slice(0,3).map(l => l.toFixed(2)).join(' / ')}
                    </span>
                  )}
                  {server.system.swap && server.system.swap.total > 0 && (
                    <span className="small" title="Swap usage" style={{ color: colors.text.secondary }}>
                      Swap: {formatBytes(server.system.swap.current)}/{formatBytes(server.system.swap.total)}
                    </span>
                  )}
                  {server.nodeId && latencyByNode[server.nodeId] && (
                    <span className="small" title="API response time"
                      style={{ color: latencyByNode[server.nodeId] > 2000 ? colors.warning : latencyByNode[server.nodeId] > 5000 ? colors.danger : colors.text.secondary }}>
                      {latencyByNode[server.nodeId]}ms
                    </span>
                  )}
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
                      Core {server.xray.version}{server.xray.uptime > 0 ? ` (up ${formatUptime(server.xray.uptime)})` : ''}
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
                      className="xray-icon-btn xray-icon-btn--warning"
                      onClick={() => handleRestartCore(server.node)}
                      disabled={!server.xray.running}
                      title={t('serverStatus.restart')}
                      aria-label="Restart Xray"
                    >
                      <UIIcon name="refresh" size={13} />
                    </button>
                    {server.nodeId && (
                      <button
                        className="xray-icon-btn xray-icon-btn--danger"
                        disabled={!server.xray.running}
                        title="Stop Xray"
                        aria-label="Stop Xray"
                        onClick={async () => {
                          if (!window.confirm(`Stop Xray on "${server.node}"?`)) return;
                          try {
                            await api.post(`/v1/nodes/${server.nodeId}/stop-xray`, {}, { auth: getAuth() });
                            toast(`Xray stopped on ${server.node}`, 'warning');
                            setTimeout(() => refreshSingleNode(server.nodeId!), 2000);
                          } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                        }}
                      >■</button>
                    )}
                    <button
                      className="xray-icon-btn xray-icon-btn--accent"
                      onClick={() => handleViewLogs(server.node)}
                      title={t('serverStatus.logs')}
                      aria-label="View logs"
                    >
                      {t('serverStatus.logs')}
                    </button>
                    {server.nodeId && (
                      <>
                        <button className="xray-icon-btn xray-icon-btn--danger" aria-label="Reset All Traffics"
                          onClick={async () => { if (!window.confirm('Reset all inbound traffics?')) return; try { await api.post(`/v1/inbounds/${server.nodeId}/reset-all-traffics`, {}, { auth: getAuth() }); } catch (e) { console.error(e); } }} title="Reset All Traffics">↺</button>
                        <button className="xray-icon-btn" aria-label="Key Generator"
                          onClick={() => handleOpenKeyGen(server.nodeId!)} title="Key Generator">🔑</button>
                        <button className="xray-icon-btn" aria-label="Xray Versions"
                          onClick={() => handleOpenVersions(server.nodeId!, server.node)} title="Xray Versions">📦</button>
                        <button className="xray-icon-btn" aria-label="Outbound Traffic"
                          onClick={() => handleOpenOutbounds(server.nodeId!, server.node)} title="Outbound Traffic">📊</button>
                        <button className="xray-icon-btn" aria-label="Update Geofiles"
                          onClick={() => handleUpdateGeofile(server.nodeId!)} title="Update Geofiles">🌍</button>
                        <button className="xray-icon-btn" aria-label="Backup to Telegram"
                          onClick={() => handleBackupTelegram(server.nodeId!)} title="Backup to Telegram">📤</button>
                        <button className="xray-icon-btn xray-icon-btn--danger" aria-label="Stop Xray"
                          onClick={() => handleStopXray(server.nodeId!)} title="Stop Xray">⏹</button>
                        <button className="xray-icon-btn" aria-label="Update Panel"
                          onClick={() => handleUpdatePanel(server.nodeId!)} title="Update Panel">⬆</button>
                        <button className="xray-icon-btn" aria-label="Xray Metrics"
                          onClick={() => handleOpenMetrics(server.nodeId!, server.node)} title="Xray Metrics">📈</button>
                        <button className="xray-icon-btn" aria-label="API Tokens"
                          onClick={() => handleOpenApiTokens(server.nodeId!, server.node)} title="API Tokens">🔐</button>
                        <button className="xray-icon-btn" aria-label="Panel Update Info"
                          onClick={() => handleOpenUpdateInfo(server.nodeId!, server.node)} title="Panel Update Info">ℹ</button>
                        <button className="xray-icon-btn" aria-label="Xray Observatory"
                          onClick={() => handleOpenObservatory(server.nodeId!, server.node)} title="Xray Observatory">🔭</button>
                        <button className="xray-icon-btn" aria-label="Server History Chart"
                          onClick={() => handleOpenHistory(server.nodeId!, server.node)} title="Server History Chart">📉</button>
                        <button className="xray-icon-btn" aria-label="View Xray Config"
                          onClick={() => handleOpenXrayConfig(server.nodeId!, server.node)} title="View Xray Config">⚙</button>
                      </>
                    )}
                </div>
              )}
              </div>
            )}
          </div>
        ))}
      </div>

      {servers.length === 0 && !loading && (
        <div className="text-center py-5" style={{ color: colors.text.secondary }}>
          <p>{t('serverStatus.noServers')}</p>
        </div>
      )}

      {showLogsModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-lg modal-dialog-centered">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>{t('serverStatus.logs')}: {logsNodeName}</h6>
                <button
                  type="button"
                  className="btn-close"
                  aria-label={t('common.close')}
                  onClick={() => setShowLogsModal(false)}
                />
              </div>
              <div className="modal-body">
                <div className="d-flex gap-2 align-items-center mb-2 flex-wrap">
                  <ChoiceChips options={[{value:'xray',label:'Xray'},{value:'panel',label:'Panel'}]}
                    value={logsTab} onChange={v => { setLogsTab(v as 'xray'|'panel'); if (logsNodeId) loadServerLogs2(logsNodeId, logsLevel, v as 'xray'|'panel'); }}  />
                  <ChoiceChips
                    options={[{ value: 'debug', label: 'debug' }, { value: 'info', label: 'info' }, { value: 'warning', label: 'warning' }, { value: 'error', label: 'error' }]}
                    value={logsLevel} onChange={v => setLogsLevel(v as typeof logsLevel)} 
                  />
                  <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                    disabled={logsLoading || !logsNodeId}
                    onClick={() => { if (logsNodeId) loadServerLogs2(logsNodeId, logsLevel, logsTab); }}>
                    {logsLoading ? '...' : t('common.refresh')}
                  </button>
                  <button className="btn btn-sm" style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                    title="Download logs as text file"
                    onClick={() => {
                      const blob = new Blob([logsLines.join('\n')], { type: 'text/plain' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = `${logsTab}-logs-${logsNodeName}-${new Date().toISOString().slice(0,16)}.txt`;
                      a.click();
                      URL.revokeObjectURL(url);
                    }}>
                    ⬇ Download
                  </button>
                </div>
                {logsError && (
                  <div className="alert alert-danger py-2">
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
                  {logsLines.length > 0 ? logsLines.join('\n') : (logsLoading ? t('serverStatus.logsLoading') : t('serverStatus.noLogs'))}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Key Generator Modal */}
      {showKeyGen && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowKeyGen(false); }}>
          <div className="modal-dialog">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>🔑 Key Generator</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowKeyGen(false)} />
              </div>
              <div className="modal-body">
                <div className="d-flex gap-2 mb-3 flex-wrap">
                  {(['uuid', 'x25519', 'vless-enc', 'mldsa65'] as const).map(type => (
                    <button key={type} className="btn btn-sm" style={{ backgroundColor: colors.accent, color: colors.accentText }}
                      onClick={() => generateKey(type)} disabled={keyGenLoading}>
                      Generate {type.toUpperCase()}
                    </button>
                  ))}
                </div>
                {Object.entries(keyGenResult).map(([k, v]) => (
                  <div key={k} className="mb-2">
                    <div className="small mb-1" style={{ color: colors.text.secondary }}>{k}</div>
                    <div className="d-flex gap-1">
                      <input readOnly className="form-control form-control-sm" value={String(v)}
                        style={{ fontFamily: 'monospace', backgroundColor: colors.bg.primary, color: colors.text.primary, borderColor: colors.border }} />
                      <button className="btn btn-sm" style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                        onClick={() => navigator.clipboard.writeText(String(v))}>Copy</button>
                    </div>
                  </div>
                ))}
                {keyGenLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Xray Version Manager Modal */}
      {showVersionModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowVersionModal(false); }}>
          <div className="modal-dialog">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>📦 Xray Versions — {versionNodeName}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowVersionModal(false)} />
              </div>
              <div className="modal-body">
                {versionLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
                {!versionLoading && xrayVersions.length === 0 && <p style={{ color: colors.text.secondary }}>No versions available</p>}
                <div className="d-flex flex-column gap-1">
                  {xrayVersions.map(v => (
                    <div key={v} className="d-flex justify-content-between align-items-center p-2 rounded" style={{ backgroundColor: colors.bg.tertiary }}>
                      <span style={{ fontFamily: 'monospace', color: colors.text.primary }}>{v}</span>
                      <button className="btn btn-sm" style={{ backgroundColor: colors.accent, color: colors.accentText }}
                        onClick={() => handleInstallXray(v)} disabled={versionInstalling === v}>
                        {versionInstalling === v ? '...' : 'Install'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Xray Metrics Modal */}
      {showMetricsModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowMetricsModal(false); }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>📈 Xray Metrics — {metricsNodeName}</h6>
                <div className="d-flex gap-2 align-items-center">
                  <button className="btn btn-sm" style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                    disabled={metricsLoading}
                    onClick={() => { const id = servers.find(s => s.node === metricsNodeName)?.nodeId; if (id) handleOpenMetrics(id, metricsNodeName); }}>
                    {metricsLoading ? '…' : '↺'}
                  </button>
                  <button type="button" className="btn-close btn-close-white" onClick={() => setShowMetricsModal(false)} />
                </div>
              </div>
              <div className="modal-body">
                {metricsLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
                {!metricsLoading && !metricsData && <p style={{ color: colors.text.secondary }}>No metrics data (requires Xray metrics enabled in panel settings)</p>}
                {!metricsLoading && metricsData && (
                  <pre style={{ backgroundColor: colors.bg.primary, color: colors.text.primary, border: `1px solid ${colors.border}`, borderRadius: '8px', padding: '10px', maxHeight: '60vh', overflow: 'auto', fontSize: '12px', marginBottom: 0 }}>
                    {typeof metricsData === 'string' ? metricsData : JSON.stringify(metricsData, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* API Tokens Modal */}
      {showApiTokensModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowApiTokensModal(false); }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>🔐 API Tokens — {apiTokensNodeName}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowApiTokensModal(false)} />
              </div>
              <div className="modal-body">
                {apiTokensLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
                {!apiTokensLoading && apiTokensList.length === 0 && <p style={{ color: colors.text.secondary }}>No API tokens</p>}
                <div className="d-flex flex-column gap-2 mb-3">
                  {apiTokensList.map((token: any) => (
                    <div key={token.id} className="d-flex align-items-center justify-content-between p-2 rounded" style={{ backgroundColor: colors.bg.tertiary }}>
                      <div>
                        <span style={{ color: colors.text.primary, fontWeight: 600 }}>{token.name}</span>
                        {token.token && (
                          <div className="small mt-1" style={{ fontFamily: 'monospace', color: colors.text.secondary, wordBreak: 'break-all' }}>{token.token}</div>
                        )}
                      </div>
                      <div className="d-flex gap-2 align-items-center ms-2">
                        <button className="btn btn-sm" style={{ backgroundColor: token.enable ? colors.success : colors.bg.secondary, borderColor: token.enable ? colors.success : colors.border, color: token.enable ? '#fff' : colors.text.secondary, padding: '2px 8px', fontSize: '0.75rem' }}
                          onClick={() => handleToggleApiToken(token.id, !token.enable)}>
                          {token.enable ? 'ON' : 'OFF'}
                        </button>
                        <button className="btn btn-sm" style={{ backgroundColor: 'transparent', borderColor: colors.border, color: colors.text.secondary, padding: '2px 6px' }}
                          onClick={() => token.token && navigator.clipboard.writeText(token.token)} title="Copy token">
                          📋
                        </button>
                        <button className="btn btn-sm" style={{ backgroundColor: 'transparent', borderColor: colors.danger + '66', color: colors.danger, padding: '2px 6px' }}
                          onClick={() => handleDeleteApiToken(token.id)} title="Delete">✕</button>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="d-flex gap-2">
                  <input className="form-control form-control-sm" placeholder="New token name" value={apiTokenNewName} onChange={e => setApiTokenNewName(e.target.value)}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    onKeyDown={e => { if (e.key === 'Enter') handleCreateApiToken(); }} />
                  <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText, whiteSpace: 'nowrap' }}
                    onClick={handleCreateApiToken} disabled={!apiTokenNewName.trim()}>
                    + Create
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Outbound Traffic Modal */}
      {showOutboundsModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowOutboundsModal(false); }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>📊 Outbound Traffic — {outboundsNodeName}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowOutboundsModal(false)} />
              </div>
              <div className="modal-body">
                {outboundsLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
                {!outboundsLoading && outboundsData.length === 0 && <p style={{ color: colors.text.secondary }}>No outbound data</p>}
                <table className="table table-sm" style={{ color: colors.text.primary }}>
                  <thead><tr style={{ color: colors.text.secondary }}><th>Tag</th><th>Upload</th><th>Download</th><th>Total</th></tr></thead>
                  <tbody>
                    {outboundsData.map((o: any, i) => (
                      <tr key={i}>
                        <td style={{ fontFamily: 'monospace' }}>{o.tag || o.name || '-'}</td>
                        <td>{formatBytes(o.up || 0)}</td>
                        <td>{formatBytes(o.down || 0)}</td>
                        <td>{formatBytes((o.up || 0) + (o.down || 0))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Server History Chart Modal */}
      {showHistoryModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowHistoryModal(false); }}>
          <div className="modal-dialog modal-lg modal-dialog-centered">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>📉 Server History — {historyNodeName}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowHistoryModal(false)} />
              </div>
              <div className="modal-body">
                <div className="d-flex gap-2 mb-3 flex-wrap">
                  <ChoiceChips
                    options={[{value:'cpu',label:'CPU'},{value:'mem',label:'RAM'},{value:'disk',label:'Disk'},{value:'netSent',label:'Net↑'},{value:'netRecv',label:'Net↓'}]}
                    value={historyMetric}
                    onChange={v => {
                      const m = v as typeof historyMetric;
                      setHistoryMetric(m);
                      if (historyNodeId) loadHistoryData(historyNodeId, m, historyBucket);
                    }}
                    
                  />
                  <ChoiceChips
                    options={[{value:'1m',label:'1m'},{value:'5m',label:'5m'},{value:'15m',label:'15m'},{value:'1h',label:'1h'},{value:'6h',label:'6h'},{value:'24h',label:'24h'}]}
                    value={historyBucket}
                    onChange={v => {
                      const b = v as typeof historyBucket;
                      setHistoryBucket(b);
                      if (historyNodeId) loadHistoryData(historyNodeId, historyMetric, b);
                    }}
                    
                  />
                </div>
                {historyLoading && <div className="text-center py-4"><div className="spinner-border spinner-border-sm" /></div>}
                {!historyLoading && historyData.length === 0 && (
                  <p style={{ color: colors.text.secondary }}>No history data (requires 3x-ui v3 with statistics enabled)</p>
                )}
                {!historyLoading && historyData.length > 0 && (() => {
                  const isBytes = historyMetric === 'netSent' || historyMetric === 'netRecv';
                  const isPercent = historyMetric === 'cpu' || historyMetric === 'mem' || historyMetric === 'disk';
                  const labels = historyData.map(p => {
                    const d = new Date(p.t * 1000);
                    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                  });
                  const values = historyData.map(p => isPercent ? p.v : (isBytes ? p.v / 1024 / 1024 : p.v));
                  const metricColor = historyMetric === 'cpu' ? '#f85149' : historyMetric === 'mem' ? '#d29922' : historyMetric === 'disk' ? '#58a6ff' : '#3fb950';
                  return (
                    <Line
                      data={{
                        labels,
                        datasets: [{
                          label: historyMetric.toUpperCase(),
                          data: values,
                          borderColor: metricColor,
                          backgroundColor: metricColor + '22',
                          fill: true,
                          tension: 0.4,
                          pointRadius: historyData.length > 60 ? 0 : 2,
                          borderWidth: 2,
                        }],
                      }}
                      options={{
                        responsive: true,
                        animation: false,
                        plugins: { tooltip: { callbacks: { label: ctx => { const y = ctx.parsed.y ?? 0; return isPercent ? `${y.toFixed(1)}%` : isBytes ? `${y.toFixed(2)} MB` : String(y); } } } },
                        scales: {
                          x: { ticks: { color: colors.text.secondary, maxTicksLimit: 10 }, grid: { color: colors.border } },
                          y: { ticks: { color: colors.text.secondary, callback: v => isPercent ? `${v}%` : isBytes ? `${v}MB` : String(v) }, grid: { color: colors.border }, min: 0, max: isPercent ? 100 : undefined },
                        },
                      }}
                    />
                  );
                })()}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Panel Update Info Modal */}
      {showUpdateInfoModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowUpdateInfoModal(false); }}>
          <div className="modal-dialog">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>ℹ Panel Update — {updateInfoNodeName}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowUpdateInfoModal(false)} />
              </div>
              <div className="modal-body">
                {updateInfoLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
                {!updateInfoLoading && !updateInfoData && <p style={{ color: colors.text.secondary }}>No update info available</p>}
                {!updateInfoLoading && updateInfoData && (() => {
                  const d = updateInfoData;
                  const hasUpdate = d.isUpdatable ?? d.has_update ?? false;
                  const current = d.currentVersion ?? d.current_version ?? '—';
                  const latest = d.latestVersion ?? d.latest_version ?? '—';
                  return (
                    <div>
                      <div className="mb-2 d-flex align-items-center gap-2">
                        <span style={{ color: colors.text.secondary }}>Current:</span>
                        <span style={{ fontFamily: 'monospace', color: colors.text.primary }}>{current}</span>
                      </div>
                      <div className="mb-2 d-flex align-items-center gap-2">
                        <span style={{ color: colors.text.secondary }}>Latest:</span>
                        <span style={{ fontFamily: 'monospace', color: colors.text.primary }}>{latest}</span>
                      </div>
                      <div className="mb-3 d-flex align-items-center gap-2">
                        <span style={{ color: colors.text.secondary }}>Update available:</span>
                        <span className="badge" style={{ backgroundColor: hasUpdate ? colors.warning : colors.success }}>
                          {hasUpdate ? 'YES' : 'Up to date'}
                        </span>
                      </div>
                      {d.releaseNotes && (
                        <details>
                          <summary style={{ color: colors.text.secondary, cursor: 'pointer', fontSize: '0.85rem' }}>Release notes</summary>
                          <pre style={{ backgroundColor: colors.bg.primary, color: colors.text.primary, border: `1px solid ${colors.border}`, borderRadius: '6px', padding: '8px', marginTop: '6px', fontSize: '11px', maxHeight: '200px', overflow: 'auto' }}>
                            {d.releaseNotes}
                          </pre>
                        </details>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Xray Observatory Modal */}
      {showObservatoryModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowObservatoryModal(false); }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>🔭 Xray Observatory — {observatoryNodeName}</h6>
                <div className="d-flex gap-2 align-items-center">
                  <button className="btn btn-sm" style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                    disabled={observatoryLoading}
                    onClick={() => { const id = servers.find(s => s.node === observatoryNodeName)?.nodeId; if (id) handleOpenObservatory(id, observatoryNodeName); }}>
                    {observatoryLoading ? '…' : '↺'}
                  </button>
                  <button type="button" className="btn-close btn-close-white" onClick={() => setShowObservatoryModal(false)} />
                </div>
              </div>
              <div className="modal-body">
                {observatoryLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
                {!observatoryLoading && !observatoryData && <p style={{ color: colors.text.secondary }}>No observatory data (requires BurstObservatory in Xray config)</p>}
                {!observatoryLoading && observatoryData && (() => {
                  const statsList: any[] = observatoryData.status ?? observatoryData.states ?? observatoryData.observers ?? [];
                  if (Array.isArray(statsList) && statsList.length > 0) {
                    return (
                      <div className="d-flex flex-column gap-2">
                        {statsList.map((obs: any, i: number) => (
                          <div key={i} className="p-2 rounded" style={{ backgroundColor: colors.bg.tertiary }}>
                            <div className="d-flex justify-content-between align-items-center">
                              <span style={{ fontFamily: 'monospace', color: colors.text.primary, fontWeight: 600 }}>{obs.OutboundTag ?? obs.outboundTag ?? obs.tag ?? `#${i}`}</span>
                              <span className="badge" style={{ backgroundColor: obs.Alive ?? obs.alive ? colors.success : colors.danger }}>
                                {(obs.Alive ?? obs.alive) ? 'Alive' : 'Dead'}
                              </span>
                            </div>
                            {(obs.Delay ?? obs.delay) !== undefined && (
                              <div className="small mt-1" style={{ color: colors.text.secondary }}>
                                Delay: {obs.Delay ?? obs.delay} ms
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  }
                  return (
                    <pre style={{ backgroundColor: colors.bg.primary, color: colors.text.primary, border: `1px solid ${colors.border}`, borderRadius: '8px', padding: '10px', maxHeight: '60vh', overflow: 'auto', fontSize: '12px', marginBottom: 0 }}>
                      {JSON.stringify(observatoryData, null, 2)}
                    </pre>
                  );
                })()}
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Xray Config Modal */}
      {showXrayConfig && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowXrayConfig(false); }}>
          <div className="modal-dialog modal-xl">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>⚙ Xray Config — {xrayConfigNodeName}</h6>
                <div className="d-flex gap-2 align-items-center">
                  {xrayConfigData && !xrayConfigData.error && (
                    <button className="btn btn-sm" style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                      onClick={() => {
                        const blob = new Blob([JSON.stringify(xrayConfigData, null, 2)], { type: 'application/json' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `xray-config-${xrayConfigNodeName}-${new Date().toISOString().slice(0,10)}.json`;
                        a.click();
                        URL.revokeObjectURL(url);
                      }}>
                      ⬇ Download JSON
                    </button>
                  )}
                  <button type="button" className="btn-close btn-close-white" onClick={() => setShowXrayConfig(false)} />
                </div>
              </div>
              <div className="modal-body" style={{ maxHeight: '70vh', overflowY: 'auto' }}>
                {xrayConfigLoading && <div className="text-center py-3"><div className="spinner-border spinner-border-sm" /></div>}
                {!xrayConfigLoading && xrayConfigData && (
                  xrayConfigData.error ? (
                    <div className="alert" style={{ backgroundColor: colors.danger + '22', color: colors.danger }}>{xrayConfigData.error}</div>
                  ) : (
                    <pre style={{ backgroundColor: colors.bg.primary, color: colors.text.primary, border: `1px solid ${colors.border}`, borderRadius: '8px', padding: '12px', margin: 0, fontSize: '12px', lineHeight: 1.5 }}>
                      {JSON.stringify(xrayConfigData, null, 2)}
                    </pre>
                  )
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
