import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';

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

interface RegisteredFleetPanelProps {
  collapsed: boolean;
  setCollapsed: (value: boolean) => void;
  onOpenNodes?: () => void;
}

const statusLabel = (node: FleetNode) => {
  if (node.available === true) return 'online';
  if (node.available === false) return 'offline';
  return 'checking';
};

const nodeAddress = (node: NodeRecord) => {
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
}) => {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<FleetNode[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
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

  return (
    <>
      {collapsed && (
        <button
          className="registered-fleet-tab"
          onClick={() => setCollapsed(false)}
          title={t('registeredFleet.open')}
          aria-label={t('registeredFleet.open')}
          type="button"
        />
      )}

      <aside className={`registered-fleet${collapsed ? ' is-collapsed' : ''}`}>
        <button
          className="registered-fleet__rail"
          onClick={() => setCollapsed(true)}
          title={t('registeredFleet.collapse')}
          aria-label={t('registeredFleet.collapse')}
          type="button"
        />

        <div className="registered-fleet__inner">
          <header className="registered-fleet__header">
            <div>
              <h2>{t('registeredFleet.title')}</h2>
              <div className="registered-fleet__counts">
                <span className="is-online">{t('registeredFleet.online')}: <strong>{counts.online}</strong></span>
                <span className="is-checking">{t('registeredFleet.checking')}: <strong>{counts.checking}</strong></span>
                <span className="is-offline">{t('registeredFleet.offline')}: <strong>{counts.offline}</strong></span>
              </div>
            </div>
            <button className="registered-fleet__test" onClick={load} disabled={loading} type="button">
              {loading ? t('registeredFleet.testing') : t('registeredFleet.testAll')}
            </button>
          </header>

          <p className="registered-fleet__hint">{t('registeredFleet.hint')}</p>

          <div className="registered-fleet__list">
            {nodes.map((node) => {
              const status = statusLabel(node);
              return (
                <article key={node.id} className="registered-fleet__card">
                  <div className="registered-fleet__main">
                    <span className={`registered-fleet__dot is-${status}`} />
                    <div className="registered-fleet__title">
                      <strong>{node.name}</strong>
                      <span>{node.api_version || node.panel_version || 'v?'}</span>
                    </div>
                  </div>

                  <div className="registered-fleet__meta">
                    <span className="registered-fleet__scheme">{node.scheme || 'https'}</span>
                    <span className="registered-fleet__address">{nodeAddress(node)}</span>
                  </div>

                  <div className="registered-fleet__status-row">
                    <span>{node.latency ? `${node.latency}ms` : '-'}</span>
                    <strong className={`is-${status}`}>{t(`registeredFleet.status.${status}`)}</strong>
                    <span className={node.read_only ? 'is-ro' : 'is-rw'}>{node.read_only ? 'RO' : 'RW'}</span>
                  </div>

                  {node.error && <div className="registered-fleet__error">{node.error}</div>}

                  <div className="registered-fleet__actions">
                    <button type="button" className="registered-fleet__action-btn" onClick={onOpenNodes} title={t('common.edit')} aria-label={t('common.edit')}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button type="button" className="registered-fleet__action-btn" onClick={load} title={t('common.refresh')} aria-label={t('common.refresh')} disabled={loading}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                    </button>
                    <button type="button" className="registered-fleet__action-btn" onClick={() => window.open(node.url || `${node.scheme || 'https'}://${node.ip || node.name}${node.port ? ':'+node.port : ''}`, '_blank')} title={t('registeredFleet.openPanel')} aria-label={t('registeredFleet.openPanel')}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
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
