import React from 'react';
import { useTheme } from '../contexts/ThemeContext';

function buildGrafanaUrl(): string {
  const explicitPath = (import.meta.env.VITE_GRAFANA_PATH as string | undefined)?.trim();
  if (explicitPath) {
    const normalized = explicitPath.startsWith('/') ? explicitPath : `/${explicitPath}`;
    return `${window.location.origin}${normalized.replace(/\/$/, '')}/`;
  }

  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
  const legacyPath = base ? `${base}/grafana` : '/grafana';
  return `${window.location.origin}${legacyPath}/`;
}

export const MonitoringDashboard: React.FC = () => {
  const { colors } = useTheme();
  const grafanaUrl = buildGrafanaUrl();

  return (
    <div className="monitoring-panel card" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
      <div className="monitoring-panel__header" style={{ borderBottom: `1px solid ${colors.border}` }}>
        <div>
          <h4 className="monitoring-panel__title" style={{ color: colors.text.primary }}>
            Grafana Monitoring
          </h4>
          <p className="monitoring-panel__hint" style={{ color: colors.text.secondary }}>
            Откройте внешний дашборд Grafana для метрик Prometheus.
          </p>
        </div>
        <a
          className="btn btn-sm"
          href={grafanaUrl}
          target="_blank"
          rel="noreferrer"
          style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#fff' }}
        >
          Открыть Grafana
        </a>
      </div>

      <div className="monitoring-panel__body" style={{ backgroundColor: colors.bg.primary }}>
        <div className="p-3">
          <div style={{ color: colors.text.secondary, marginBottom: '8px' }}>Ссылка для доступа:</div>
          <code>{grafanaUrl}</code>
        </div>
      </div>
    </div>
  );
};
