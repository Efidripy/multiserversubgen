import { useEffect, useMemo, useState, type ReactNode } from 'react';
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
import { getDashboardServerDeck, type DashboardServerStatus } from '../api/dashboard';
import { refreshNodesNow } from '../api/nodes';

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
  };
  fleetCollapsed?: boolean;
  onToggleFleet?: () => void;
}

type SortMode = 'name' | 'cpu' | 'status' | 'clients';

type UiServer = {
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
};

type ServerMetaItem = {
  label: string;
  value: string;
  icon: ReactNode;
  tone?: string;
};

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

const toUiServer = (server: DashboardServerStatus): UiServer => {
  const isOnline = Boolean(server.available);
  const cpu = Number(server.system?.cpu ?? 0);
  const ramPercent = Number(server.system?.mem?.percent ?? 0);
  const diskPercent = Number(server.system?.disk?.percent ?? 0);
  return {
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
    core: server.xray?.version || '26.4.17',
    lastSeen: server.timestamp ? new Date(server.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-',
    issue: server.error || server.reason,
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
  const [servers, setServers] = useState<UiServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState(30);
  const [cardSort, setCardSort] = useState<SortMode>('name');
  void includeCounts;
  void includeCollectorStatus;

  const loadServersStatus = async () => {
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
  };

  const refreshDeck = async () => {
    try {
      await refreshNodesNow();
    } catch {}
    await loadServersStatus();
  };

  useEffect(() => {
    loadServersStatus();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(loadServersStatus, refreshInterval * 1000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, refreshInterval, includeLiveStatus, includePanelUpdateChecks, dashboardMode]);

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
            <button className="h-6 px-3 bg-[#0a0e1a] text-amber-300/80 border border-amber-400/25 rounded-md text-[10px] font-mono hover:bg-amber-400/5 hover:border-amber-300/40 transition-colors duration-200 whitespace-nowrap" type="button">
              {t('serverStatus.restartAllXray')}
            </button>
            <button className="h-6 px-3 bg-[#0a0e1a] text-cyan-300/80 border border-cyan-300/25 rounded-md text-[10px] font-mono hover:bg-cyan-400/5 hover:border-cyan-300/40 transition-colors duration-200 whitespace-nowrap" type="button">
              {t('serverStatus.updateAllGeofiles')}
            </button>
            <button className="h-6 px-3 bg-[#0a0e1a] text-cyan-300/75 border border-cyan-300/20 rounded-md text-[10px] font-mono hover:bg-cyan-400/5 hover:border-cyan-300/35 transition-colors duration-200 whitespace-nowrap" type="button">
              {t('serverStatus.copySummary')}
            </button>
          </div>

          <div className="server-status__stat-grid grid grid-cols-2 sm:grid-cols-3 xl:flex xl:flex-wrap gap-1.5">
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-green-400">Online: <strong className="ml-1 font-medium">{fleetSummary?.online ?? online}/{fleetSummary?.total ?? servers.length}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-yellow-400">Errors: <strong className="ml-1 font-medium">{fleetSummary?.checking ?? 2}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-red-400">Offline: <strong className="ml-1 font-medium">{fleetSummary?.offline ?? offline}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-green-400">{t('serverStatus.avgCpu')}: <strong className="ml-1 font-medium">{avgCpu.toFixed(1)}%</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-green-400">{t('serverStatus.fleetRam')}: <strong className="ml-1 font-medium">{'10.4/19.2 GB'}</strong></span>
            <span className="flex h-6 items-center justify-center whitespace-nowrap rounded border border-cyan-500/20 bg-[#0a0e1a] px-2 font-mono text-[10px] font-light text-gray-300">{t('serverStatus.onlineClients')}: <strong className="ml-1 font-medium">-</strong></span>
          </div>
        </div>

        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,22rem),1fr))] gap-3 p-3">
          {sortedServers.length > 0 ? (
            sortedServers.map((server) => (
              <ServerCard key={server.name} server={server} />
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
  );
}

function ServerCard({ server }: { server: UiServer }) {
  const { t } = useTranslation();
  const isOffline = server.status === 'offline';
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
        <MetricRow label="CPU Usage" value={server.cpu} valueText={`${server.cpu}%`} color={server.cpu > 50 ? 'from-yellow-400 to-amber-400' : 'from-green-400 to-emerald-400'} />
        <MetricRow label="RAM Usage" value={server.ramPercent} valueText={`${server.ramPercent}%`} detail={server.ramDetail} color={server.ramPercent > 50 ? 'from-yellow-400 to-amber-400' : 'from-green-400 to-emerald-400'} />
        <MetricRow label="Disk Usage" value={server.diskPercent} valueText={`${server.diskPercent}%`} detail={server.diskDetail} color="from-green-400 to-emerald-400" />
      </div>

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
            <button className="mt-1.5 rounded border border-cyan-500/20 bg-[#0f1420] px-3 py-1 font-mono text-xs font-light text-gray-300 transition-colors duration-200 hover:text-cyan-200" type="button">
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
                <button className="flex h-6 w-6 items-center justify-center rounded border border-cyan-500/20 bg-[#0f1420] text-gray-500 transition-colors duration-200 hover:text-cyan-300" title={t('serverStatus.restartXray')} type="button">
                  <RotateCcw className="w-3.5 h-3.5 opacity-60" />
                </button>
                <button className="flex h-6 w-6 items-center justify-center rounded border border-cyan-500/20 bg-[#0f1420] text-gray-500 transition-colors duration-200 hover:text-red-300" title={t('serverStatus.stopXray')} type="button">
                  <Square className="w-3.5 h-3.5 opacity-60" />
                </button>
                <button className="h-6 rounded border border-cyan-500/20 bg-[#0f1420] px-2 font-mono text-[10px] font-light text-gray-400 transition-colors duration-200 hover:text-cyan-200" title="Logs" type="button">
                  Logs
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-1">
              <IconAction icon={<Play className="w-3 h-3" />} title="Play" />
              <IconAction icon={<Pause className="w-3 h-3" />} title="Pause" />
              <IconAction icon={<Clipboard className="w-3 h-3" />} title={t('serverStatus.copySummary')} />
              <IconAction icon={<KeyRound className="w-3 h-3" />} title={t('serverStatus.keyGenerator')} />
              <IconAction icon={<LineChart className="w-3 h-3" />} title="Metrics" />
              <IconAction icon={<Shield className="w-3 h-3" />} title="Geofiles" />
              <IconAction icon={<FileText className="w-3 h-3" />} title="Logs" />
              <IconAction icon={<Settings className="w-3 h-3" />} title="Config" />
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

function IconAction({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <button
      className="flex h-6 w-6 items-center justify-center rounded border border-cyan-500/20 bg-[#0f1420] text-gray-500 transition-colors duration-200 hover:text-cyan-300"
      title={title}
      aria-label={title}
      type="button"
    >
      <span className="opacity-60">{icon}</span>
    </button>
  );
}
