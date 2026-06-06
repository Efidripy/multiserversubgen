import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { UIIcon } from './UIIcon';

interface NodeRecord {
  id: number;
  name: string;
  url?: string;
  scheme?: string;
  ip?: string;
  port?: string;
  read_only?: boolean;
  api_version?: string;
  panel_version?: string;
}

interface FleetNode extends NodeRecord {
  available: boolean | null;
  latency?: number;
  error?: string;
}

interface FleetSummary {
  total: number;
  online: number;
  offline: number;
  checking: number;
  loading: boolean;
}

interface RegisteredFleetPanelProps {
  collapsed: boolean;
  setCollapsed: (value: boolean) => void;
  onOpenNodes?: () => void;
  onSummaryChange?: (summary: FleetSummary) => void;
}

const getStatusLabel = (node: FleetNode) => {
  if (node.available === true) return 'online';
  if (node.available === false) return 'offline';
  return 'checking';
};

const getNodeAddress = (node: NodeRecord) => {
  if (node.url) return node.url.replace(/^https?:\/\//, '');
  const scheme = node.scheme || 'https';
  const host = node.ip || node.name;
  const port = node.port ? `:${node.port}` : '';
  return `${scheme}://${host}${port}`.replace(/^https?:\/\//, '');
};

export const RegisteredFleetPanel: React.FC<RegisteredFleetPanelProps> = ({
  collapsed,
  setCollapsed,
  onOpenNodes,
  onSummaryChange,
}) => {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<FleetNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');

  const load = async () => {
    setLoading(true);
    setLoadError('');
    try {
      const auth = getAuth();
      const res = await api.get('/v1/nodes', { auth });
      const list: NodeRecord[] = Array.isArray(res.data) ? res.data : [];
      setNodes(list.map((node) => ({ ...node, available: null })));

      const checks = await Promise.all(
        list.map(async (node) => {
          const started = performance.now();
          try {
            const status = await api.get(`/v1/nodes/${node.id}/server-status`, { auth });
            return {
              id: node.id,
              available: Boolean(status.data?.available),
              latency: Math.max(1, Math.round(performance.now() - started)),
              error: status.data?.error || status.data?.reason,
            };
          } catch (error: any) {
            return {
              id: node.id,
              available: false,
              latency: undefined,
              error: error?.response?.data?.detail || error?.message || 'Connection failed',
            };
          }
        }),
      );

      const byId = new Map(checks.map((item) => [item.id, item]));
      setNodes(list.map((node) => {
        const check = byId.get(node.id);
        return {
          ...node,
          available: check?.available ?? null,
          latency: check?.latency,
          error: check?.error,
        };
      }));
    } catch (error: any) {
      setNodes([]);
      setLoadError(error?.response?.data?.detail || error?.message || t('error'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const counts = useMemo(() => {
    const online = nodes.filter((node) => node.available === true).length;
    const offline = nodes.filter((node) => node.available === false).length;
    const checking = nodes.length - online - offline;
    return { online, offline, checking };
  }, [nodes]);

  useEffect(() => {
    onSummaryChange?.({
      total: nodes.length,
      online: counts.online,
      offline: counts.offline,
      checking: counts.checking,
      loading,
    });
  }, [counts.checking, counts.offline, counts.online, loading, nodes.length, onSummaryChange]);

  return (
    <>
      {collapsed && (
        <button
          className="registered-fleet-tab"
          onClick={() => setCollapsed(false)}
          title={t('nodes.registeredFleet')}
          aria-label={t('nodes.registeredFleet')}
          type="button"
        >
          {t('nodes.registeredFleet')}
        </button>
      )}

      <aside className={`registered-fleet${collapsed ? ' is-collapsed' : ''}`}>
        <button
          className="registered-fleet__rail"
          onClick={() => setCollapsed(true)}
          title={t('common.close')}
          aria-label={t('common.close')}
          type="button"
        >
          {collapsed ? '>' : '<'}
        </button>

        <div className="registered-fleet__inner">
          <header className="registered-fleet__header">
            <div className="registered-fleet__header-copy">
              <div className="registered-fleet__kicker">{t('dashboardSummary.fleetControl')}</div>
              <div className="registered-fleet__title-row">
                <span className="registered-fleet__title-icon">
                  <UIIcon name="servers" size={14} />
                </span>
                <h2>{t('nodes.registeredFleet')}</h2>
                <span className="registered-fleet__total-pill">{nodes.length}</span>
              </div>
              <div className="registered-fleet__counts">
                <span className="is-online">{t('nodes.online')}: <strong>{counts.online}</strong></span>
                <span className="is-checking">{t('nodes.checking')}: <strong>{counts.checking}</strong></span>
                <span className="is-offline">{t('nodes.offline')}: <strong>{counts.offline}</strong></span>
              </div>
              <div className="registered-fleet__state-row">
                <span className={`registered-fleet__state-pill${loading ? ' is-loading' : loadError ? ' is-error' : ' is-ready'}`}>
                  {loading ? t('nodes.statusSyncing') : loadError ? t('error') : t('dashboardSummary.liveView')}
                </span>
              </div>
            </div>
            <button className="registered-fleet__test" onClick={load} disabled={loading} type="button">
              {loading ? t('nodes.statusSyncing') : t('common.refresh')}
            </button>
          </header>

          <p className="registered-fleet__hint">{t('nodes.fleetHint')}</p>

          <div className="registered-fleet__list">
            {loadError && (
              <div className="registered-fleet__empty-state registered-fleet__empty-state--error">
                <strong>{t('error')}</strong>
                <span>{loadError}</span>
                {onOpenNodes && (
                  <button
                    type="button"
                    className="registered-fleet__empty-action"
                    onClick={onOpenNodes}
                  >
                    {t('nav.inbounds')}
                  </button>
                )}
              </div>
            )}

            {!loadError && !loading && nodes.length === 0 && (
              <div className="registered-fleet__empty-state">
                <strong>{t('common.noDataAvailable')}</strong>
                <span>{t('nodes.fleetHint')}</span>
                {onOpenNodes && (
                  <button
                    type="button"
                    className="registered-fleet__empty-action"
                    onClick={onOpenNodes}
                  >
                    {t('nodes.addNode')}
                  </button>
                )}
              </div>
            )}

            {nodes.map((node) => {
              const status = getStatusLabel(node);
              return (
                <article key={node.id} className={`registered-fleet__card${node.error ? ' has-error' : ''}`}>
                  <div className="registered-fleet__main">
                    <span className={`registered-fleet__dot is-${status}`} />
                    <div className="registered-fleet__title">
                      <strong>{node.name}</strong>
                      <span className="registered-fleet__version">{node.api_version || node.panel_version || 'v?'}</span>
                    </div>
                  </div>

                  <div className="registered-fleet__meta">
                    <span className="registered-fleet__scheme">{node.scheme || 'https'}</span>
                    <span className="registered-fleet__address">{getNodeAddress(node)}</span>
                  </div>

                  <div className="registered-fleet__status-row">
                    <strong className={`is-${status}`}>{t(`nodes.${status}`)}</strong>
                    <span>{node.latency ? `${node.latency}ms` : '-'}</span>
                    <span className={node.read_only ? 'is-ro' : 'is-rw'}>{node.read_only ? 'RO' : 'RW'}</span>
                  </div>

                  {node.error && <div className="registered-fleet__error">{node.error}</div>}

                  <div className="registered-fleet__actions">
                    <button type="button" className="registered-fleet__action-btn" onClick={onOpenNodes} title={t('common.edit')} aria-label={t('common.edit')}>
                      <UIIcon name="edit" size={12} />
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </aside>
    </>
  );
};
