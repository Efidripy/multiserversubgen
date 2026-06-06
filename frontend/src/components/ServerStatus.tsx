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

const fallbackServers: UiServer[] = [
  {
    name: 'DE 82-FR',
    status: 'online',
    latency: 'online',
    cpu: 0,
    ramPercent: 0,
    ramDetail: '0 MB/1000 MB',
    diskPercent: 0,
    diskDetail: '0 MB/10000 MB',
    network: '0 GB / 0 GB',
    uptime: '-',
    load: '- / - / -',
    swap: '0 B/512 MB',
    core: '26.4.17',
    lastSeen: '12:00 AM',
  },
  {
    name: 'EE 5-EE',
    status: 'online',
    latency: '3559ms',
    cpu: 8.27,
    ramPercent: 55.77,
    ramDetail: '536 MB/961 MB',
    diskPercent: 46.7,
    diskDetail: '3170 MB/6790 MB',
    network: '91.31 GB / 89.86 GB',
    uptime: '14h 59m',
    load: '0.04 / 0.10 / 0.09',
    swap: '0 B/512 MB',
    core: '26.4.17',
    lastSeen: '9:00:44 PM',
  },
  {
    name: 'NL 146-AM-E',
    status: 'offline',
    latency: 'No connection',
    cpu: 0,
    ramPercent: 0,
    ramDetail: '0 MB/961 MB',
    diskPercent: 0,
    diskDetail: '0 MB/29440 MB',
    network: '-',
    uptime: '-',
    load: '- / - / -',
    swap: '-',
    core: '-',
    lastSeen: '2h ago',
    issue: 'Connection Lost',
  },
  {
    name: 'RU 185-RF-E',
    status: 'online',
    latency: '2145ms',
    cpu: 5.2,
    ramPercent: 46.3,
    ramDetail: '445 MB/961 MB',
    diskPercent: 41,
    diskDetail: '8200 MB/20000 MB',
    network: '32.1 GB / 78.4 GB',
    uptime: '5h 33m',
    load: '0.06 / 0.08 / 0.07',
    swap: '0 B/512 MB',
    core: '26.4.17',
    lastSeen: '9:00:45 PM',
  },
];

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
  const [servers, setServers] = useState<UiServer[]>(fallbackServers);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState(30);
  const [cardSort, setCardSort] = useState<SortMode>('name');
  void includeCounts;
  void includeCollectorStatus;

  const loadServersStatus = async () => {
    setLoading(true);
    try {
      const deck = await getDashboardServerDeck({
        includeLiveStatus,
        includePanelUpdateChecks: includePanelUpdateChecks ?? !dashboardMode,
      });
      const mapped = deck.servers.map(toUiServer);
      setServers(mapped.length > 0 ? mapped.slice(0, 4) : fallbackServers);
    } catch {
      setServers(fallbackServers);
    } finally {
      setLoading(false);
    }
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
      <div className="bg-[#0f1420] rounded-lg overflow-hidden">
        <div className="p-3 bg-[#0d1b2b]">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-bold text-cyan-300 font-mono uppercase tracking-wider">{t('serverStatus.title').toUpperCase()}</h2>
              <span className="text-xs text-gray-400 font-mono">{online}/{servers.length} online</span>
              <span className="px-2 py-0.5 bg-green-400/20 text-green-300 rounded text-[10px] font-mono">
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
                  className={`h-7 px-2.5 rounded text-[10px] font-mono transition-colors duration-200 flex-shrink-0 ${
                    cardSort === sort ? 'bg-cyan-500/20 text-cyan-300' : 'text-gray-400 hover:bg-cyan-400/5 hover:text-cyan-300'
                  }`}
                  onClick={() => setCardSort(sort)}
                  type="button"
                >
                  {sort}
                </button>
              ))}
            </div>
            <div className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-2 min-h-7 xl:flex xl:justify-end">
              <label className="flex min-w-0 items-center gap-1.5 text-[10px] text-gray-400 font-mono">
                <input type="checkbox" className="w-3 h-3 flex-shrink-0" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
                <span className="truncate">{t('serverStatus.autoRefresh')}</span>
              </label>
              <select
                className="h-7 bg-[#0a0e1a] rounded px-2 text-[10px] text-gray-400 font-mono flex-shrink-0"
                value={refreshInterval}
                onChange={(event) => setRefreshInterval(Number(event.target.value))}
                aria-label={t('serverStatus.autoRefresh')}
              >
                {[10, 15, 30, 60, 120, 300].map((seconds) => (
                  <option key={seconds} value={seconds}>{seconds}s</option>
                ))}
              </select>
              <button
                className="w-7 h-7 bg-gradient-to-r from-cyan-400/90 to-fuchsia-400/90 text-white rounded flex items-center justify-center disabled:opacity-50 flex-shrink-0"
                onClick={async () => {
                  try {
                    await refreshNodesNow();
                  } catch {}
                  await loadServersStatus();
                }}
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
                  className="w-7 h-7 bg-[#0a0e1a] rounded flex items-center justify-center flex-shrink-0"
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
            <span className="h-6 px-2 bg-[#0a0e1a] text-green-400 rounded text-[10px] font-mono flex items-center justify-center whitespace-nowrap">Online: <strong>{fleetSummary?.online ?? online}/{fleetSummary?.total ?? servers.length}</strong></span>
            <span className="h-6 px-2 bg-[#0a0e1a] text-yellow-400 rounded text-[10px] font-mono flex items-center justify-center whitespace-nowrap">Errors: <strong>{fleetSummary?.checking ?? 2}</strong></span>
            <span className="h-6 px-2 bg-[#0a0e1a] text-red-400 rounded text-[10px] font-mono flex items-center justify-center whitespace-nowrap">Offline: <strong>{fleetSummary?.offline ?? offline}</strong></span>
            <span className="h-6 px-2 bg-[#0a0e1a] text-green-400 rounded text-[10px] font-mono flex items-center justify-center whitespace-nowrap">{t('serverStatus.avgCpu')}: <strong>{avgCpu.toFixed(1)}%</strong></span>
            <span className="h-6 px-2 bg-[#0a0e1a] text-green-400 rounded text-[10px] font-mono flex items-center justify-center whitespace-nowrap">{t('serverStatus.fleetRam')}: <strong>{'10.4/19.2 GB'}</strong></span>
            <span className="h-6 px-2 bg-[#0a0e1a] text-gray-300 rounded text-[10px] font-mono flex items-center justify-center whitespace-nowrap">{t('serverStatus.onlineClients')}: <strong>-</strong></span>
          </div>
        </div>

        <div className="p-3 grid gap-3 grid-cols-1 md:grid-cols-2">
          {sortedServers.map((server) => (
            <ServerCard key={server.name} server={server} />
          ))}
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
    <article className="min-h-[286px] bg-[#0a0e1a] rounded-lg p-3 flex flex-col overflow-hidden">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${isOffline ? 'bg-red-400' : 'bg-green-400'}`} />
          <span className="text-base font-bold text-white font-mono truncate">{server.name}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-nowrap justify-end">
          <span className={`px-1.5 py-px rounded-sm text-[10px] font-mono leading-tight ${isOffline ? 'bg-red-950/70 text-red-300/80' : 'bg-emerald-950/70 text-emerald-300/80'}`}>
            {server.status}
          </span>
          <span className={`px-1.5 py-px rounded-sm text-[10px] font-mono leading-tight ${isOffline ? 'bg-red-950/50 text-red-300/75' : 'bg-amber-950/60 text-amber-300/80'}`}>
            {server.latency}
          </span>
        </div>
      </div>

      <div className="space-y-2 mb-2">
        <MetricRow label="CPU Usage" value={server.cpu} valueText={`${server.cpu}%`} color={server.cpu > 50 ? 'from-yellow-400 to-amber-400' : 'from-green-400 to-emerald-400'} />
        <MetricRow label="RAM Usage" value={server.ramPercent} valueText={`${server.ramPercent}%`} detail={server.ramDetail} color={server.ramPercent > 50 ? 'from-yellow-400 to-amber-400' : 'from-green-400 to-emerald-400'} />
        <MetricRow label="Disk Usage" value={server.diskPercent} valueText={`${server.diskPercent}%`} detail={server.diskDetail} color="from-green-400 to-emerald-400" />
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-gray-500 font-mono mb-2">
        {metaItems.map((item) => (
          <div key={item.label} className="grid grid-cols-[auto_minmax(34px,1fr)_minmax(0,1.4fr)] items-center gap-1.5 min-w-0">
            <span className="text-gray-500/60 flex items-center justify-center">{item.icon}</span>
            <span className="text-gray-500 uppercase tracking-wide">{item.label}</span>
            <span className={`text-right truncate ${item.tone || 'text-gray-400'}`} title={item.value}>{item.value}</span>
          </div>
        ))}
      </div>

      <div className="mt-auto h-[73px] pt-2 border-t border-slate-800/60 overflow-hidden">
        {isOffline ? (
          <div className="text-center py-1.5">
            <div className="text-red-400 text-sm font-mono mb-1">{server.issue || 'Connection Lost'}</div>
            <div className="text-gray-500 text-xs font-mono">Last seen: {server.lastSeen}</div>
            <button className="mt-1.5 px-3 py-1 bg-[#0f1420] text-gray-300 hover:text-cyan-200 rounded text-xs font-mono transition-colors duration-200" type="button">
              {t('serverStatus.retryConnection')}
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-gray-400 font-mono">Core {server.core}</span>
                <span className="w-4 h-4 bg-emerald-950/80 rounded-full flex items-center justify-center">
                  <CheckCircle className="w-3 h-3 text-emerald-300/70" />
                </span>
              </div>
              <div className="flex items-center gap-1">
                <button className="w-6 h-6 bg-[#0f1420] text-gray-500 hover:text-cyan-300 rounded flex items-center justify-center transition-colors duration-200" title={t('serverStatus.restartXray')} type="button">
                  <RotateCcw className="w-3.5 h-3.5 opacity-60" />
                </button>
                <button className="w-6 h-6 bg-[#0f1420] text-gray-500 hover:text-red-300 rounded flex items-center justify-center transition-colors duration-200" title={t('serverStatus.stopXray')} type="button">
                  <Square className="w-3.5 h-3.5 opacity-60" />
                </button>
                <button className="h-6 px-2 bg-[#0f1420] text-gray-400 hover:text-cyan-200 rounded text-[10px] font-mono transition-colors duration-200" title="Logs" type="button">
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
        <span className="text-[11px] text-gray-400 font-mono leading-none">{label}</span>
        <span className="text-[11px] text-green-400 font-mono font-bold leading-none text-right">
          {valueText}
          {detail && <span className="text-gray-500 text-[10px] ml-1.5 font-normal">{detail}</span>}
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
      className="w-6 h-6 bg-[#0f1420] text-gray-500 hover:text-cyan-300 rounded flex items-center justify-center transition-colors duration-200"
      title={title}
      aria-label={title}
      type="button"
    >
      <span className="opacity-60">{icon}</span>
    </button>
  );
}
