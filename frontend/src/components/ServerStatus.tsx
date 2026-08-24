import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  FileText,
  Gauge,
  HardDrive,
  KeyRound,
  LineChart,
  Network,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Settings,
  Shield,
  Square,
  Timer,
} from 'lucide-react';
import { dashboardFleetToServerDeck, getDashboardServerDeck, type DashboardServerStatus } from '../api/dashboard';
import { refreshNodesNow } from '../api/nodes';
import { restartXray, stopXray, updateGeofile, type NodeLogKind } from '../api/serverOps';
import { useTrafficStatsSubscription, type TrafficUpdate } from '../services/useTrafficStatsSubscription';
import { NodeOperationsModal, type NodeOpsTab } from './NodeOperationsModal';
import { ServerLogsModal } from './ServerLogsModal';
import { useToast } from './Toast';
import { useDashboardData } from '../services/DashboardDataContext';

interface ServerStatusProps {
  dashboardMode?: boolean;
  includeCounts?: boolean;
  includeCollectorStatus?: boolean;
  includePanelUpdateChecks?: boolean;
  includeLiveStatus?: boolean;
  fleetSummary?: {
    total: number;
    online: number;
    offline: number;
    checking: number;
    loading: boolean;
    onlineClients?: number | null;
  };
  fleetCollapsed?: boolean;
  onToggleFleet?: () => void;
}

export const formatOnlineClients = (onlineClients: number | null | undefined): string => (
  onlineClients == null ? '—' : String(onlineClients)
);

type SortMode = 'name' | 'cpu' | 'status' | 'clients';
type NodeAction = 'restart' | 'stop' | 'geofile' | 'xrayLogs' | 'serverLogs';

type UiServer = {
  nodeId?: number;
  name: string;
  status: 'online' | 'offline';
  latency: string;
  cpu: number;
  ramPercent: number;
  ramDetail: string;
  diskPercent: number;
  diskDetail: string;
  network: string;
  uptime: string;
  load: string;
  swap: string;
  core: string;
  lastSeen: string;
  issue?: string;
  xrayCompatibility?: { status: 'ok' | 'warning' | 'unknown'; warningCount: number; codes: string[] };
};

type ServerMetaItem = {
  label: string;
  value: string;
  icon: ReactNode;
  tone?: string;
};

const nodeActionKey = (server: UiServer, action: NodeAction) => `${server.nodeId ?? server.name}:${action}`;

const widthClasses = [
  'w-0',
  'w-[3%]',
  'w-[6%]',
  'w-[8%]',
  'w-[12%]',
  'w-[16%]',
  'w-[24%]',
  'w-[32%]',
  'w-[40%]',
  'w-[48%]',
  'w-[56%]',
  'w-[64%]',
  'w-[72%]',
  'w-[80%]',
  'w-[90%]',
  'w-full',
];

const getWidthClass = (value: number) => {
  if (value <= 0) return widthClasses[0];
  if (value < 4) return widthClasses[1];
  if (value < 7) return widthClasses[2];
  if (value < 10) return widthClasses[3];
  if (value < 14) return widthClasses[4];
  if (value < 20) return widthClasses[5];
  if (value < 28) return widthClasses[6];
  if (value < 36) return widthClasses[7];
  if (value < 44) return widthClasses[8];
  if (value < 52) return widthClasses[9];
  if (value < 60) return widthClasses[10];
  if (value < 68) return widthClasses[11];
  if (value < 76) return widthClasses[12];
  if (value < 84) return widthClasses[13];
  if (value < 94) return widthClasses[14];
  return widthClasses[15];
};

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

