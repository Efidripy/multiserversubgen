import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight, Edit3, Pause, Play, RefreshCw, Trash2 } from 'lucide-react';
import {
  deleteNode,
  getRegisteredFleetOverview,
  getRegisteredFleetSnapshotOverview,
  NODES_CHANGED_EVENT,
  type FleetNode,
} from '../api/nodes';
import { restartXray, stopXray } from '../api/serverOps';
import { useToast } from './Toast';

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
  onEditNode?: (node: FleetNode) => void;
  onSummaryChange?: (summary: FleetSummary) => void;
}

type UiFleetNode = {
  id: number;
  name: string;
  version: string;
  address: string;
  latency: string;
  sourceType: string;
  status: 'online' | 'offline' | 'error';
  access: 'RW' | 'RO';
  record: FleetNode;
  error?: string;
};

const fleetActionButtonClass =
  'flex h-5 w-5 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] text-gray-500 transition-colors hover:border-cyan-400/30 hover:text-cyan-300';

const fleetDeleteButtonClass =
  'flex h-5 w-5 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] text-slate-500 transition-colors hover:border-red-400/30 hover:text-red-400 disabled:cursor-not-allowed disabled:opacity-50';

const isReadOnly = (value: unknown) => value === true || Number(value) === 1;

const cleanPanelUrl = (rawAddress: string) => {
  const normalized = rawAddress.startsWith('http') ? rawAddress : `https://${rawAddress}`;
  try {
    const url = new URL(normalized);
    url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    const path = url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '');
    return `${url.protocol}//${url.host}${path}`;
  } catch {
    return normalized.replace(/\/\/[^:@/]+:[^@/]+@/, '//');
  }
};

const skeletonLine = (className: string) => (
  <span className={`block animate-pulse rounded bg-[#182133] ${className}`} />
);

const toUiNode = (node: FleetNode, index: number): UiFleetNode => {
  const rawAddress = node.panel_url || node.url || `${node.scheme || 'https'}://${node.ip || node.name}${node.port ? `:${node.port}` : ''}`;
  return {
    id: node.id || index + 1,
    name: node.name || `NODE-${index + 1}`,
    version: node.panel_version || node.api_version || 'v3',
    address: cleanPanelUrl(rawAddress),
    sourceType: node.source_type || 'xui',
    latency: node.latency ? `${node.latency}ms` : '-',
    status: node.available === true ? 'online' : node.available === false ? 'offline' : 'error',
    access: isReadOnly(node.read_only) ? 'RO' : 'RW',
    record: node,
    error: node.error,
  };
};

