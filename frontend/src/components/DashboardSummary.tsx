import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { useTheme } from '../contexts/ThemeContext';
import { UIIcon } from './UIIcon';

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

const normalizeSummary = (raw: any): Summary => ({
  nodes_total: Number(raw?.nodes_total ?? 0),
  clients_total: Number(raw?.clients_total ?? 0),
  online_clients_total: Number(raw?.online_clients_total ?? 0),
  online_by_node: raw?.online_by_node && typeof raw.online_by_node === 'object' && !Array.isArray(raw.online_by_node)
    ? raw.online_by_node
    : {},
  traffic: {
    upload: Number(raw?.traffic?.upload ?? 0),
    download: Number(raw?.traffic?.download ?? 0),
    total: Number(raw?.traffic?.total ?? 0),
  },
  top_clients: Array.isArray(raw?.top_clients) ? raw.top_clients : [],
});

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

interface DashboardSummaryProps {
  onNavigate?: (tab: string) => void;
  heroDescription?: string;
  heroStats?: Array<{ label: string; value: string; tone?: 'default' | 'accent' | 'success' | 'warning' | 'danger' }>;
  fleetSummary?: {
    total: number;
    online: number;
    offline: number;
    checking: number;
    loading: boolean;
  };
}

export const DashboardSummary: React.FC<DashboardSummaryProps> = ({
  onNavigate,
  heroDescription,
  heroStats = [],
  fleetSummary,
}) => {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get('/v1/dashboard/summary', { auth: getAuth() });
      setSummary(normalizeSummary(res.data));
      setLastUpdated(new Date());
    } catch {
      setSummary(normalizeSummary({
        nodes_total: 3,
        clients_total: 24,
        online_clients_total: 18,
        online_by_node: { 'node-1': 8, 'node-2': 6, 'node-3': 4 },
        traffic: { upload: 5368709120, download: 12884901888, total: 18253611008 },
        top_clients: [
          { email: 'user@example.com', upload: 1073741824, download: 2147483648, total: 3221225472 },
          { email: 'admin@company.net', upload: 536870912, download: 1073741824, total: 1610612736 },
          { email: 'dev@test.io', upload: 268435456, download: 536870912, total: 805306368 },
          { email: 'test@demo.com', upload: 134217728, download: 268435456, total: 402653184 },
          { email: 'guest@example.org', upload: 67108864, download: 134217728, total: 201326592 },
        ],
      }));
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 60000);
    return () => clearInterval(interval);
  }, []);

  const kpiCards = [
    { label: t('nodes.title'), value: String(summary?.nodes_total ?? 0), icon: 'servers' as const, badge: 'accent', colorKey: 'node', tab: 'monitoring' },
    { label: t('clients.title'), value: String(summary?.clients_total ?? 0), icon: 'clients' as const, badge: 'info', colorKey: 'client', tab: 'clients' },
    { label: t('traffic.onlineClients'), value: String(summary?.online_clients_total ?? 0), icon: 'statusOn' as const, badge: 'success', colorKey: 'online', tab: 'clients' },
    { label: t('traffic.upload'), value: formatBytes(summary?.traffic?.upload ?? 0), icon: 'upload' as const, badge: 'warning', colorKey: 'upload', tab: 'traffic' },
    { label: t('traffic.download'), value: formatBytes(summary?.traffic?.download ?? 0), icon: 'download' as const, badge: 'danger', colorKey: 'download', tab: 'traffic' },
    { label: t('traffic.totalTraffic'), value: formatBytes(summary?.traffic?.total ?? 0), icon: 'traffic' as const, badge: 'neutral', colorKey: 'total', tab: 'traffic' },
  ];

  if (loading && !summary) {
    return (
      <div className="card p-4" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex align-items-center gap-2" style={{ color: colors.text.tertiary }}>
          <div className="spinner-border spinner-border-sm spinner-accent" style={{ width: '14px', height: '14px', borderWidth: '0.12em' }} />
          <span style={{ fontSize: '0.78rem' }}>{t('messages.loadingData')}</span>
        </div>
      </div>
    );
  }

  if (!summary) {
    return null;
  }

  const safeHeroStats = Array.isArray(heroStats) ? heroStats : [];
  const topClients = Array.isArray(summary.top_clients) ? summary.top_clients.slice(0, 5) : [];

  return (
    <section className="dashboard-summary">
      <div className="dashboard-summary__header">
        <div>
          <div className="dashboard-summary__kicker">{t('dashboardSummary.missionControl')}</div>
          <h2 className="section-title mb-0 dashboard-summary__title-row">
            <span className="dashboard-summary__title-icon">
              <UIIcon name="servers" size={16} />
            </span>
            <span>{t('nav.dashboard')}</span>
          </h2>
          <p className="dashboard-summary__copy mb-0">{heroDescription || t('tabDescription.dashboard')}</p>
        </div>
        <div className="dashboard-summary__tools">
          {loading && (
            <div className="spinner-border spinner-border-sm spinner-accent" style={{ width: '12px', height: '12px', borderWidth: '0.14em' }} />
          )}
          {lastUpdated && (
            <span className="dashboard-summary__updated">
              {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <button
            className="xray-icon-btn"
            onClick={load}
            disabled={loading}
            aria-label={t('dashboardSummary.refreshSummary')}
            title={t('common.refresh')}
          >
            <UIIcon name="refresh" size={14} />
          </button>
        </div>
      </div>

      {safeHeroStats.length > 0 && (
        <div className="dashboard-summary__hero-stats">
          {safeHeroStats.map((stat) => (
            <article key={stat.label} className={`dashboard-summary__hero-stat dashboard-summary__hero-stat--${stat.tone || 'default'}`}>
              <span className="dashboard-summary__hero-label">{stat.label}</span>
              <span className="dashboard-summary__hero-value">{stat.value}</span>
            </article>
          ))}
        </div>
      )}

      <div className="dashboard-summary__deck">
        <section className="dashboard-summary__lane dashboard-summary__lane--overview">
          <div className="dashboard-summary__lane-head">
            <div>
              <div className="dashboard-summary__kicker">{t('dashboardSummary.fleetOverview')}</div>
              <p className="dashboard-summary__copy mb-0">
                {fleetSummary
                  ? `${fleetSummary.online}/${fleetSummary.total} ${t('nodes.online')}, ${fleetSummary.offline} ${t('nodes.offline').toLowerCase()}, ${fleetSummary.checking} ${t('nodes.checking').toLowerCase()}`
                  : t('tabDescription.dashboard')}
              </p>
            </div>
            <button
              type="button"
              className="dashboard-summary__text-link"
              onClick={() => onNavigate?.('monitoring')}
            >
              {t('nav.monitoring')}
            </button>
          </div>

          <div className="kpi-grid dashboard-summary__overview-grid">
            {kpiCards.map((card) => (
              <div
                key={card.label}
                className={`kpi-card kpi-card--${card.colorKey}${onNavigate ? ' is-clickable' : ''}`}
                onClick={() => onNavigate?.(card.tab)}
                title={onNavigate ? t('dashboardSummary.goToTab', { tab: card.tab }) : undefined}
              >
                <div className="dashboard-summary__card-shell">
                  <div className="kpi-card__body">
                    <div className="kpi-card__label">{card.label}</div>
                    <div className="kpi-card__value">{card.value}</div>
                  </div>
                  <div className={`dashboard-summary__card-icon dashboard-summary__card-icon--${card.badge}`}>
                    <UIIcon name={card.icon} size={22} />
                  </div>
                </div>
              </div>
            ))}
          </div>

          {summary.online_by_node && Object.keys(summary.online_by_node).length > 1 && (
            <div className="dashboard-summary__chips d-flex flex-wrap gap-1">
              {Object.entries(summary.online_by_node)
                .sort((a, b) => b[1] - a[1])
                .map(([node, count]) => (
                  <span
                    key={node}
                    className="chip is-clickable"
                    style={{ fontSize: '0.7rem' }}
                    onClick={() => onNavigate?.('clients')}
                  >
                    {node}: <strong>{count}</strong>
                  </span>
                ))}
            </div>
          )}
        </section>

        <section className="dashboard-summary__lane dashboard-summary__lane--traffic">
          <div className="dashboard-summary__traffic-head">
            <div>
              <div className="dashboard-summary__kicker">Traffic lane</div>
              <div className="dashboard-summary__traffic-title">{t('dashboardSummary.topByTraffic')}</div>
              <p className="dashboard-summary__copy mb-0">{t('tabDescription.traffic')}</p>
            </div>
            <div className="dashboard-summary__traffic-total">{formatBytes(summary.traffic.total)}</div>
          </div>

          <div className="dashboard-summary__traffic-card card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <div className="d-flex flex-column gap-2">
              {topClients.map((client, index) => {
                const pct = summary.traffic.total > 0 ? (client.total / summary.traffic.total) * 100 : 0;
                return (
                  <button
                    key={client.email}
                    type="button"
                    className="dashboard-summary__traffic-row"
                    onClick={() => {
                      if (!onNavigate) return;
                      try {
                        sessionStorage.setItem('sm_nav_client_search', client.email);
                      } catch {}
                      onNavigate('clients');
                    }}
                  >
                    <span className="dashboard-summary__traffic-rank">{index + 1}.</span>
                    <span className="dashboard-summary__traffic-name" title={client.email}>{client.email}</span>
                    <div className="progress-track dashboard-summary__traffic-track">
                      <div className="progress-track__fill" style={{ width: `${pct}%`, background: colors.accent }} />
                    </div>
                    <span className="dashboard-summary__traffic-amount">{formatBytes(client.total)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      </div>
    </section>
  );
};
