/**
 * Performance Metrics Dashboard для мониторинга LCP, CLS, TTI
 * Используется performanceMonitoring сервис для сбора метрик
 */
import React, { useEffect, useState } from 'react';
import { performanceMonitor } from '../services/performanceMonitoring';
import { useTranslation } from 'react-i18next';

export interface PerformanceMetrics {
  fcp?: number; // First Contentful Paint (ms)
  lcp?: number; // Largest Contentful Paint (ms)
  cls?: number; // Cumulative Layout Shift
  tti?: number; // Time to Interactive (ms)
  apiLatencies: Record<string, { min: number; max: number; avg: number; count: number }>;
  errorCount: number;
  timestamp: number;
}

export const PerformanceMetricsDashboard: React.FC = () => {
  const { t } = useTranslation();
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null);
  const [history, setHistory] = useState<(PerformanceMetrics | undefined)[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    // Начальная загрузка метрик
    updateMetrics();

    // Auto-refresh каждые 5 секунд
    const interval = autoRefresh
      ? setInterval(updateMetrics, 5000)
      : null;

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [autoRefresh]);

  const updateMetrics = () => {
    const current = performanceMonitor.exportMetrics() as any;
    if (current) {
      setMetrics({
        fcp: current.fcp,
        lcp: current.lcp,
        cls: current.cls,
        tti: current.tti,
        apiLatencies: current.apiLatencies || {},
        errorCount: current.errorCount || 0,
        timestamp: Date.now(),
      });
      setHistory((prev) => [
        ...(prev as any[]).slice(-99),
        {
          fcp: current.fcp,
          lcp: current.lcp,
          cls: current.cls,
          tti: current.tti,
          apiLatencies: current.apiLatencies || {},
          errorCount: current.errorCount || 0,
          timestamp: Date.now(),
        } as PerformanceMetrics,
      ]);
    }
  };

  const getLCPStatus = (lcp?: number): 'good' | 'needs-improvement' | 'poor' => {
    if (!lcp) return 'poor';
    if (lcp <= 2500) return 'good';
    if (lcp <= 4000) return 'needs-improvement';
    return 'poor';
  };

  const getCLSStatus = (cls?: number): 'good' | 'needs-improvement' | 'poor' => {
    if (!cls) return 'good';
    if (cls <= 0.1) return 'good';
    if (cls <= 0.25) return 'needs-improvement';
    return 'poor';
  };

  const getFCPStatus = (fcp?: number): 'good' | 'needs-improvement' | 'poor' => {
    if (!fcp) return 'poor';
    if (fcp <= 1800) return 'good';
    if (fcp <= 3000) return 'needs-improvement';
    return 'poor';
  };

  const getStatusColor = (status: 'good' | 'needs-improvement' | 'poor'): string => {
    switch (status) {
      case 'good':
        return '#10b981'; // green
      case 'needs-improvement':
        return '#f59e0b'; // amber
      case 'poor':
        return '#ef4444'; // red
    }
  };

  const getStatusText = (status: 'good' | 'needs-improvement' | 'poor'): string => {
    switch (status) {
      case 'good':
        return t('performance.good');
      case 'needs-improvement':
        return t('performance.needsImprovement');
      case 'poor':
        return t('performance.poor');
    }
  };

  if (!metrics) {
    return (
      <div style={{ padding: '1rem', color: '#666' }}>
        ⏳ {t('performance.loading')}
      </div>
    );
  }

  return (
    <div style={{ padding: '1.5rem', fontFamily: 'system-ui' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1.5rem',
        }}
      >
        <h2 style={{ margin: 0 }}>🎯 {t('performance.title')}</h2>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            onClick={updateMetrics}
            style={{
              padding: '0.5rem 1rem',
              backgroundColor: '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '0.375rem',
              cursor: 'pointer',
            }}
          >
            🔄 {t('common.refresh')}
          </button>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            {t('performance.autoRefresh')}
          </label>
        </div>
      </div>

      {/* Web Vitals Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
          gap: '1rem',
          marginBottom: '2rem',
        }}
      >
        {/* LCP */}
        <div
          style={{
            border: `2px solid ${getStatusColor(getLCPStatus(metrics.lcp))}`,
            borderRadius: '0.5rem',
            padding: '1rem',
            backgroundColor: '#f9fafb',
          }}
        >
          <div style={{ fontSize: '0.875rem', color: '#666', marginBottom: '0.5rem' }}>
            {t('performance.lcp')}
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>
            {metrics.lcp?.toFixed(0) || '—'} ms
          </div>
          <div style={{ fontSize: '0.875rem', color: getStatusColor(getLCPStatus(metrics.lcp)) }}>
            {getStatusText(getLCPStatus(metrics.lcp))}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#999', marginTop: '0.5rem' }}>
            {t('performance.targetLcp')}
          </div>
        </div>

        {/* CLS */}
        <div
          style={{
            border: `2px solid ${getStatusColor(getCLSStatus(metrics.cls))}`,
            borderRadius: '0.5rem',
            padding: '1rem',
            backgroundColor: '#f9fafb',
          }}
        >
          <div style={{ fontSize: '0.875rem', color: '#666', marginBottom: '0.5rem' }}>
            {t('performance.cls')}
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>
            {metrics.cls?.toFixed(3) || '—'}
          </div>
          <div style={{ fontSize: '0.875rem', color: getStatusColor(getCLSStatus(metrics.cls)) }}>
            {getStatusText(getCLSStatus(metrics.cls))}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#999', marginTop: '0.5rem' }}>
            {t('performance.targetCls')}
          </div>
        </div>

        {/* FCP */}
        <div
          style={{
            border: `2px solid ${getStatusColor(getFCPStatus(metrics.fcp))}`,
            borderRadius: '0.5rem',
            padding: '1rem',
            backgroundColor: '#f9fafb',
          }}
        >
          <div style={{ fontSize: '0.875rem', color: '#666', marginBottom: '0.5rem' }}>
            {t('performance.fcp')}
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>
            {metrics.fcp?.toFixed(0) || '—'} ms
          </div>
          <div style={{ fontSize: '0.875rem', color: getStatusColor(getFCPStatus(metrics.fcp)) }}>
            {getStatusText(getFCPStatus(metrics.fcp))}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#999', marginTop: '0.5rem' }}>
            {t('performance.targetFcp')}
          </div>
        </div>

        {/* TTI */}
        <div
          style={{
            border: '2px solid #3b82f6',
            borderRadius: '0.5rem',
            padding: '1rem',
            backgroundColor: '#f9fafb',
          }}
        >
          <div style={{ fontSize: '0.875rem', color: '#666', marginBottom: '0.5rem' }}>
            {t('performance.tti')}
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>
            {metrics.tti?.toFixed(0) || '—'} ms
          </div>
          <div style={{ fontSize: '0.875rem', color: '#3b82f6' }}>
            {t('performance.ttiHint')}
          </div>
        </div>
      </div>

      {/* API Latencies */}
      {Object.keys(metrics.apiLatencies).length > 0 && (
        <div
          style={{
            backgroundColor: '#f0f4f8',
            padding: '1rem',
            borderRadius: '0.5rem',
            marginBottom: '1rem',
          }}
        >
          <h3 style={{ marginTop: 0 }}>📡 {t('performance.apiLatency')}</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
            {Object.entries(metrics.apiLatencies).map(([endpoint, latency]) => (
              <div key={endpoint} style={{ backgroundColor: 'white', padding: '0.75rem', borderRadius: '0.375rem' }}>
                <div style={{ fontSize: '0.875rem', color: '#666' }}>{endpoint}</div>
                <div style={{ fontSize: '1.125rem', fontWeight: 'bold' }}>
                  {latency.avg.toFixed(0)} ms
                </div>
                <div style={{ fontSize: '0.75rem', color: '#999' }}>
                  {t('performance.latencyStats', { min: latency.min.toFixed(0), max: latency.max.toFixed(0), count: latency.count })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error Count */}
      {metrics.errorCount > 0 && (
        <div
          style={{
            backgroundColor: '#fef2f2',
            padding: '1rem',
            borderRadius: '0.5rem',
            marginBottom: '1rem',
          }}
        >
          <div style={{ color: '#dc2626' }}>
            ⚠️ {t('performance.javascriptErrors')}: <strong>{metrics.errorCount}</strong>
          </div>
        </div>
      )}

      {/* History Chart */}
      {history.length > 1 && (
        <div
          style={{
            backgroundColor: '#f9fafb',
            padding: '1rem',
            borderRadius: '0.5rem',
            marginTop: '1.5rem',
          }}
        >
          <h3 style={{ marginTop: 0 }}>📈 {t('performance.historyTitle', { count: history.length })}</h3>
          <div style={{ fontSize: '0.875rem', color: '#666', marginTop: '1rem' }}>
            <div>{t('performance.periodAverages')}:</div>
            <ul style={{ margin: '0.5rem 0', paddingLeft: '1.25rem' }}>
              <li>
                LCP: {(history.filter(Boolean).reduce((sum, m) => sum + (m?.lcp || 0), 0) / Math.max(history.filter(Boolean).length, 1)).toFixed(0)} ms
              </li>
              <li>
                CLS: {(history.filter(Boolean).reduce((sum, m) => sum + (m?.cls || 0), 0) / Math.max(history.filter(Boolean).length, 1)).toFixed(3)}
              </li>
              <li>
                FCP: {(history.filter(Boolean).reduce((sum, m) => sum + (m?.fcp || 0), 0) / Math.max(history.filter(Boolean).length, 1)).toFixed(0)} ms
              </li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
};

export default PerformanceMetricsDashboard;
