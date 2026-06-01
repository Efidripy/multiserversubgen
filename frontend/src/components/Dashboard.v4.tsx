import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Server, Users, Activity, Database, RefreshCw } from 'lucide-react';
import api from '../api';
import { getAuth } from '../auth';
import { StatsCardV4 } from './StatsCard.v4';

interface TopClient {
  email: string;
  upload: number;
  download: number;
  total: number;
}

interface Summary {
  nodes_total: number;
  clients_total: number;
  online_clients_total: number;
  online_by_node?: Record<string, number>;
  traffic: { upload: number; download: number; total: number };
  top_clients: TopClient[];
}

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
};

interface DashboardV4Props {
  onNavigate?: (tab: string) => void;
}

export const DashboardV4: React.FC<DashboardV4Props> = ({ onNavigate }) => {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get('/v1/dashboard/summary', { auth: getAuth() });
      setSummary(res.data);
      setLastUpdated(new Date());
    } catch {
      setSummary(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);

  if (loading && !summary) {
    return (
      <div className="p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <div className="animate-spin">
            <RefreshCw className="w-4 h-4" />
          </div>
          <span className="text-sm">{t('messages.loadingData')}</span>
        </div>
      </div>
    );
  }

  if (!summary) return null;

  const stats = [
    {
      title: t('nodes.title'),
      value: String(summary.nodes_total),
      icon: <Server className="w-5 h-5" />,
      gradient: 'from-cyan-400/80 to-blue-400/80',
      shadowColor: 'shadow-cyan-400/20',
      tab: 'monitoring',
    },
    {
      title: t('clients.title'),
      value: String(summary.clients_total),
      icon: <Users className="w-5 h-5" />,
      gradient: 'from-magenta-400/80 to-pink-400/80',
      shadowColor: 'shadow-magenta-400/20',
      tab: 'clients',
    },
    {
      title: t('traffic.onlineClients'),
      value: String(summary.online_clients_total),
      icon: <Activity className="w-5 h-5" />,
      gradient: 'from-purple-400/80 to-indigo-400/80',
      shadowColor: 'shadow-purple-400/20',
      tab: 'clients',
    },
    {
      title: t('traffic.totalTraffic'),
      value: formatBytes(summary.traffic.total),
      icon: <Database className="w-5 h-5" />,
      gradient: 'from-green-400/80 to-emerald-400/80',
      shadowColor: 'shadow-green-400/20',
      tab: 'traffic',
    },
  ];

  return (
    <div className="p-6 min-h-screen">
      {/* Header */}
      <div className="mb-6 bg-[#0f1420] backdrop-blur-sm rounded-lg p-4 border border-cyan-500/20 relative overflow-hidden">
        <div className="relative z-10">
          <h1 className="text-2xl font-bold text-cyan-300 font-mono tracking-wider">{t('nav.dashboard', 'DASHBOARD')}</h1>
          <p className="text-magenta-300 mt-1 font-mono text-xs">VARIANT 4: COMMAND CENTER</p>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {stats.map(stat => (
          <StatsCardV4
            key={stat.title}
            title={stat.title}
            value={stat.value}
            icon={stat.icon}
            gradient={stat.gradient}
            shadowColor={stat.shadowColor}
            onClick={() => onNavigate?.(stat.tab)}
          />
        ))}
      </div>

      {/* Per-node breakdown */}
      {summary.online_by_node && Object.keys(summary.online_by_node).length > 1 && (
        <div className="mb-6 flex flex-wrap gap-2">
          {Object.entries(summary.online_by_node)
            .sort((a, b) => b[1] - a[1])
            .map(([node, count]) => (
              <button
                key={node}
                onClick={() => onNavigate?.('clients')}
                className="px-3 py-1.5 bg-[#0f1420] border border-cyan-500/20 rounded-lg text-cyan-300 font-mono text-xs hover:border-cyan-400/30 transition-all"
              >
                {node}: <strong>{count}</strong>
              </button>
            ))}
        </div>
      )}

      {/* System Activity */}
      {summary.top_clients.length > 0 && (
        <div className="bg-[#0f1420] backdrop-blur-sm border border-cyan-500/20 rounded-lg overflow-hidden">
          <div className="p-4 border-b border-cyan-500/20 bg-cyan-500/5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-cyan-300 font-mono">{t('dashboardSummary.topByTraffic', 'TOP CLIENTS')}</h2>
              <button
                onClick={load}
                disabled={loading}
                className="p-2 hover:bg-cyan-500/10 rounded transition-colors disabled:opacity-50"
                title={t('common.refresh', 'Refresh')}
              >
                <RefreshCw className={`w-4 h-4 text-cyan-400 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>
          <div className="divide-y divide-cyan-500/10">
            {summary.top_clients.map((client, idx) => {
              const pct = summary.traffic.total > 0 ? (client.total / summary.traffic.total) * 100 : 0;
              return (
                <div key={client.email} className="p-4 hover:bg-cyan-500/5 transition-colors group cursor-pointer">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-lg shadow-cyan-400/30 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-cyan-300 font-mono text-xs font-bold">CLIENT_{idx + 1}</p>
                        <p className="text-gray-400 font-mono text-[10px] mt-0.5 truncate" title={client.email}>
                          {client.email}
                        </p>
                      </div>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-400/20 text-cyan-300 border border-cyan-400/40">
                        {formatBytes(client.total)}
                      </span>
                    </div>
                  </div>
                  <div className="mt-2 w-full bg-[#0a0e1a] rounded-full h-1 overflow-hidden border border-cyan-500/20">
                    <div
                      className="h-full bg-gradient-to-r from-cyan-400 to-magenta-400"
                      style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Last updated info */}
      {lastUpdated && (
        <div className="mt-4 text-right text-gray-500 text-xs font-mono">
          {t('common.lastUpdated', 'Last updated')}: {lastUpdated.toLocaleTimeString()}
        </div>
      )}
    </div>
  );
};