const formatUptime = (seconds?: number) => {
  if (!seconds || seconds < 0) return '-';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

const toNumber = (value: unknown, fallback = 0): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const formatLastSeen = (value?: string | number | null) => {
  if (value === undefined || value === null || value === '') return '-';
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric < 1_000_000_000 ? Date.now() : numeric < 1_000_000_000_000 ? numeric * 1000 : numeric)
    : new Date(String(value));
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const metricDetail = (metric: any, fallback: string) => {
  if (!metric || typeof metric !== 'object') return fallback;
  return `${formatBytes(toNumber(metric.current))}/${formatBytes(toNumber(metric.total))}`;
};

const formatLoads = (loads: unknown, fallback: string) => {
  if (!Array.isArray(loads) || loads.length === 0) return fallback;
  return loads.slice(0, 3).map((item) => toNumber(item).toFixed(2)).join(' / ');
};

const toUiServer = (server: DashboardServerStatus): UiServer => {
  const isOnline = Boolean(server.available);
  const cpu = Number(server.system?.cpu ?? 0);
  const ramPercent = Number(server.system?.mem?.percent ?? 0);
  const diskPercent = Number(server.system?.disk?.percent ?? 0);
  return {
    nodeId: server.nodeId,
    name: server.node,
    status: isOnline ? 'online' : 'offline',
    latency: isOnline ? 'online' : 'No connection',
    cpu,
    ramPercent,
    ramDetail: server.system?.mem ? `${formatBytes(server.system.mem.current)}/${formatBytes(server.system.mem.total)}` : '-',
    diskPercent,
    diskDetail: server.system?.disk ? `${formatBytes(server.system.disk.current)}/${formatBytes(server.system.disk.total)}` : '-',
    network: `${formatBytes(server.network?.upload ?? 0)} / ${formatBytes(server.network?.download ?? 0)}`,
    uptime: formatUptime(server.xray?.uptime || server.system?.uptime),
    load: (server.system?.loads || []).slice(0, 3).map((item: number) => item.toFixed(2)).join(' / ') || '-',
    swap: server.system?.swap ? `${formatBytes(server.system.swap.current)}/${formatBytes(server.system.swap.total)}` : '-',
    core: server.xray?.version || server.panel_version || '26.4.17',
    lastSeen: formatLastSeen(server.timestamp),
    issue: server.error || server.reason,
    xrayCompatibility: server.xray_compatibility ? {
      status: server.xray_compatibility.status,
      warningCount: server.xray_compatibility.findings.reduce((sum, finding) => sum + finding.count, 0),
      codes: server.xray_compatibility.findings.map((finding) => finding.code),
    } : undefined,
  };
};

const normalizeXrayCompatibility = (value: unknown): UiServer['xrayCompatibility'] => {
  if (!value || typeof value !== 'object') return undefined;
  const raw = value as { status?: unknown; findings?: unknown };
  const findings = Array.isArray(raw.findings) ? raw.findings : [];
  const codes = findings
    .filter((finding): finding is { code: string; count?: unknown } => Boolean(finding) && typeof finding === 'object' && typeof (finding as { code?: unknown }).code === 'string')
    .map((finding) => finding.code);
  const warningCount = findings.reduce((sum, finding) => {
    const count = Number((finding as { count?: unknown })?.count);
    return sum + (Number.isFinite(count) ? count : 0);
  }, 0);
  return {
    status: raw.status === 'warning' ? 'warning' : raw.status === 'unknown' ? 'unknown' : 'ok',
    warningCount,
    codes,
  };
};

const mergeServerTelemetry = (server: UiServer, data: Record<string, any>): UiServer => {
  const system = data.system && typeof data.system === 'object' ? data.system : {};
  const xray = data.xray && typeof data.xray === 'object' ? data.xray : {};
  const network = data.network && typeof data.network === 'object' ? data.network : {};
  const available = data.available === undefined ? server.status === 'online' : Boolean(data.available);
  const status = data.status === 'offline' ? 'offline' : data.status === 'online' ? 'online' : available ? 'online' : 'offline';
  const pollMs = Number(data.poll_ms);
  const lastSeen = formatLastSeen(data.timestamp);

  return {
    ...server,
    nodeId: data.node_id !== undefined && data.node_id !== null ? Number(data.node_id) : server.nodeId,
    name: String(data.node || data.name || server.name),
    status,
    latency: status === 'online'
      ? Number.isFinite(pollMs) && pollMs > 0 ? `${Math.round(pollMs)}ms` : server.latency === 'No connection' ? 'online' : server.latency
      : 'No connection',
    cpu: toNumber(system.cpu ?? data.cpu, server.cpu),
    ramPercent: toNumber(system.mem?.percent, server.ramPercent),
    ramDetail: metricDetail(system.mem, server.ramDetail),
    diskPercent: toNumber(system.disk?.percent, server.diskPercent),
    diskDetail: metricDetail(system.disk, server.diskDetail),
    network: Object.keys(network).length > 0
      ? `${formatBytes(toNumber(network.upload))} / ${formatBytes(toNumber(network.download))}`
      : server.network,
    uptime: xray.uptime || system.uptime ? formatUptime(toNumber(xray.uptime || system.uptime)) : server.uptime,
    load: formatLoads(system.loads, server.load),
    swap: metricDetail(system.swap, server.swap),
    core: String(xray.version || data.panel_version || server.core),
    lastSeen: lastSeen === '-' ? server.lastSeen : lastSeen,
    issue: data.error || data.reason || (status === 'online' ? undefined : server.issue),
    xrayCompatibility: data.xray_compatibility === undefined
      ? server.xrayCompatibility
      : normalizeXrayCompatibility(data.xray_compatibility),
  };
};

export function ServerStatus({
  dashboardMode = false,
  includeCounts,
  includeCollectorStatus,
  includePanelUpdateChecks,
  includeLiveStatus = true,
  fleetSummary,
  fleetCollapsed = true,
  onToggleFleet,
}: ServerStatusProps) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const dashboardData = useDashboardData();
  const [servers, setServers] = useState<UiServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState(30);
  const [cardSort, setCardSort] = useState<SortMode>('name');
  const [pendingActions, setPendingActions] = useState<Record<string, boolean>>({});
  const [nodeOpsModal, setNodeOpsModal] = useState<{ nodeId: number; nodeName: string; tab: NodeOpsTab } | null>(null);
  const [logsModal, setLogsModal] = useState<{ nodeId: number; nodeName: string; kind: NodeLogKind } | null>(null);
  const closeLogsModal = useCallback(() => setLogsModal(null), []);
  void includeCounts;
  void includeCollectorStatus;

  const setActionPending = useCallback((key: string, pending: boolean) => {
    setPendingActions((current) => {
      const next = { ...current };
      if (pending) {
        next[key] = true;
      } else {
        delete next[key];
      }
      return next;
    });
  }, []);

  const getNodeActionError = useCallback((error: any) => {
    const detail = error?.response?.data?.detail || error?.response?.data?.error || error?.message;
    return detail ? String(detail) : t('common.failed');
  }, [t]);

  const loadServersStatus = useCallback(async () => {
    if (dashboardData) {
      setServers(dashboardFleetToServerDeck(dashboardData.fleet).servers.map(toUiServer));
      setLoadError(null);
      setLoading(dashboardData.loading);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const deck = await getDashboardServerDeck({
        includeLiveStatus,
        includePanelUpdateChecks: includePanelUpdateChecks ?? !dashboardMode,
      });
      const mapped = deck.servers.map(toUiServer);
      setServers(mapped);
    } catch {
      setServers([]);
      setLoadError(t('serverStatus.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [dashboardData, dashboardMode, includeLiveStatus, includePanelUpdateChecks, t]);

  const refreshDeck = useCallback(async () => {
    try {
      await refreshNodesNow();
    } catch {}
    if (dashboardData) await dashboardData.refresh();
    else await loadServersStatus();
  }, [dashboardData, loadServersStatus]);

  const requireNodeId = useCallback((server: UiServer): number | null => {
    if (server.nodeId !== undefined && Number.isFinite(server.nodeId)) {
      return server.nodeId;
    }
    toast(t('serverStatus.actionRequiresNodeId', { node: server.name }), 'warning');
    return null;
  }, [t, toast]);

  const runNodeCommand = useCallback(async (
    server: UiServer,
    action: NodeAction,
    command: (nodeId: number) => Promise<unknown>,
    successKey: string,
    failureKey: string,
  ) => {
    const nodeId = requireNodeId(server);
    if (nodeId === null) return;
    const key = nodeActionKey(server, action);
    setActionPending(key, true);
    try {
      await command(nodeId);
      toast(t(successKey, { node: server.name }), 'success');
      await loadServersStatus();
    } catch (error: any) {
      toast(`${t(failureKey, { node: server.name })}: ${getNodeActionError(error)}`, 'error');
    } finally {
      setActionPending(key, false);
    }
  }, [getNodeActionError, loadServersStatus, requireNodeId, setActionPending, t, toast]);

  const handleRestartXray = useCallback((server: UiServer) => {
    void runNodeCommand(server, 'restart', restartXray, 'serverStatus.restartSentNode', 'serverStatus.restartFailedNode');
  }, [runNodeCommand]);

  const handleStopXray = useCallback((server: UiServer) => {
    if (!window.confirm(t('serverStatus.confirmStopXrayNode', { node: server.name }))) return;
    void runNodeCommand(server, 'stop', stopXray, 'serverStatus.xrayStoppedNode', 'serverStatus.stopXrayFailedNode');
  }, [runNodeCommand, t]);

  const handleUpdateGeofile = useCallback((server: UiServer) => {
    void runNodeCommand(server, 'geofile', updateGeofile, 'serverStatus.geofileUpdatedNode', 'serverStatus.geofileUpdateFailedNode');
  }, [runNodeCommand]);

  const handleShowLogs = useCallback((server: UiServer, kind: NodeLogKind) => {
    const nodeId = requireNodeId(server);
    if (nodeId === null) return;
    setLogsModal({ nodeId, nodeName: server.name, kind });
  }, [requireNodeId]);

  const handleOpenNodeOps = useCallback((server: UiServer, tab: NodeOpsTab) => {
    const nodeId = requireNodeId(server);
    if (nodeId === null) return;
    setNodeOpsModal({ nodeId, nodeName: server.name, tab });
  }, [requireNodeId]);

  const handleRetryConnection = useCallback(async (server: UiServer) => {
    const key = nodeActionKey(server, 'restart');
    setActionPending(key, true);
    try {
      await refreshDeck();
      toast(t('serverStatus.refreshThisNode'), 'success');
    } catch (error: any) {
      toast(`${t('serverStatus.forceRefreshFailed')}: ${getNodeActionError(error)}`, 'error');
    } finally {
      setActionPending(key, false);
    }
  }, [getNodeActionError, refreshDeck, setActionPending, t, toast]);

  const handleCopyNodeSummary = useCallback(async (server: UiServer) => {
    const summary = [
      `${server.name}: ${server.status}`,
      `CPU ${server.cpu}%`,
      `RAM ${server.ramPercent}% (${server.ramDetail})`,
      `Disk ${server.diskPercent}% (${server.diskDetail})`,
      `Network ${server.network}`,
      `Core ${server.core}`,
      `Seen ${server.lastSeen}`,
    ].join('; ');
    try {
      await navigator.clipboard.writeText(summary);
      toast(t('serverStatus.fleetSummaryCopied'), 'success');
    } catch {
      toast(t('serverStatus.clipboardUnavailable'), 'error');
    }
  }, [t, toast]);

  const copyFleetSummary = useCallback(async () => {
    const summary = servers.map((server) => (
      `${server.name}: ${server.status}; CPU ${server.cpu}%; RAM ${server.ramPercent}%; Disk ${server.diskPercent}%; Core ${server.core}; Seen ${server.lastSeen}`
    )).join('\n');
    try {
      await navigator.clipboard.writeText(summary);
      toast(t('serverStatus.fleetSummaryCopied'), 'success');
    } catch {
      toast(t('serverStatus.clipboardUnavailable'), 'error');
    }
  }, [servers, t, toast]);

  const handleRestartAllXray = useCallback(async () => {
    const targets = servers.filter((server) => server.status === 'online' && server.nodeId !== undefined);
    if (targets.length === 0) {
      toast(t('serverStatus.noOnlineNodes'), 'warning');
      return;
    }
    if (!window.confirm(t('serverStatus.confirmRestartAll', { count: targets.length }))) return;
    const key = 'global:restart';
    setActionPending(key, true);
    let ok = 0;
    let fail = 0;
    for (const server of targets) {
      try {
        await restartXray(server.nodeId as number);
        ok += 1;
      } catch {
        fail += 1;
      }
    }
    toast(t('serverStatus.restartAllResult', { ok, fail }), ok > 0 ? 'success' : 'error');
    setActionPending(key, false);
    await loadServersStatus();
  }, [loadServersStatus, servers, setActionPending, t, toast]);

  const handleUpdateAllGeofiles = useCallback(async () => {
    const targets = servers.filter((server) => server.status === 'online' && server.nodeId !== undefined);
    if (targets.length === 0) {
      toast(t('serverStatus.noOnlineNodes'), 'warning');
      return;
    }
    if (!window.confirm(t('serverStatus.confirmUpdateGeofileAll', { count: targets.length }))) return;
    const key = 'global:geofile';
    setActionPending(key, true);
    let ok = 0;
    let fail = 0;
    for (const server of targets) {
      try {
        await updateGeofile(server.nodeId as number);
        ok += 1;
      } catch {
        fail += 1;
      }
    }
    toast(
      ok > 0 ? t('serverStatus.geofileUpdatedAll', { count: ok }) : t('serverStatus.updateGeofileAllFailed', { fail }),
      ok > 0 ? 'success' : 'error',
    );
    setActionPending(key, false);
    await loadServersStatus();
  }, [loadServersStatus, servers, setActionPending, t, toast]);

  const applyServerTelemetry = useCallback((rawData: Record<string, any>) => {
    const data = rawData.snapshot && typeof rawData.snapshot === 'object'
      ? { ...rawData.snapshot, ...rawData }
      : rawData;
    const nodeName = String(data.node || data.name || '');
    const nodeId = data.node_id !== undefined && data.node_id !== null ? Number(data.node_id) : null;

    setServers((current) => {
      let matched = false;
      const next = current.map((server) => {
        const byId = nodeId !== null && server.nodeId !== undefined && Number(server.nodeId) === nodeId;
        const byName = Boolean(nodeName) && server.name === nodeName;
        if (!byId && !byName) return server;
        matched = true;
        return mergeServerTelemetry(server, data);
      });

      if (matched || !nodeName) {
        return next;
      }

      return [
        ...next,
        toUiServer({
          nodeId: nodeId ?? undefined,
          node: nodeName,
          available: Boolean(data.available),
          status: data.status,
          reason: data.reason,
          error: data.error,
          timestamp: data.timestamp,
          system: data.system,
          xray: data.xray,
          network: data.network,
          panel_version: data.panel_version,
          api_version: data.api_version,
        }),
      ];
    });
    setLoadError(null);
    setLoading(false);
  }, []);

  const handleRealtimeUpdate = useCallback((update: TrafficUpdate) => {
    if (update.type !== 'server_status') return;
    if (!update.data || typeof update.data !== 'object') return;
    applyServerTelemetry(update.data);
  }, [applyServerTelemetry]);

  useEffect(() => {
    loadServersStatus();
  }, [loadServersStatus]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(loadServersStatus, refreshInterval * 1000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, refreshInterval, loadServersStatus]);

  useTrafficStatsSubscription({
    enabled: !dashboardData,
    channels: ['server_status'],
    onUpdate: handleRealtimeUpdate,
    onError: (err) => console.warn('[ServerStatus] realtime error:', err),
    fallbackPollIntervalMs: 60_000,
    fallbackRun: loadServersStatus,
  });

  const sortedServers = useMemo(() => {
    return [...servers].sort((a, b) => {
      if (cardSort === 'name') return a.name.localeCompare(b.name);
      if (cardSort === 'cpu') return b.cpu - a.cpu;
      if (cardSort === 'status') return Number(b.status === 'online') - Number(a.status === 'online');
      return b.ramPercent - a.ramPercent;
    });
  }, [cardSort, servers]);

  const online = servers.filter((server) => server.status === 'online').length;
  const offline = servers.filter((server) => server.status === 'offline').length;
  const avgCpu = online > 0 ? servers.reduce((sum, server) => sum + server.cpu, 0) / servers.length : 0;

  return (
    <>
    <section className={dashboardMode ? 'pb-6' : 'px-6 pb-6'}>
      <div className="overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] shadow-[inset_0_1px_0_rgba(103,232,249,0.05)] backdrop-blur-sm">
        <div className="border-b border-cyan-500/20 bg-cyan-500/5 p-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="font-mono text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">{t('serverStatus.title').toUpperCase()}</h2>
              <span className="font-mono text-xs font-light text-gray-400">{online}/{servers.length} online</span>
              <span className="rounded border border-green-300/20 bg-green-400/10 px-2 py-0.5 font-mono text-[10px] font-light text-green-300">
                {loading || fleetSummary?.loading ? 'syncing' : 'active'}
              </span>
            </div>
          </div>

          <div className="server-status__control-row grid grid-cols-1 gap-2 mb-2 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
            <div className="flex w-full items-center gap-1.5 min-h-7 overflow-x-auto scrollbar-none">
              <span className="text-[10px] text-gray-400 font-mono flex-shrink-0">Sort:</span>
              {(['name', 'cpu', 'status', 'clients'] as const).map((sort) => (
                <button
                  key={sort}
                  className={`h-7 flex-shrink-0 rounded border px-2.5 font-mono text-[10px] font-light transition-colors duration-200 ${
                    cardSort === sort ? 'border-cyan-300/30 bg-cyan-500/15 text-cyan-300' : 'border-cyan-500/0 text-gray-400 hover:border-cyan-300/20 hover:bg-cyan-400/5 hover:text-cyan-300'
                  }`}
                  onClick={() => setCardSort(sort)}
                  type="button"
                >
                  {sort}
                </button>
              ))}
            </div>
            <div className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-2 min-h-7 xl:flex xl:justify-end">
              <label className="flex min-w-0 items-center gap-1.5 font-mono text-[10px] font-light text-gray-400">
                <input type="checkbox" className="w-3 h-3 flex-shrink-0" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
                <span className="truncate">{t('serverStatus.autoRefresh')}</span>
              </label>
              <select
                className="h-7 flex-shrink-0 rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-gray-400"
                value={refreshInterval}
                onChange={(event) => setRefreshInterval(Number(event.target.value))}
                aria-label={t('serverStatus.autoRefresh')}
              >
                {[10, 15, 30, 60, 120, 300].map((seconds) => (
                  <option key={seconds} value={seconds}>{seconds}s</option>
                ))}
              </select>
              <button
                className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded border border-cyan-300/25 bg-gradient-to-r from-cyan-400/90 to-fuchsia-400/90 text-white disabled:opacity-50"
                onClick={refreshDeck}
                disabled={loading}
                type="button"
                title="Refresh"
                aria-label="Refresh"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              </button>
              {onToggleFleet && (
                <button
                  onClick={onToggleFleet}
                  className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded border border-cyan-500/20 bg-[#0a0e1a]"
                  title={t('nodes.registeredFleet')}
                  aria-label={t('nodes.registeredFleet')}
                  type="button"
                >
                  {fleetCollapsed ? <ChevronLeft className="w-4 h-4 text-cyan-300" /> : <ChevronRight className="w-4 h-4 text-cyan-300" />}
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 xl:flex gap-1.5 mb-2">
            <button
              className="h-6 px-3 bg-[#0a0e1a] text-amber-300/80 border border-amber-400/25 rounded-md text-[10px] font-mono hover:bg-amber-400/5 hover:border-amber-300/40 transition-colors duration-200 whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              title={t('serverStatus.restartAllTitle')}
              onClick={handleRestartAllXray}
              disabled={Boolean(pendingActions['global:restart'])}
            >
              {t('serverStatus.restartAllXray')}
            </button>
            <button
              className="h-6 px-3 bg-[#0a0e1a] text-cyan-300/80 border border-cyan-300/25 rounded-md text-[10px] font-mono hover:bg-cyan-400/5 hover:border-cyan-300/40 transition-colors duration-200 whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              title={t('serverStatus.updateAllGeofilesTitle')}
              onClick={handleUpdateAllGeofiles}
              disabled={Boolean(pendingActions['global:geofile'])}
            >
              {t('serverStatus.updateAllGeofiles')}
            </button>
            <button
              className="h-6 px-3 bg-[#0a0e1a] text-cyan-300/75 border border-cyan-300/20 rounded-md text-[10px] font-mono hover:bg-cyan-400/5 hover:border-cyan-300/35 transition-colors duration-200 whitespace-nowrap"
              type="button"
              title={t('serverStatus.copyFleetSummaryTitle')}
              onClick={copyFleetSummary}
            >
              {t('serverStatus.copySummary')}
            </button>
          </div>

          <div className="server-status__stat-grid grid grid-cols-2 sm:grid-cols-3 xl:flex xl:flex-wrap gap-1.5">
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-green-400">Online: <strong className="ml-1 font-medium">{fleetSummary?.online ?? online}/{fleetSummary?.total ?? servers.length}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-yellow-400">Errors: <strong className="ml-1 font-medium">{fleetSummary?.checking ?? 2}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-red-400">Offline: <strong className="ml-1 font-medium">{fleetSummary?.offline ?? offline}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-green-400">{t('serverStatus.avgCpu')}: <strong className="ml-1 font-medium">{avgCpu.toFixed(1)}%</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-green-400">{t('serverStatus.fleetRam')}: <strong className="ml-1 font-medium">{'10.4/19.2 GB'}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-gray-300">{t('serverStatus.onlineClients')}: <strong className="ml-1 font-medium">{formatOnlineClients(fleetSummary?.onlineClients)}</strong></span>
          </div>
        </div>

        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,22rem),1fr))] gap-3 p-3">
          {sortedServers.length > 0 ? (
            sortedServers.map((server) => (
              <ServerCard
                key={server.name}
                server={server}
                onRestartXray={handleRestartXray}
                onStopXray={handleStopXray}
                onUpdateGeofile={handleUpdateGeofile}
                onShowLogs={handleShowLogs}
                onOpenNodeOps={handleOpenNodeOps}
                onRetryConnection={handleRetryConnection}
                onCopyNodeSummary={handleCopyNodeSummary}
                isActionPending={(action) => Boolean(pendingActions[nodeActionKey(server, action)])}
              />
            ))
          ) : (
            <div className="col-span-full flex min-h-[286px] items-center justify-center rounded-lg border border-dashed border-cyan-500/15 bg-[#0a0e1a]/70 px-4 py-10 text-center shadow-[inset_0_1px_0_rgba(103,232,249,0.03)]">
              <div className="max-w-md">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-500/10 text-cyan-300">
                  {loading ? <RefreshCw className="h-5 w-5 animate-spin" /> : <Network className="h-5 w-5" />}
                </div>
                <div className="font-mono text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">
                  {loading ? t('serverStatus.loadingLiveMetrics') : t('common.noRecordsFound')}
                </div>
                <p className="mt-2 text-sm font-light leading-6 text-gray-400">
                  {loading
                    ? t('dashboardSummary.signalDeckCopy')
                    : loadError || t('serverStatus.noServers', { defaultValue: 'No active servers registered' })}
                </p>
                {!loading && (
                  <button
                    className="mt-4 inline-flex h-8 items-center gap-1.5 rounded border border-cyan-300/25 bg-[#0f1420] px-3 font-mono text-xs font-light text-cyan-200 transition-colors duration-200 hover:border-cyan-300/40 hover:text-cyan-100"
                    onClick={refreshDeck}
                    type="button"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    <span>{t('common.refresh')}</span>
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
    {nodeOpsModal && (
      <NodeOperationsModal
        nodeId={nodeOpsModal.nodeId}
        nodeName={nodeOpsModal.nodeName}
        initialTab={nodeOpsModal.tab}
        onClose={() => setNodeOpsModal(null)}
        onNodeChanged={() => void loadServersStatus()}
      />
    )}
    {logsModal && (
      <ServerLogsModal
        open
        nodeId={logsModal.nodeId}
        nodeName={logsModal.nodeName}
        kind={logsModal.kind}
        onClose={closeLogsModal}
      />
    )}
    </>
  );
}

function ServerCard({
  server,
  onRestartXray,
  onStopXray,
  onUpdateGeofile,
  onShowLogs,
  onOpenNodeOps,
  onRetryConnection,
  onCopyNodeSummary,
  isActionPending,
}: {
  server: UiServer;
  onRestartXray: (server: UiServer) => void;
  onStopXray: (server: UiServer) => void;
  onUpdateGeofile: (server: UiServer) => void;
  onShowLogs: (server: UiServer, kind: NodeLogKind) => void;
  onOpenNodeOps: (server: UiServer, tab: NodeOpsTab) => void;
  onRetryConnection: (server: UiServer) => void;
  onCopyNodeSummary: (server: UiServer) => void;
  isActionPending: (action: NodeAction) => boolean;
}) {
  const { t } = useTranslation();
  const isOffline = server.status === 'offline';
  const restartPending = isActionPending('restart');
  const stopPending = isActionPending('stop');
  const geofilePending = isActionPending('geofile');
  const xrayLogsPending = isActionPending('xrayLogs');
  const serverLogsPending = isActionPending('serverLogs');
  const compatibility = server.xrayCompatibility;
  const metaItems: ServerMetaItem[] = [
    { label: 'Net', value: server.network, icon: <Network className="w-3.5 h-3.5" /> },
    { label: 'Uptime', value: server.uptime, icon: <Timer className="w-3.5 h-3.5" /> },
    { label: 'Load', value: server.load, icon: <Gauge className="w-3.5 h-3.5" /> },
    { label: 'Swap', value: server.swap, icon: <HardDrive className="w-3.5 h-3.5" /> },
    { label: 'Ping', value: server.latency, icon: <Activity className="w-3.5 h-3.5" />, tone: isOffline ? 'text-red-300/70' : 'text-amber-300/75' },
    { label: 'Seen', value: server.lastSeen, icon: <CheckCircle className="w-3.5 h-3.5" /> },
  ];

  return (
    <article className="flex min-h-[286px] flex-col overflow-hidden rounded-lg border border-cyan-500/10 bg-[#0a0e1a] p-3 shadow-[inset_0_1px_0_rgba(103,232,249,0.04)] transition-colors duration-200 hover:border-cyan-400/20">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${isOffline ? 'bg-red-400' : 'bg-green-400'}`} />
          <span className="truncate font-mono text-base font-medium text-white">{server.name}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-nowrap justify-end">
          <span className={`rounded border px-1.5 py-px font-mono text-[10px] font-light leading-tight ${isOffline ? 'border-red-300/20 bg-red-950/60 text-red-300/80' : 'border-emerald-300/20 bg-emerald-950/60 text-emerald-300/80'}`}>
            {server.status}
          </span>
          <span className={`rounded border px-1.5 py-px font-mono text-[10px] font-light leading-tight ${isOffline ? 'border-red-300/20 bg-red-950/45 text-red-300/75' : 'border-amber-300/20 bg-amber-950/55 text-amber-300/80'}`}>
            {server.latency}
          </span>
        </div>
      </div>

      <div className="space-y-2 mb-2">
        <MetricRow label={t('serverStatus.cpu')} value={server.cpu} valueText={`${server.cpu}%`} color={server.cpu > 50 ? 'from-yellow-400 to-amber-400' : 'from-green-400 to-emerald-400'} />
        <MetricRow label={t('serverStatus.ram')} value={server.ramPercent} valueText={`${server.ramPercent}%`} detail={server.ramDetail} color={server.ramPercent > 50 ? 'from-yellow-400 to-amber-400' : 'from-green-400 to-emerald-400'} />
        <MetricRow label={t('serverStatus.disk')} value={server.diskPercent} valueText={`${server.diskPercent}%`} detail={server.diskDetail} color="from-green-400 to-emerald-400" />
      </div>

      {compatibility?.status === 'warning' && (
        <div
          className="mb-2 rounded border border-amber-400/25 bg-amber-950/35 px-2 py-1 font-mono text-[10px] text-amber-200"
          title={compatibility.codes.join(', ')}
        >
          Xray compatibility: {compatibility.warningCount} warning(s)
        </div>
      )}

      <div className="mb-2 grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[10px] font-light text-gray-500">
        {metaItems.map((item) => (
          <div key={item.label} className="grid grid-cols-[auto_minmax(34px,1fr)_minmax(0,1.4fr)] items-center gap-1.5 min-w-0">
            <span className="text-gray-500/60 flex items-center justify-center">{item.icon}</span>
            <span className="text-gray-500 uppercase tracking-wide">{item.label}</span>
            <span className={`text-right truncate ${item.tone || 'text-gray-400'}`} title={item.value}>{item.value}</span>
          </div>
        ))}
      </div>

      <div className="mt-auto h-[73px] overflow-hidden border-t border-cyan-500/10 pt-2">
        {isOffline ? (
          <div className="text-center py-1.5">
            <div className="mb-1 font-mono text-sm font-light text-red-400">{server.issue || 'Connection Lost'}</div>
            <div className="font-mono text-xs font-light text-gray-500">Last seen: {server.lastSeen}</div>
            <button
              className="mt-1.5 rounded border border-cyan-500/20 bg-[#0f1420] px-3 py-1 font-mono text-xs font-light text-gray-300 transition-colors duration-200 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              onClick={() => onRetryConnection(server)}
              disabled={restartPending}
            >
              {t('serverStatus.retryConnection')}
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-xs font-light text-gray-400">Core {server.core}</span>
                <span className="w-4 h-4 bg-emerald-950/80 rounded-full flex items-center justify-center">
                  <CheckCircle className="w-3 h-3 text-emerald-300/70" />
                </span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  className="flex h-6 w-6 items-center justify-center rounded border border-cyan-500/20 bg-[#0f1420] text-gray-500 transition-colors duration-200 hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
                  title={t('serverStatus.restartXray')}
                  aria-label={t('serverStatus.restartXray')}
                  type="button"
                  onClick={() => onRestartXray(server)}
                  disabled={restartPending}
                >
                  <RotateCcw className={`w-3.5 h-3.5 opacity-60 ${restartPending ? 'animate-spin' : ''}`} />
                </button>
                <button
                  className="flex h-6 w-6 items-center justify-center rounded border border-cyan-500/20 bg-[#0f1420] text-gray-500 transition-colors duration-200 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                  title={t('serverStatus.stopXray')}
                  aria-label={t('serverStatus.stopXray')}
                  type="button"
                  onClick={() => onStopXray(server)}
                  disabled={stopPending}
                >
                  <Square className="w-3.5 h-3.5 opacity-60" />
                </button>
                <button
                  className="h-6 rounded border border-cyan-500/20 bg-[#0f1420] px-2 font-mono text-[10px] font-light text-gray-400 transition-colors duration-200 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                  title={t('serverStatus.serverLogsTitle', { node: server.name })}
                  type="button"
                  onClick={() => onShowLogs(server, 'panel')}
                  disabled={serverLogsPending}
                >
                  {t('serverStatus.logs')}
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-1">
              <IconAction icon={restartPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />} title="Play" onClick={() => onRestartXray(server)} disabled={restartPending} />
              <IconAction icon={<Pause className="w-3 h-3" />} title="Pause" onClick={() => onStopXray(server)} disabled={stopPending} />
              <IconAction icon={<Clipboard className="w-3 h-3" />} title={t('serverStatus.copySummary')} onClick={() => onCopyNodeSummary(server)} />
              <IconAction icon={<KeyRound className="w-3 h-3" />} title={t('serverStatus.keyGenerator')} onClick={() => onOpenNodeOps(server, 'keys')} />
              <IconAction icon={<LineChart className="w-3 h-3" />} title="Metrics" onClick={() => onOpenNodeOps(server, 'traffic')} />
              <IconAction
                icon={geofilePending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Shield className="w-3 h-3" />}
                title={t('serverStatus.updateGeofiles')}
                onClick={() => onUpdateGeofile(server)}
                disabled={geofilePending}
              />
              <IconAction
                icon={xrayLogsPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <FileText className="w-3 h-3" />}
                title={t('serverStatus.xrayLogsTitle', { node: server.name })}
                onClick={() => onShowLogs(server, 'xray')}
                disabled={xrayLogsPending}
              />
              <IconAction icon={<Settings className="w-3 h-3" />} title="Config" onClick={() => onOpenNodeOps(server, 'config')} />
            </div>
          </>
        )}
      </div>
    </article>
  );
}

function MetricRow({
  label,
  value,
  valueText,
  detail,
  color,
}: {
  label: string;
  value: number;
  valueText: string;
  detail?: string;
  color: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-1 whitespace-nowrap">
        <span className="font-mono text-[11px] font-light leading-none text-gray-400">{label}</span>
        <span className="text-right font-mono text-[11px] font-medium leading-none text-green-400">
          {valueText}
          {detail && <span className="ml-1.5 text-[10px] font-light text-gray-500">{detail}</span>}
        </span>
      </div>
      <div className="w-full h-[3px] bg-[#1b2638] rounded-full overflow-hidden">
        <div className={`h-full rounded-full bg-gradient-to-r ${color} ${getWidthClass(value)}`} />
      </div>
    </div>
  );
}

function IconAction({
  icon,
  title,
  onClick,
  disabled = false,
}: {
  icon: ReactNode;
  title: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      className="flex h-6 w-6 items-center justify-center rounded border border-cyan-500/20 bg-[#0f1420] text-gray-500 transition-colors duration-200 hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
      title={title}
      aria-label={title}
      type="button"
      onClick={onClick}
      disabled={disabled}
    >
      <span className="opacity-60">{icon}</span>
    </button>
  );
}
