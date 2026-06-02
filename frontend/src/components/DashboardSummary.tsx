import React, { useState, useEffect } from 'react';
import api from '../api';
import { getAuth } from '../auth';
import { useTheme } from '../contexts/ThemeContext';
import { UIIcon } from './UIIcon';
import { useTranslation } from 'react-i18next';

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

export const DashboardSummary: React.FC<{ onNavigate?: (tab: string) => void }> = ({ onNavigate }) => {
  const { colors } = useTheme();
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
    } catch { setSummary(null); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);

  if (loading && !summary) return (
    <div className="card p-4" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
      <div className="d-flex align-items-center gap-2" style={{ color: colors.text.tertiary }}>
        <div className="spinner-border spinner-border-sm spinner-accent" style={{ width: '14px', height: '14px', borderWidth: '0.12em' }} />
        <span style={{ fontSize: '0.78rem' }}>{t('messages.loadingData')}</span>
      </div>
    </div>
  );

  if (!summary) return null;

  const kpiCards = [
    { label: t('nodes.title'), value: String(summary.nodes_total), icon: 'servers' as const, badge: 'accent', colorKey: 'node', tab: 'monitoring' },
    { label: t('clients.title'), value: String(summary.clients_total), icon: 'clients' as const, badge: 'info', colorKey: 'client', tab: 'clients' },
    { label: t('traffic.onlineClients'), value: String(summary.online_clients_total), icon: 'statusOn' as const, badge: 'success', colorKey: 'online', tab: 'clients' },
    { label: t('traffic.upload'), value: formatBytes(summary.traffic.upload), icon: 'upload' as const, badge: 'warning', colorKey: 'upload', tab: 'traffic' },
    { label: t('traffic.download'), value: formatBytes(summary.traffic.download), icon: 'download' as const, badge: 'danger', colorKey: 'download', tab: 'traffic' },
    { label: t('traffic.totalTraffic'), value: formatBytes(summary.traffic.total), icon: 'traffic' as const, badge: 'neutral', colorKey: 'total', tab: 'traffic' },
  ];

  return (
    <div className="dashboard-summary">
      {/* Section header */}
      <div className="dashboard-summary__header d-flex align-items-center justify-content-between">
        <h2 className="section-title mb-0">{t('dashboardSummary.fleetOverview')}</h2>
        <div className="dashboard-summary__tools d-flex align-items-center gap-2">
          {loading && (
            <div className="spinner-border spinner-border-sm spinner-accent" style={{ width: '12px', height: '12px', borderWidth: '0.14em' }} />
          )}
          {lastUpdated && (
            <span style={{ color: colors.text.tertiary, fontSize: '0.7rem', fontVariantNumeric: 'tabular-nums' }}>
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

      {/* KPI card grid */}
      <div className="kpi-grid">
        {kpiCards.map(card => (
          <div
            key={card.label}
            className={`kpi-card kpi-card--${card.colorKey}${onNavigate ? ' is-clickable' : ''}`}
            onClick={() => onNavigate?.(card.tab)}
            title={onNavigate ? t('dashboardSummary.goToTab', { tab: card.tab }) : undefined}
          >
            <div className="kpi-card__body">
              <div className="kpi-card__label">{card.label}</div>
              <div className="kpi-card__value">{card.value}</div>
            </div>
            <div className={`icon-badge icon-badge--${card.badge} icon-badge--rounded`}>
              <UIIcon name={card.icon} size={20} />
            </div>
          </div>
        ))}
      </div>

      {/* Per-node online breakdown */}
      {summary.online_by_node && Object.keys(summary.online_by_node).length > 1 && (
        <div className="dashboard-summary__chips d-flex flex-wrap gap-1">
          {Object.entries(summary.online_by_node).sort((a, b) => b[1] - a[1]).map(([node, count]) => (
            <span key={node} className="chip is-clickable" style={{ fontSize: '0.7rem' }}
              onClick={() => onNavigate?.('clients')}>
              {node}: <strong>{count}</strong>
            </span>
          ))}
        </div>
      )}

      {/* Top clients */}
      {summary.top_clients.length > 0 && (
        <div className="dashboard-summary__top-traffic">
          <div className="section-title--sm mb-2" style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: colors.text.tertiary }}>
            {t('dashboardSummary.topByTraffic')}
          </div>
          <div className="dashboard-summary__traffic-card card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
            <div className="d-flex flex-column gap-2">
              {summary.top_clients.map((c, i) => {
                const pct = summary.traffic.total > 0 ? (c.total / summary.traffic.total) * 100 : 0;
                return (
                  <div key={c.email} className="dashboard-summary__traffic-row d-flex align-items-center gap-2">
                    <span style={{ color: colors.text.tertiary, fontSize: '0.68rem', minWidth: '16px', fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
                      {i + 1}.
                    </span>
                    <span
                      className="text-truncate"
                      style={{
                        color: onNavigate ? colors.accent : colors.text.primary,
                        fontSize: '0.78rem',
                        maxWidth: '180px',
                        cursor: onNavigate ? 'pointer' : 'default',
                        flexShrink: 0,
                        fontWeight: 500,
                      }}
                      title={c.email}
                      onClick={() => {
                        if (!onNavigate) return;
                        try { sessionStorage.setItem('sm_nav_client_search', c.email); } catch {}
                        onNavigate('clients');
                      }}
                    >
                      {c.email}
                    </span>
                    <div className="progress-track flex-grow-1" style={{ minWidth: '40px' }}>
                      <div className="progress-track__fill" style={{ width: `${pct}%`, background: colors.accent }} />
                    </div>
                    <span style={{ color: colors.text.secondary, fontSize: '0.72rem', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                      {formatBytes(c.total)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
