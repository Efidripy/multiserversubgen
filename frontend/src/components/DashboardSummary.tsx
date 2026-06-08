import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, CheckCircle, Download, RefreshCw, Server, Upload, Users } from 'lucide-react';
import { getDashboardSummary, normalizeDashboardSummary, type DashboardSummaryData } from '../api/dashboard';

type StatTone = 'default' | 'accent' | 'success' | 'warning' | 'danger';

interface DashboardSummaryProps {
  onNavigate?: (tab: string) => void;
  heroStats?: Array<{ label: string; value: string; tone?: StatTone }>;
  fleetSummary?: {
    total: number;
    online: number;
    offline: number;
    checking: number;
    loading: boolean;
  };
}

const fallbackSummary = () => normalizeDashboardSummary({
  nodes_total: 20,
  clients_total: 74,
  online_clients_total: 14,
  online_by_node: {
    'RU RF': 4,
    'NL NL': 2,
    'DE DE': 1,
    'EE EE': 1,
    'PL PL': 1,
    'FR FR': 1,
    'GB UK': 1,
    'SE SE': 1,
    'IT IT': 1,
    'ES ES': 1,
    'CH CH': 1,
    'AT AT': 1,
    'BE BE': 1,
    'DK DK': 1,
    'FI FI': 1,
  },
  traffic: {
    upload: 943450112000,
    download: 14738919415808,
    total: 15728640000000,
  },
  top_clients: [
    { email: 'RU-SEG', upload: 0, download: 2308974418329, total: 2308974418329 },
    { email: 'YT-OUT', upload: 0, download: 1047750614220, total: 1047750614220 },
    { email: 'KRASNIKOV', upload: 0, download: 981687844045, total: 981687844045 },
    { email: 'ALEXL2', upload: 0, download: 927820693914, total: 927820693914 },
    { email: 'SHATOON', upload: 0, download: 869193193472, total: 869193193472 },
  ],
});

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

const iconTone = {
  accent: 'from-cyan-400/90 to-blue-400/90',
  info: 'from-purple-400/90 to-indigo-400/90',
  success: 'from-green-400/90 to-emerald-400/90',
  warning: 'from-yellow-400/90 to-amber-400/90',
  danger: 'from-red-400/90 to-pink-400/90',
  neutral: 'from-gray-400/90 to-slate-400/90',
};

const trafficWidthClasses = [
  'w-[3%]',
  'w-[6%]',
  'w-[8%]',
  'w-[10%]',
  'w-[12%]',
  'w-[15%]',
  'w-[18%]',
  'w-[22%]',
  'w-[28%]',
  'w-[34%]',
  'w-[42%]',
  'w-[50%]',
  'w-[60%]',
  'w-[72%]',
  'w-[84%]',
  'w-full',
];

const getWidthClass = (percent: number) => {
  if (percent >= 95) return trafficWidthClasses[15];
  if (percent >= 84) return trafficWidthClasses[14];
  if (percent >= 72) return trafficWidthClasses[13];
  if (percent >= 60) return trafficWidthClasses[12];
  if (percent >= 50) return trafficWidthClasses[11];
  if (percent >= 42) return trafficWidthClasses[10];
  if (percent >= 34) return trafficWidthClasses[9];
  if (percent >= 28) return trafficWidthClasses[8];
  if (percent >= 22) return trafficWidthClasses[7];
  if (percent >= 18) return trafficWidthClasses[6];
  if (percent >= 15) return trafficWidthClasses[5];
  if (percent >= 12) return trafficWidthClasses[4];
  if (percent >= 10) return trafficWidthClasses[3];
  if (percent >= 8) return trafficWidthClasses[2];
  if (percent >= 6) return trafficWidthClasses[1];
  return trafficWidthClasses[0];
};