export function RegisteredFleetPanel({
  collapsed,
  setCollapsed,
  onOpenNodes,
  onEditNode,
  onSummaryChange,
}: RegisteredFleetPanelProps) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [nodes, setNodes] = useState<UiFleetNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingNodeId, setDeletingNodeId] = useState<number | null>(null);
  const [actionNodeKey, setActionNodeKey] = useState<string | null>(null);

  const load = useCallback(async (options: { live?: boolean } = {}) => {
    setLoading(true);
    setError(null);
    try {
      const payload = options.live
        ? await getRegisteredFleetOverview()
        : await getRegisteredFleetSnapshotOverview();
      setNodes(payload.map(toUiNode));
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Unable to load registered servers');
      setNodes((current) => current);
    } finally {
      setLoaded(true);
      setLoading(false);
    }
  }, []);

  const handleDelete = async (node: UiFleetNode) => {
    if (deletingNodeId !== null) return;
    if (!window.confirm(t('nodes.confirmDelete'))) return;

    setDeletingNodeId(node.id);
    setError(null);
    try {
      await deleteNode(node.id);
      setNodes((current) => current.filter((item) => item.id !== node.id));
      await load();
    } catch (err: any) {
      const message = err?.response?.data?.detail || err?.message || t('nodes.deleteFailed');
      setError(message);
      toast(message, 'error');
    } finally {
      setDeletingNodeId(null);
    }
  };

  const runNodeAction = async (
    node: UiFleetNode,
    action: 'restart' | 'stop',
    command: (nodeId: number) => Promise<unknown>,
    successKey: string,
    failureKey: string,
  ) => {
    const key = `${node.id}:${action}`;
    if (actionNodeKey !== null) return;
    setActionNodeKey(key);
    setError(null);
    try {
      await command(node.id);
      toast(t(successKey, { node: node.name }), 'success');
      await load({ live: true });
    } catch (err: any) {
      const message = err?.response?.data?.detail || err?.response?.data?.error || err?.message || t(failureKey, { node: node.name });
      setError(message);
      toast(message, 'error');
    } finally {
      setActionNodeKey(null);
    }
  };

  const handleRestart = (node: UiFleetNode) => {
    void runNodeAction(node, 'restart', restartXray, 'serverStatus.restartSentNode', 'serverStatus.restartFailedNode');
  };

  const handleStop = (node: UiFleetNode) => {
    if (!window.confirm(t('serverStatus.confirmStopXrayNode', { node: node.name }))) return;
    void runNodeAction(node, 'stop', stopXray, 'serverStatus.xrayStoppedNode', 'serverStatus.stopXrayFailedNode');
  };

  useEffect(() => {
    load();
    const interval = window.setInterval(load, 30000);
    return () => window.clearInterval(interval);
  }, [load]);

  useEffect(() => {
    const handleNodesChanged = () => {
      void load();
    };
    window.addEventListener(NODES_CHANGED_EVENT, handleNodesChanged);
    return () => window.removeEventListener(NODES_CHANGED_EVENT, handleNodesChanged);
  }, [load]);

  const counts = useMemo(() => {
    const online = nodes.filter((node) => node.status === 'online').length;
    const offline = nodes.filter((node) => node.status === 'offline').length;
    const checking = nodes.filter((node) => node.status === 'error').length;
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

  const initialLoading = loading && !loaded;

  return (
    <>
      <div
        className={`xl:hidden fixed inset-0 bg-black/50 z-30 transition-all duration-300 ${
          collapsed ? 'opacity-0 pointer-events-none backdrop-blur-0' : 'opacity-100 pointer-events-auto backdrop-blur-sm'
        }`}
        onClick={() => setCollapsed(true)}
        aria-hidden="true"
      />

      {collapsed && (
        <button
          onClick={() => setCollapsed(false)}
          className="fixed right-2 top-[72px] z-30 flex h-12 w-8 items-center justify-center rounded-lg border border-cyan-500/20 bg-[#0f1420] shadow-[0_18px_42px_rgba(0,0,0,0.36),inset_0_1px_0_rgba(103,232,249,0.06)] transition-all hover:border-cyan-300/40 hover:bg-[#111827] xl:hidden group"
          title={t('nodes.registeredFleet')}
          aria-label={t('nodes.registeredFleet')}
          aria-expanded="false"
          type="button"
        >
          <ChevronLeft className="w-4 h-4 text-cyan-300/70 group-hover:text-cyan-300" />
        </button>
      )}

      <aside
        className={`fleet-panel fixed bottom-0 right-0 top-16 z-40 w-[calc(100vw-1rem)] max-w-[420px] transition-[width,transform] duration-300 ${
          collapsed
            ? 'pointer-events-none translate-x-full xl:pointer-events-auto xl:bottom-[25px] xl:top-24 xl:w-8 xl:translate-x-0 xl:pt-0'
            : 'translate-x-0 xl:bottom-[25px] xl:top-0 xl:w-[420px] xl:pt-24'
        }`}
      >
        <div
          className={`relative flex h-full min-w-0 flex-col overflow-hidden rounded-l-lg border border-r-0 border-cyan-500/20 shadow-[0_18px_50px_rgba(0,0,0,0.22),inset_0_1px_0_rgba(103,232,249,0.06)] ${
            collapsed ? 'bg-[#0a0e1a]' : 'bg-[#0f1420]'
          }`}
        >
          <button
            onClick={() => setCollapsed(!collapsed)}
            className={`absolute inset-y-0 left-0 z-10 flex w-8 items-center justify-center rounded-l-lg bg-[#0a0e1a] transition-colors hover:bg-[#111827] group ${
              collapsed ? 'right-0 w-full' : 'border-r border-cyan-500/20'
            }`}
            title={collapsed ? t('nodes.registeredFleet') : t('common.close')}
            aria-label={collapsed ? t('nodes.registeredFleet') : t('common.close')}
            aria-expanded={!collapsed}
            type="button"
          >
            {collapsed ? (
              <ChevronLeft className="w-4 h-4 text-cyan-300/70 group-hover:text-cyan-300" />
            ) : (
              <ChevronRight className="w-4 h-4 text-cyan-300/70 group-hover:text-cyan-300" />
            )}
          </button>

          <div
            className={`flex min-h-0 flex-1 flex-col pb-3 pr-3 pt-3 transition-opacity duration-200 ${
              collapsed ? 'pointer-events-none pl-0 opacity-0 xl:hidden' : 'pl-10 opacity-100'
            }`}
          >
            <div className="flex-shrink-0 rounded-lg border border-cyan-500/20 bg-[#0d1b2b] px-3 py-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-mono text-sm font-medium uppercase tracking-[0.14em] text-cyan-300">{t('nodes.registeredFleet')}</h2>
                  <div className="mt-1 flex flex-wrap gap-3">
                    <span className="font-mono text-[10px] font-light text-green-400">Online: <strong className="font-medium tabular-nums">{counts.online}</strong></span>
                    <span className="font-mono text-[10px] font-light text-yellow-400">Error: <strong className="font-medium tabular-nums">{counts.checking}</strong></span>
                    <span className="font-mono text-[10px] font-light text-red-400">Offline: <strong className="font-medium tabular-nums">{counts.offline}</strong></span>
                  </div>
                </div>
                  <button
                    className="rounded-md border border-cyan-300/25 bg-gradient-to-r from-cyan-400/90 to-fuchsia-400/90 px-3 py-1.5 font-mono text-xs font-medium tracking-wide text-white disabled:opacity-50"
                    onClick={() => void load({ live: true })}
                    disabled={loading}
                    type="button"
                  >
                  {t('nodes.testAll')}
                </button>
              </div>
              <p className="font-mono text-xs font-light leading-5 text-gray-400">{t('nodes.fleetHint')}</p>
              {error && (
                <div className="mt-2 rounded-md border border-red-400/20 bg-red-950/20 px-2.5 py-2 font-mono text-[11px] font-light text-red-200/80">
                  {error}
                </div>
              )}
            </div>

            <div id="fleet-scroll-container" className="flex-1 min-h-0 overflow-y-scroll overflow-x-hidden scrollbar-none">
              <div className="space-y-1 py-1.5">
                {initialLoading ? Array.from({ length: 8 }, (_, index) => (
                  <article key={index} className="rounded-lg border border-cyan-500/15 bg-[#0a0e1a] px-2.5 py-1.5">
                    <div className="mb-1 flex items-center gap-1.5">
                      {skeletonLine('h-2.5 w-2.5 rounded-full')}
                      {skeletonLine('h-4 w-28')}
                      {skeletonLine('h-3 w-8')}
                    </div>
                    <div className="space-y-1 pl-4">
                      {skeletonLine('h-3 w-full')}
                      {skeletonLine('h-3 w-3/4')}
                    </div>
                    <div className="mt-2 flex items-center gap-1.5">
                      {Array.from({ length: 5 }, (_, actionIndex) => (
                        <span key={actionIndex} className="h-5 w-5 animate-pulse rounded-md border border-cyan-500/20 bg-[#182133]" />
                      ))}
                    </div>
                  </article>
                )) : nodes.length === 0 && !error ? (
                  <div className="rounded-lg border border-cyan-500/15 bg-[#0a0e1a] px-3 py-4 text-center font-mono text-[11px] font-light text-gray-400">
                    {t('nodes.noRegisteredServersFound', { defaultValue: 'No registered servers found' })}
                  </div>
                ) : nodes.map((node) => {
                  const isDeleting = deletingNodeId === node.id;
                  const isRestarting = actionNodeKey === `${node.id}:restart`;
                  const isStopping = actionNodeKey === `${node.id}:stop`;
                  return (
                    <article key={node.id} className={`rounded-lg border border-cyan-500/15 bg-[#0a0e1a] px-2.5 py-1.5 transition-all duration-200 hover:border-cyan-300/30 hover:bg-[#0b101b] ${isDeleting ? 'opacity-50' : ''}`}>
                    <div className="mb-0.5">
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                          node.status === 'online' ? 'bg-green-400' : node.status === 'error' ? 'bg-yellow-400' : 'bg-red-400'
                        }`} />
                        <span className="min-w-0 truncate text-sm font-medium text-white" title={node.name}>{node.name}</span>
                        <span className="flex-shrink-0 text-xs font-light text-gray-500">{node.version}</span>
                      </div>

                      <div className="text-[11px] space-y-0.5 pl-4 min-w-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="flex-shrink-0 font-mono text-green-400">{node.address.startsWith('http://') ? 'http' : 'https'}</span>
                          <span className="min-w-0 truncate font-mono font-light text-cyan-100" title={node.address}>{node.address.replace(/^https?:\/\//, '')}</span>
                        </div>
                        <div className="flex items-center gap-2 text-gray-400">
                          <span className="font-mono tabular-nums text-gray-500">{node.latency}</span>
                          <span className={`font-medium ${
                            node.status === 'online' ? 'text-green-400' : node.status === 'error' ? 'text-yellow-400' : 'text-red-400'
                          }`}>{node.status}</span>
                          <span className="rounded border border-cyan-300/25 bg-cyan-400/10 px-2 py-0.5 font-mono text-[10px] font-medium uppercase text-cyan-300">
                            {node.sourceType}
                          </span>
                          <span className={`rounded border px-2 py-0.5 text-[10px] font-medium ${
                            node.access === 'RW' ? 'border-cyan-300/25 bg-cyan-400/10 text-cyan-300' : 'border-yellow-300/25 bg-yellow-400/10 text-yellow-300'
                          }`}>
                            {node.access}
                          </span>
                        </div>
                        {node.error && (
                          <div className="pt-0.5 text-red-400 font-mono text-[10px]">{node.error}</div>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-start gap-1.5 pt-1">
                      <button
                        className={fleetActionButtonClass}
                        type="button"
                        title={t('serverStatus.restartXray')}
                        aria-label={t('serverStatus.restartXray')}
                        onClick={() => handleRestart(node)}
                        disabled={actionNodeKey !== null}
                      >
                        {isRestarting ? <RefreshCw className="w-3.5 h-3.5 animate-spin opacity-60" /> : <Play className="w-3.5 h-3.5 opacity-60" />}
                      </button>
                      <button
                        className={fleetActionButtonClass}
                        type="button"
                        title={t('serverStatus.stopXray')}
                        aria-label={t('serverStatus.stopXray')}
                        onClick={() => handleStop(node)}
                        disabled={actionNodeKey !== null}
                      >
                        {isStopping ? <RefreshCw className="w-3.5 h-3.5 animate-spin opacity-60" /> : <Pause className="w-3.5 h-3.5 opacity-60" />}
                      </button>
                      <button className={fleetActionButtonClass} type="button" title="Refresh" onClick={() => void load({ live: true })}>
                        <RefreshCw className="w-3.5 h-3.5 opacity-60" />
                      </button>
                      <button
                        className={fleetActionButtonClass}
                        type="button"
                        title="Edit"
                        onClick={() => {
                          if (onEditNode) {
                            onEditNode(node.record);
                            return;
                          }
                          onOpenNodes?.();
                        }}
                      >
                        <Edit3 className="w-3.5 h-3.5 opacity-60" />
                      </button>
                      <button
                        className={fleetDeleteButtonClass}
                        type="button"
                        title={t('common.delete')}
                        aria-label={t('common.delete')}
                        disabled={deletingNodeId !== null}
                        onClick={() => handleDelete(node)}
                      >
                        <Trash2 className={`w-3.5 h-3.5 opacity-60 ${isDeleting ? 'animate-pulse' : ''}`} />
                      </button>
                    </div>
                    </article>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