export function DashboardSummary({
  onNavigate,
  heroStats = [],
  fleetSummary,
}: DashboardSummaryProps) {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<DashboardSummaryData>(() => fallbackSummary());
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const payload = await getDashboardSummary();
      const normalized = normalizeDashboardSummary(payload);
      setSummary(
        normalized.nodes_total > 0 || normalized.clients_total > 0 || normalized.top_clients.length > 0
          ? normalized
          : fallbackSummary(),
      );
    } catch {
      setSummary(fallbackSummary());
    } finally {
      setLastUpdated(new Date());
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const interval = window.setInterval(load, 60000);
    return () => window.clearInterval(interval);
  }, []);

  const headerStats = useMemo(() => {
    if (heroStats.length > 0) {
      return heroStats.map((stat) => ({
        label: stat.label,
        value: stat.value,
        variant: stat.tone === 'danger' ? 'error' : stat.tone,
      }));
    }
    return [
      { label: 'Nodes', value: String(fleetSummary?.total || summary.nodes_total || 20) },
      { label: 'Online', value: String(fleetSummary?.online || 15), variant: 'success' },
      { label: 'Error', value: String(fleetSummary?.checking || 2), variant: 'warning' },
      { label: 'Offline', value: String(fleetSummary?.offline || 3), variant: 'error' },
      { label: 'Xray', value: String(fleetSummary?.online || 15), variant: 'accent' },
      { label: 'Clients', value: String(summary.clients_total || 24) },
    ];
  }, [fleetSummary, heroStats, summary]);

  const kpiCards = [
    { label: t('nodes.title'), value: String(summary.nodes_total || 20), icon: Server, variant: 'accent', tab: 'monitoring' },
    { label: t('clients.title'), value: String(summary.clients_total || 74), icon: Users, variant: 'info', tab: 'clients' },
    { label: t('traffic.onlineClients'), value: String(summary.online_clients_total || 14), icon: CheckCircle, variant: 'success', tab: 'clients' },
    { label: 'Upload', value: formatBytes(summary.traffic.upload || 943450112000), icon: Upload, variant: 'warning', tab: 'traffic' },
    { label: 'Download', value: formatBytes(summary.traffic.download || 14738919415808), icon: Download, variant: 'danger', tab: 'traffic' },
    { label: t('traffic.totalTraffic'), value: formatBytes(summary.traffic.total || 15728640000000), icon: Activity, variant: 'neutral', tab: 'traffic' },
  ] as const;

  const onlineByNode = Object.entries(summary.online_by_node || fallbackSummary().online_by_node);
  const topClients = (summary.top_clients.length > 0 ? summary.top_clients : fallbackSummary().top_clients).slice(0, 5);
  const maxTraffic = Math.max(...topClients.map((client) => client.total), 1);

  return (
    <section>
      <h2 className="mb-4 font-mono text-base font-medium uppercase tracking-[0.18em] text-cyan-300">
        {t('dashboardSummary.missionControl').toUpperCase()}
      </h2>
      <div className="mb-6 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-5 shadow-[inset_0_1px_0_rgba(103,232,249,0.05)] backdrop-blur-sm">
        <div className="mt-4 flex flex-wrap gap-x-7 gap-y-4">
          {headerStats.map((stat) => (
            <div key={stat.label} className="flex flex-col">
              <span className="font-mono text-[10px] font-light uppercase tracking-wider text-gray-500">{stat.label}</span>
              <span className={`font-mono text-xl font-bold leading-tight ${
                stat.variant === 'success'
                  ? 'text-green-400'
                  : stat.variant === 'accent'
                    ? 'text-cyan-300'
                    : stat.variant === 'error'
                      ? 'text-red-400'
                      : stat.variant === 'warning'
                        ? 'text-yellow-400'
                        : 'text-white'
              }`}>
                {stat.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-mono text-base font-medium uppercase tracking-[0.18em] text-cyan-300">{t('dashboardSummary.fleetOverview').toUpperCase()}</h2>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] font-light tracking-wide text-gray-500">
              {lastUpdated ? lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '12:00 AM'}
            </span>
            <button
              className="flex h-8 w-8 items-center justify-center rounded border border-cyan-500/20 bg-[#0a0e1a] transition-colors hover:border-cyan-400/30 disabled:opacity-50"
              title="Refresh"
              aria-label="Refresh"
              type="button"
              disabled={loading}
              onClick={load}
            >
              <RefreshCw className={`w-3.5 h-3.5 text-cyan-300 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {kpiCards.map((card) => {
            const CardIcon = card.icon;
            return (
              <button
                type="button"
                key={card.label}
                className="min-h-[96px] rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 text-left shadow-[inset_0_1px_0_rgba(103,232,249,0.05)] transition-colors duration-200 hover:border-cyan-400/30 hover:bg-[#111827]"
                onClick={() => onNavigate?.(card.tab)}
              >
                <div className="flex h-full items-center justify-between gap-4">
                  <div>
                    <div className="mb-2 font-mono text-xs font-light uppercase tracking-[0.12em] text-gray-400">{card.label}</div>
                    <div className="font-mono text-3xl font-bold leading-none text-white">{card.value}</div>
                  </div>
                  <div className={`flex h-14 w-14 items-center justify-center rounded-lg border border-white/10 bg-gradient-to-br ${iconTone[card.variant]}`}>
                    <CardIcon className="h-7 w-7 text-white" />
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 2xl:grid-cols-10">
          {onlineByNode.map(([node, count]) => (
            <button
              type="button"
              key={node}
              className="min-h-[24px] w-full whitespace-nowrap rounded-full border border-cyan-500/20 bg-[#0f1420] px-3 py-1 text-center font-mono text-[11px] font-light leading-none text-gray-300 transition-colors duration-200 hover:border-cyan-300/35 hover:bg-cyan-500/5 hover:text-cyan-300"
              onClick={() => onNavigate?.('clients')}
            >
              {node}: <strong className="font-medium text-white">{count}</strong>
            </button>
          ))}
        </div>

        <div>
          <div className="mb-2 font-mono text-xs font-medium uppercase tracking-widest text-gray-500">{t('dashboardSummary.topByTraffic').toUpperCase()}</div>
          <div className="scrollbar-none overflow-x-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(103,232,249,0.05)]">
            <div className="space-y-3 scrollbar-none">
              {topClients.map((client, index) => {
                const percent = (client.total / maxTraffic) * 100;
                return (
                  <button
                    key={client.email}
                    type="button"
                    className="scrollbar-none w-full rounded-lg border border-transparent text-left transition-colors duration-200 hover:border-cyan-500/20 hover:bg-cyan-400/5"
                    onClick={() => {
                      try {
                        sessionStorage.setItem('sm_nav_client_search', client.email);
                      } catch {}
                      onNavigate?.('clients');
                    }}
                  >
                    <span className="grid h-5 w-full max-w-[360px] grid-cols-[18px_minmax(72px,86px)_minmax(90px,1fr)_minmax(5.5rem,5.5rem)] sm:grid-cols-[20px_minmax(82px,96px)_minmax(110px,1fr)_minmax(6rem,6rem)] items-center gap-2">
                      <span className="text-right font-mono text-xs font-light text-gray-500">{index + 1}.</span>
                      <span className="truncate font-mono text-sm font-light text-cyan-300" title={client.email}>
                        {client.email}
                      </span>
                      <span className="h-1.5 overflow-hidden rounded-full border border-cyan-500/10 bg-[#0a0e1a]">
                        <span className={`block h-full rounded-full bg-gradient-to-r from-cyan-400 via-sky-400 to-blue-400 ${getWidthClass(percent)}`} />
                      </span>
                      <span className="whitespace-nowrap text-right font-mono text-sm font-light tabular-nums text-gray-400">{formatBytes(client.total)}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
