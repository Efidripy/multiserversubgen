import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { downloadNodeBackup } from '../api/backup';
import {
  checkNodeConnection,
  createNode,
  deleteNode,
  dispatchNodesChanged,
  getNodeDashboardOverview,
  getNodePanelUpdateInfo,
  updateNode,
  type NodeRecord,
} from '../api/nodes';
import { restartXray } from '../api/serverOps';
import { useTheme } from '../contexts/ThemeContext';
import { UIIcon } from './UIIcon';
import { useToast } from './Toast';
import EmptyState from './EmptyState';
import {
  buildNodeEditPayload,
  buildPanelUrl,
  emptyNodeConnectionForm,
  nodeToEditForm,
  type NodeConnectionFormData,
} from './nodeEditForm';

type Node = NodeRecord;

interface BatchPreviewRow {
  name: string;
  url: string;
  user?: string;
  password?: string;
  bearer_token?: string;
}

interface NodeManagerProps {
  onReload: () => void;
  showIntake?: boolean;
  showIntakeStrip?: boolean;
  showFleet?: boolean;
  dashboardMode?: boolean;
  includeCounts?: boolean;
  openIntakeSignal?: number;
  editNode?: NodeRecord | null;
  openEditSignal?: number;
}

const NODE_STATUS_CACHE_KEY = 'sub_manager_node_status_cache_v1';
const NODE_LIST_CACHE_KEY = 'sub_manager_node_list_cache_v1';
const NODE_SNAPSHOT_TTL_MS = 20_000;

const getNodeTags = (node: Node): string[] => Array.isArray(node.tags) ? node.tags : [];

const normalizeTags = (tags: string[]): string[] =>
  Array.from(new Set(tags.map((tag) => tag.trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b));

type NodeSnapshotPayload = {
  nodes: Node[];
  statuses: Record<number, boolean | null>;
  clientCounts: Record<number, number>;
  inboundCounts: Record<number, number>;
  countsIncluded: boolean;
};

let sharedNodeSnapshot: NodeSnapshotPayload | null = null;
let sharedNodeSnapshotTs = 0;
let sharedNodeSnapshotInFlight: Promise<NodeSnapshotPayload> | null = null;
let sharedNodeSnapshotInFlightIncludesCounts = false;

const getNodeDisplayAddress = (node: Node): string => {
  if (node.url) {
    try {
      return new URL(node.url).host;
    } catch {
      return node.url.replace(/^https?:\/\//, '');
    }
  }
  const host = node.ip || node.name;
  const port = node.port ? `:${node.port}` : '';
  return `${host}${port}`;
};

const getNodePanelUrl = (node: Node): string => {
  if (node.url) return node.url;
  const scheme = node.scheme || 'http';
  const host = node.ip || node.name;
  const port = node.port ? `:${node.port}` : '';
  const basePath = (node.base_path || '').replace(/^\/|\/$/g, '');
  return `${scheme}://${host}${port}${basePath ? `/${basePath}/` : '/'}`;
};

export const NodeManager: React.FC<NodeManagerProps> = ({
  onReload,
  showIntake = true,
  showIntakeStrip = false,
  showFleet = true,
  dashboardMode = false,
  includeCounts,
  openIntakeSignal,
  editNode,
  openEditSignal,
}) => {
  const { colors } = useTheme();
  const { toast } = useToast();
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [nodeStatuses, setNodeStatuses] = useState<Record<number, boolean | null>>({});
  const [nodeVersions, setNodeVersions] = useState<Record<number, string>>({});
  const [nodePing, setNodePing] = useState<Record<number, number>>({});
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<number>>(new Set());
  const [nodeClientCounts, setNodeClientCounts] = useState<Record<number, number>>({});
  const [nodeInboundCounts, setNodeInboundCounts] = useState<Record<number, number>>({});
  const [filterTag, setFilterTag] = useState<string>('');
  const saveNodeTags = async (nodeId: number, tags: string[]) => {
    const nextTags = normalizeTags(tags);
    try {
      await updateNode(nodeId, { tags: nextTags });
      setNodes(prev => {
        const nextNodes = prev.map(node => node.id === nodeId ? { ...node, tags: nextTags } : node);
        if (sharedNodeSnapshot) {
          sharedNodeSnapshot = { ...sharedNodeSnapshot, nodes: nextNodes };
        }
        try {
          localStorage.setItem(NODE_LIST_CACHE_KEY, JSON.stringify(nextNodes));
        } catch {
          // Ignore cache failures.
        }
        return nextNodes;
      });
      setSuccess(t('nodes.tagsSaved'));
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.tagsSaveFailed'));
    }
  };
  const allTags = Array.from(new Set(nodes.flatMap(getNodeTags))).sort();
  const [statusLoading, setStatusLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [addMode, setAddMode] = useState<'form' | 'batch'>('form');
  const [formData, setFormData] = useState<NodeConnectionFormData>(emptyNodeConnectionForm);
  const [batchText, setBatchText] = useState('');
  const [batchPreview, setBatchPreview] = useState<BatchPreviewRow[]>([]);
  const [batchAdded, setBatchAdded] = useState(false);
  const [error, setErrorRaw] = useState('');
  const [success, setSuccessRaw] = useState('');
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setError = useCallback((msg: string) => {
    setErrorRaw(msg);
    if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    if (msg) errorTimerRef.current = setTimeout(() => setErrorRaw(''), 6000);
  }, []);

  const setSuccess = useCallback((msg: string) => {
    setSuccessRaw(msg);
    if (successTimerRef.current) clearTimeout(successTimerRef.current);
    if (msg) successTimerRef.current = setTimeout(() => setSuccessRaw(''), 5000);
  }, []);

  const resetIntake = useCallback(() => {
    setFormData(emptyNodeConnectionForm());
    setBatchText('');
    setBatchPreview([]);
    setBatchAdded(false);
    setAddMode('form');
  }, []);

  const closeIntakeAndNotify = useCallback(() => {
    setShowForm(false);
    window.setTimeout(() => dispatchNodesChanged({ action: 'create' }), 0);
  }, []);

  const [editingNode, setEditingNode] = useState<Node | null>(null);
  const [editingForm, setEditingForm] = useState<NodeConnectionFormData>(emptyNodeConnectionForm);
  const [showEditModal, setShowEditModal] = useState(false);
  const [checkingConnection, setCheckingConnection] = useState(false);
  const [readOnlyUpdating, setReadOnlyUpdating] = useState<Record<number, boolean>>({});
  const showIntakeController = showIntake || showIntakeStrip;

  const invalidateSharedSnapshot = () => {
    sharedNodeSnapshot = null;
    sharedNodeSnapshotTs = 0;
  };

  useEffect(() => {
    if (openIntakeSignal === undefined || openIntakeSignal <= 0) return;
    resetIntake();
    setSuccess('');
    setError('');
    setShowForm(true);
  }, [openIntakeSignal, resetIntake, setError, setSuccess]);

  useEffect(() => {
    if (openEditSignal === undefined || openEditSignal <= 0 || !editNode) return;
    setEditingNode(editNode);
    setEditingForm(nodeToEditForm(editNode));
    setError('');
    setSuccess('');
    setShowEditModal(true);
  }, [editNode, openEditSignal, setError, setSuccess]);

  useEffect(() => {
    try {
      const rawNodes = localStorage.getItem(NODE_LIST_CACHE_KEY);
      if (rawNodes) {
        const parsed = JSON.parse(rawNodes) as Node[];
        if (Array.isArray(parsed)) {
          setNodes(parsed);
        }
      }
      const rawStatuses = localStorage.getItem(NODE_STATUS_CACHE_KEY);
      if (rawStatuses) {
        const parsed = JSON.parse(rawStatuses) as Record<number, boolean | null>;
        if (parsed && typeof parsed === 'object') {
          setNodeStatuses(parsed);
        }
      }
    } catch {
      // Ignore malformed cache.
    }
  }, []);

  const loadNodes = async () => {
    if (!showFleet) {
      setStatusLoading(false);
      return;
    }

    try {
      const now = Date.now();
      const shouldIncludeCounts = includeCounts ?? !dashboardMode;
      if (
        sharedNodeSnapshot &&
        now - sharedNodeSnapshotTs < NODE_SNAPSHOT_TTL_MS &&
        (!shouldIncludeCounts || sharedNodeSnapshot.countsIncluded)
      ) {
        setNodes(sharedNodeSnapshot.nodes);
        setNodeStatuses(sharedNodeSnapshot.statuses);
        setNodeClientCounts(sharedNodeSnapshot.clientCounts);
        setNodeInboundCounts(sharedNodeSnapshot.inboundCounts);
        setStatusLoading(false);
        return;
      }

      if (!sharedNodeSnapshotInFlight || (shouldIncludeCounts && !sharedNodeSnapshotInFlightIncludesCounts)) {
        sharedNodeSnapshotInFlightIncludesCounts = shouldIncludeCounts;
        sharedNodeSnapshotInFlight = (async () => {
          const overview = await getNodeDashboardOverview({ includeCounts: shouldIncludeCounts });
          const nodeList = overview.nodes;
          const payload: NodeSnapshotPayload = {
            nodes: nodeList,
            statuses: overview.statuses,
            clientCounts: overview.clientCounts,
            inboundCounts: overview.inboundCounts,
            countsIncluded: shouldIncludeCounts,
          };
          sharedNodeSnapshot = payload;
          sharedNodeSnapshotTs = Date.now();

          try {
            localStorage.setItem(NODE_LIST_CACHE_KEY, JSON.stringify(nodeList));
            localStorage.setItem(NODE_STATUS_CACHE_KEY, JSON.stringify(overview.statuses));
          } catch {
            // Ignore cache failures.
          }

          return payload;
        })().finally(() => {
          sharedNodeSnapshotInFlight = null;
          sharedNodeSnapshotInFlightIncludesCounts = false;
        });
      }

      setStatusLoading(true);
      const payload = await sharedNodeSnapshotInFlight;
      setNodes(payload.nodes);
      setNodeStatuses(payload.statuses);
      setNodeClientCounts(payload.clientCounts);
      setNodeInboundCounts(payload.inboundCounts);
      setStatusLoading(false);

      // Fetch visible version/latency enrichment in the background.
      payload.nodes.forEach((node: { id: number; name: string }) => {
        if (payload.statuses[node.id] !== true) return;
        const t0 = Date.now();
        getNodePanelUpdateInfo(node.id)
          .then(res => {
            setNodePing(prev => ({ ...prev, [node.id]: Date.now() - t0 }));
            const ver = res?.currentVersion ?? res?.current_version;
            if (ver) setNodeVersions(prev => ({ ...prev, [node.id]: ver }));
          })
          .catch(() => {});
      });
    } catch (err) {
      console.error('Failed to load nodes:', err);
      setError(t('nodes.loadFailed'));
      setStatusLoading(false);
    }
  };

  useEffect(() => {
    if (showFleet) {
      loadNodes();
    }
  }, []);

  const filteredNodes = nodes.filter(n => !filterTag || getNodeTags(n).includes(filterTag));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');

    const panelUrl = buildPanelUrl(formData.url, formData.port);
    if (!panelUrl) {
      setError(t('nodes.fillConnectionFields'));
      setLoading(false);
      return;
    }

    const hasToken = formData.bearer_token.trim();
    const hasCredentials = formData.user.trim() && formData.password.trim();

    if (!hasToken && !hasCredentials) {
      setError(t('nodes.fillConnectionFields'));
      setLoading(false);
      return;
    }

    try {
      const payload: { name: string; url: string; bearer_token?: string; user?: string; password?: string } = {
        name: formData.name.trim(),
        url: panelUrl,
      };
      
      if (hasToken) {
        payload.bearer_token = formData.bearer_token.trim();
      } else {
        payload.user = formData.user.trim();
        payload.password = formData.password;
      }

      await createNode(payload, { emitChange: false });
      resetIntake();
      closeIntakeAndNotify();
      setSuccess(t('nodes.addSuccess'));
      toast(t('nodes.addSuccess'), 'success');
      invalidateSharedSnapshot();
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.addFailed'));
    } finally {
      setLoading(false);
    }
  };

  const parseBatchText = () => {
    setError('');
    const lines = batchText.split('\n').map((line) => line.trim()).filter(Boolean);
    const rows: BatchPreviewRow[] = lines.map((line, idx) => {
      const parts = line.split(/\s+/);
      const row: BatchPreviewRow = {
        name: `Server-${idx + 1}`,
        url: parts[0] || '',
      };
      
      // Check if second part is bearer token (starts with "bearer:")
      if (parts[1]?.startsWith('bearer:')) {
        row.bearer_token = parts[1].substring(7); // Remove "bearer:" prefix
      } else {
        row.user = parts[1] || '';
        row.password = parts[2] || '';
      }
      
      return row;
    });
    setBatchPreview(rows);
    setBatchAdded(false);
  };

  const handleBatchAddAll = async () => {
    if (batchPreview.length === 0) return;
    setLoading(true);
    setError('');
    setSuccess('');
    try {
      const results = await Promise.allSettled(
        batchPreview.map((row) => createNode(row, { emitChange: false }))
      );
      const succeeded = results.filter((result) => result.status === 'fulfilled').length;
      const failed = results.length - succeeded;
      if (failed > 0) {
        setSuccess(t('nodes.batchAdded', { count: succeeded }));
        setError(t('nodes.batchFailed', { count: failed }));
      } else {
        resetIntake();
        closeIntakeAndNotify();
        setSuccess(t('nodes.batchAdded', { count: succeeded }));
        toast(t('nodes.batchAdded', { count: succeeded }), 'success');
      }
      if (succeeded > 0) {
        if (failed > 0) {
          dispatchNodesChanged({ action: 'create' });
        }
        invalidateSharedSnapshot();
        loadNodes();
        onReload();
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.batchAddFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleModeSwitch = (mode: 'form' | 'batch') => {
    setAddMode(mode);
    setFormData(emptyNodeConnectionForm());
    setBatchText('');
    setBatchPreview([]);
    setBatchAdded(false);
    setError('');
    setSuccess('');
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('nodes.confirmDelete'))) return;
    setLoading(true);
    setError('');
    setSuccess('');
    try {
      await deleteNode(id);
      invalidateSharedSnapshot();
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.deleteFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleToggleReadOnly = async (node: Node) => {
    const nextReadOnly = !Boolean(node.read_only);
    setReadOnlyUpdating((prev) => ({ ...prev, [node.id]: true }));
    setError('');
    setSuccess('');
    try {
      await updateNode(node.id, { read_only: nextReadOnly });
      setNodes((prev) =>
        prev.map((n) => (n.id === node.id ? { ...n, read_only: nextReadOnly } : n))
      );
      invalidateSharedSnapshot();
      setSuccess(t('nodes.switchModeSuccess', { name: node.name, mode: nextReadOnly ? t('nodes.modeReadOnly') : t('nodes.modeWrite') }));
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.switchModeFailed'));
    } finally {
      setReadOnlyUpdating((prev) => ({ ...prev, [node.id]: false }));
    }
  };

  const handleEditClick = (node: Node) => {
    setEditingNode(node);
    setEditingForm(nodeToEditForm(node));
    setError('');
    setSuccess('');
    setShowEditModal(true);
  };

  const closeEditModal = () => {
    setShowEditModal(false);
    setEditingNode(null);
    setEditingForm(emptyNodeConnectionForm());
    setError('');
  };

  const handleSaveNode = async () => {
    if (!editingNode) return;
    const result = buildNodeEditPayload(editingNode, editingForm);
    if ('error' in result) {
      setError(
        result.error === 'name'
          ? t('nodes.nameEmpty')
          : result.error === 'url'
            ? t('nodes.fillConnectionFields')
            : t('nodes.credentialsIncomplete'),
      );
      return;
    }

    setLoading(true);
    setError('');
    try {
      await updateNode(editingNode.id, result.payload);
      closeEditModal();
      invalidateSharedSnapshot();
      loadNodes();
      onReload();
      setSuccess(t('nodes.updateSuccess'));
      toast(t('nodes.updateSuccess'), 'success');
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.updateFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleCheckConnection = async () => {
    setError('');
    setSuccess('');
    
    const hasToken = formData.bearer_token.trim();
    const hasCredentials = formData.user.trim() && formData.password.trim();
    
    const panelUrl = buildPanelUrl(formData.url, formData.port);
    if (!panelUrl) {
      setError(t('nodes.fillConnectionFields'));
      return;
    }
    
    if (!hasToken && !hasCredentials) {
      setError(t('nodes.fillConnectionFields'));
      return;
    }

    setCheckingConnection(true);
    try {
      const checkData: { url: string; bearer_token?: string; user?: string; password?: string } = { url: panelUrl };
      if (hasToken) {
        checkData.bearer_token = formData.bearer_token.trim();
      } else {
        checkData.user = formData.user.trim();
        checkData.password = formData.password;
      }
      
      const payload = await checkNodeConnection(checkData);
      if (payload.success) {
        const count = Number.isFinite(payload.inbounds_count) ? payload.inbounds_count : null;
        setSuccess(count !== null ? t('nodes.connectionOkWithInbounds', { count }) : t('nodes.connectionOk'));
      } else {
        setError(payload.message || t('nodes.connectionFailed'));
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.connectionCheckFailed'));
    } finally {
      setCheckingConnection(false);
    }
  };

  return (
    <div className={`node-manager${dashboardMode ? ' node-manager--dashboard-root' : ''}${showIntakeStrip ? ' node-manager--intake-strip-mode' : ''}`}>
      {(showIntakeController || showForm) && (
      <section className={showIntakeController ? `panel-block mb-4${showIntakeStrip ? ' node-intake-strip' : ''}` : undefined}>
          {showIntakeController && (
          <>
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title">{t('nodes.intakeTitle')}</h6>
              <p className="panel-block__hint">{t('nodes.intakeHint')}</p>
            </div>
            <button
              className={showIntakeStrip ? 'node-intake-strip__action' : 'btn btn-sm'}
              style={showIntakeStrip ? undefined : { backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
              onClick={() => { setShowForm(!showForm); setSuccess(''); setError(''); }}
            >
              <span className="d-inline-flex align-items-center gap-1">
                <UIIcon name={showForm ? 'x' : 'plus'} size={14} />
                {showForm ? t('common.cancel') : t('nodes.addNode')}
              </span>
            </button>
          </div>

          {error && <div className="alert alert-danger mb-3">{error}</div>}
          {success && <div className="alert alert-success mb-3">{success}</div>}
          </>
          )}

          {showForm && (
            <div className="modal fade show d-block" tabIndex={-1} role="dialog" style={{ backgroundColor: 'rgba(2, 6, 23, 0.66)' }}>
              <div className="modal-dialog modal-lg modal-dialog-scrollable" role="document">
                <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="modal-header" style={{ borderColor: colors.border }}>
                    <h6 className="modal-title" style={{ color: colors.text.primary }}>{t('nodes.intakeTitle')}</h6>
                    <button type="button" className="btn-close" onClick={() => setShowForm(false)} aria-label="Close" />
                  </div>
                  <div className="modal-body">
            <div className="panel-block__stack">
              <div>
                <label className="form-label small" style={{ color: colors.text.secondary }}>{t('nodes.addMode')}</label>
                <div className="panel-inline-actions">
                  <button
                    type="button"
                    className={`seg-tab${addMode === 'form' ? ' seg-tab--active' : ''}`}
                    onClick={() => handleModeSwitch('form')}
                  >
                    {t('nodes.singleForm')}
                  </button>
                  <button
                    type="button"
                    className={`seg-tab${addMode === 'batch' ? ' seg-tab--active' : ''}`}
                    onClick={() => handleModeSwitch('batch')}
                  >
                    {t('nodes.batchText')}
                  </button>
                </div>
              </div>

              {addMode === 'form' ? (
                <form onSubmit={handleSubmit} className="panel-block__stack">
                  <div className="panel-field-grid">
                    <input
                      type="text"
                      name="name"
                      className="form-control"
                      placeholder={t('nodes.nodeLabel')}
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                    <input
                      type="text"
                      name="url"
                      className="form-control"
                      placeholder={t('nodes.nodeUrlPlaceholder')}
                      value={formData.url}
                      onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                    <input
                      type="text"
                      inputMode="numeric"
                      name="port"
                      className="form-control"
                      placeholder={t('inbounds.port')}
                      value={formData.port}
                      onChange={(e) => setFormData({ ...formData, port: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                    <input
                      type="text"
                      name="user"
                      className="form-control"
                      placeholder={t('auth.username')}
                      value={formData.user}
                      onChange={(e) => setFormData({ ...formData, user: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                    <input
                      type="password"
                      name="password"
                      className="form-control"
                      placeholder={t('auth.password')}
                      value={formData.password}
                      onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                  </div>

                  <div className="d-flex align-items-center gap-2 my-1">
                    <hr style={{ flex: 1, borderColor: colors.border, margin: 0 }} />
                    <span className="small" style={{ color: colors.text.secondary, whiteSpace: 'nowrap' }}>{t('common.or').toUpperCase()}</span>
                    <hr style={{ flex: 1, borderColor: colors.border, margin: 0 }} />
                  </div>

                  <div className="panel-block__stack">
                    <div>
                      <label className="form-label small" htmlFor="node-bearer-token" style={{ color: colors.text.secondary }}>
                        {t('nodes.bearerTokenLabel')}
                      </label>
                      <input
                        id="node-bearer-token"
                        type="password"
                        name="bearer_token"
                        className="form-control"
                        placeholder={t('nodes.bearerTokenPlaceholder')}
                        value={formData.bearer_token}
                        onChange={(e) => setFormData({ ...formData, bearer_token: e.target.value })}
                        style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      />
                      <div className="form-text small mt-1" style={{ color: colors.text.secondary }}>
                        {t('nodes.bearerTokenHint')}
                      </div>
                    </div>
                  </div>

                  <div className="panel-inline-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.warning + '33', borderColor: colors.warning + '66', color: colors.warning }}
                      onClick={handleCheckConnection}
                      disabled={loading || checkingConnection}
                    >
                      {checkingConnection ? t('nodes.checking') : t('nodes.checkConnection')}
                    </button>
                    <button
                      type="submit"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                      disabled={loading || checkingConnection}
                    >
                      {loading ? t('nodes.saving') : t('common.save')}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="panel-block__stack">
                  <p className="small mb-0" style={{ color: colors.text.secondary }}>
                    {t('nodes.batchFormat')}: <span className="mono-inline">{t('nodes.batchFormatPasswordExample')}</span> • <span className="mono-inline">{t('nodes.batchFormatBearerExample')}</span>
                  </p>
                  <textarea
                    className="form-control form-control-sm"
                    rows={6}
                    aria-label={t('nodes.batchText')}
                    value={batchText}
                    onChange={(e) => { setBatchText(e.target.value); setBatchPreview([]); setBatchAdded(false); }}
                    placeholder={t('nodes.batchPlaceholder')}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <div className="panel-inline-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                      onClick={parseBatchText}
                      disabled={!batchText.trim()}
                    >
                      {t('nodes.parsePreview')}
                    </button>
                    {batchPreview.length > 0 && (
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ backgroundColor: colors.success, borderColor: colors.success, color: colors.successText }}
                        onClick={handleBatchAddAll}
                        disabled={loading || batchAdded}
                      >
                        {loading ? t('nodes.adding') : t('nodes.addAll', { count: batchPreview.length })}
                      </button>
                    )}
                  </div>

                  {batchPreview.length > 0 && (
                    <div className="table-responsive table-shell">
                      <table className="table table-sm align-middle mb-0" style={{ color: colors.text.primary }}>
                        <thead>
                          <tr style={{ borderColor: colors.border }}>
                            <th>{t('common.name')}</th>
                            <th>{t('nodes.nodeUrl')}</th>
                            <th>{t('auth.username')}</th>
                            <th>{t('auth.password')}</th>
                            <th>{t('nodes.bearerTokenLabel')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {batchPreview.map((row, idx) => (
                            <tr key={idx} style={{ borderColor: colors.border }}>
                              <td>{row.name}</td>
                              <td><small className="mono-inline">{row.url}</small></td>
                              <td>{row.bearer_token ? '—' : row.user}</td>
                              <td>{row.bearer_token ? '—' : row.password}</td>
                              <td>
                                {row.bearer_token
                                  ? <span className="badge" style={{ backgroundColor: colors.accent, color: colors.accentText }}>token</span>
                                  : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {showFleet && (
      <section className={`panel-block h-100${dashboardMode ? ' node-manager--dashboard' : ''}`}>
        {!dashboardMode && <div className="panel-block__header">
          <div>
            <h6 className="panel-block__title">{t('nodes.registeredFleet')}</h6>
            <p className="panel-block__hint">
              {t('nodes.fleetHint')}
              {statusLoading ? ` ${t('nodes.statusSyncing')}` : ''}
            </p>
          </div>
          {!dashboardMode && <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
            title={t('nodes.testAllConnectionsTitle')}
            disabled={statusLoading || nodes.length === 0}
            onClick={async () => {
              setStatusLoading(true);
              const results = await Promise.allSettled(nodes.map(async node => {
                const nodeUrl = getNodePanelUrl(node);
                const connPayload: Record<string, string> = { url: nodeUrl };
                if (node.bearer_token) connPayload.bearer_token = node.bearer_token;
                else { connPayload.user = node.user ?? ''; connPayload.password = node.password ?? ''; }
                try {
                  const payload = await checkNodeConnection(connPayload);
                  return { id: node.id, ok: payload?.success === true };
                } catch { return { id: node.id, ok: false }; }
              }));
              const newStatuses: Record<number, boolean | null> = { ...nodeStatuses };
              results.forEach(r => {
                if (r.status === 'fulfilled') newStatuses[r.value.id] = r.value.ok;
              });
              setNodeStatuses(newStatuses);
              setStatusLoading(false);
              const ok = results.filter(r => r.status === 'fulfilled' && r.value.ok).length;
              const fail = results.length - ok;
              toast(t('nodes.connectionTestResult', { ok, fail }), ok === results.length ? 'success' : fail === results.length ? 'error' : 'warning');
            }}
          >
            ⟳ {t('nodes.testAll')}
          </button>}
        </div>}

        {error && !showIntake && (
          <div className="alert alert-danger mb-3" role="alert">
            {error}
          </div>
        )}

        {selectedNodeIds.size > 0 && !dashboardMode && (
          <div className="d-flex gap-2 mb-2 align-items-center p-2 rounded" style={{ backgroundColor: colors.bg.tertiary, border: `1px solid ${colors.border}` }}>
            <span className="small" style={{ color: colors.text.secondary }}>{t('nodes.selectedInline', { count: selectedNodeIds.size })}</span>
            <button className="btn btn-sm btn-ghost-info"
              title={t('nodes.downloadSelectedBackupsTitle')}
              onClick={async () => {
                if (!window.confirm(t('nodes.confirmDownloadSelectedBackups', { count: selectedNodeIds.size }))) return;
                let ok = 0, fail = 0;
                for (const id of selectedNodeIds) {
                  try {
                    const blob = await downloadNodeBackup(id);
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `backup_node${id}_${new Date().toISOString().slice(0,10)}.db`;
                    a.click();
                    URL.revokeObjectURL(url);
                    ok++;
                  } catch { fail++; }
                }
                toast(t('nodes.backupSelectedResult', { ok, fail }), ok > 0 ? 'success' : 'error');
              }}>
              ⬇ {t('nodes.backup')}
            </button>
            <button className="btn btn-sm btn-ghost-warning"
              title={t('nodes.restartSelectedXrayTitle')}
              onClick={async () => {
                if (!window.confirm(t('nodes.confirmRestartSelectedXray', { count: selectedNodeIds.size }))) return;
                let ok = 0, fail = 0;
                for (const id of selectedNodeIds) {
                  try { await restartXray(id); ok++; }
                  catch { fail++; }
                }
                toast(t('nodes.restartSelectedResult', { ok, fail }), ok > 0 ? 'success' : 'error');
              }}>
              ↺ {t('serverStatus.restartXray')}
            </button>
            <button className="btn btn-sm btn-ghost-accent"
              onClick={() => setSelectedNodeIds(new Set())}>
              ✕ {t('common.clear')}
            </button>
          </div>
        )}

        {nodes.length > 0 ? (
          <>
          {allTags.length > 0 && !dashboardMode && (
            <div className="d-flex gap-1 flex-wrap mb-2 align-items-center">
              <span className="small" style={{ color: colors.text.secondary }}>{t('nodes.tagFilter')}</span>
              <button className="btn btn-sm" style={{ fontSize: '0.72rem', padding: '1px 7px', backgroundColor: !filterTag ? colors.accent : colors.bg.tertiary, borderColor: !filterTag ? colors.accent : colors.border, color: !filterTag ? colors.accentText : colors.text.secondary }}
                onClick={() => setFilterTag('')}>{t('common.all')}</button>
              {allTags.map(tag => (
                <button key={tag} className="btn btn-sm" style={{ fontSize: '0.72rem', padding: '1px 7px', backgroundColor: filterTag === tag ? colors.accent : colors.bg.tertiary, borderColor: filterTag === tag ? colors.accent : colors.border, color: filterTag === tag ? colors.accentText : colors.text.secondary }}
                  onClick={() => setFilterTag(prev => prev === tag ? '' : tag)}>{tag}</button>
              ))}
            </div>
          )}
          {dashboardMode ? (
            <div className="node-manager__fleet-list">
              {filteredNodes.map((node) => {
                const status = nodeStatuses[node.id];
                const statusKey = status === true ? 'online' : status === false ? 'offline' : 'checking';
                const statusLabel = t(`nodes.${statusKey}`);
                return (
                  <article key={node.id} className="registered-fleet__card node-manager__fleet-card">
                    <div className="registered-fleet__main">
                      <span className={`registered-fleet__dot is-${statusKey}`} />
                      <div className="registered-fleet__title">
                        <strong>{node.name}</strong>
                        <span className="registered-fleet__version">{node.api_version || node.panel_version || 'v?'}</span>
                      </div>
                      <button
                        type="button"
                        className="registered-fleet__action-btn node-manager__fleet-edit"
                        onClick={() => handleEditClick(node)}
                        title={t('common.edit')}
                        aria-label={t('common.edit')}
                      >
                        <UIIcon name="edit" size={12} />
                      </button>
                    </div>

                    <div className="registered-fleet__meta">
                      <span className="registered-fleet__scheme">{node.scheme || 'https'}</span>
                      <span className="registered-fleet__address">{getNodeDisplayAddress(node)}</span>
                    </div>

                    <div className="registered-fleet__status-row node-manager__fleet-status-row">
                      <strong className={`is-${statusKey}`}>{statusLabel}</strong>
                      <span>
                        {nodePing[node.id] ? `LAT ${nodePing[node.id]}ms` : 'LAT -'}
                      </span>
                      <span className={node.read_only ? 'is-ro' : 'is-rw'}>{node.read_only ? 'RO' : 'RW'}</span>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
          <div className="table-responsive table-shell">
            <table className={`table table-sm align-middle mb-0${dashboardMode ? ' node-manager__table--dashboard' : ''}`} style={{ color: colors.text.primary }}>
              <thead>
                <tr>
                  {!dashboardMode && (
                    <th style={{ width: '32px' }}>
                      <input type="checkbox" onChange={e => setSelectedNodeIds(e.target.checked ? new Set(nodes.map(n => n.id)) : new Set())}
                        checked={selectedNodeIds.size === nodes.length && nodes.length > 0} />
                    </th>
                  )}
                  <th>{t('common.name')}</th>
                  {!dashboardMode && <th className="col-hide-mobile">{t('nodes.address')}</th>}
                  {!dashboardMode && <th>{t('common.status')}</th>}
                  {!dashboardMode && (
                    <th style={{ width: '1px', whiteSpace: 'nowrap' }}>{t('nodes.access')}</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {filteredNodes.map((node) => {
                  const status = nodeStatuses[node.id];
                  const dotColor = status === true ? colors.success : status === false ? colors.danger : colors.text.secondary;
                  const statusLabel = status === true ? t('nodes.online') : status === false ? t('nodes.offline') : t('nodes.checking');
                  const tags = getNodeTags(node);
                  const panelUrl = getNodePanelUrl(node);
                  return (
                    <React.Fragment key={node.id}>
                      <tr>
                        {!dashboardMode && (
                          <td>
                            <input type="checkbox" checked={selectedNodeIds.has(node.id)}
                              onChange={e => setSelectedNodeIds(prev => { const n = new Set(prev); e.target.checked ? n.add(node.id) : n.delete(node.id); return n; })} />
                          </td>
                        )}
                        <td>
                          <div className={`d-flex align-items-start flex-column gap-1${dashboardMode ? ' node-manager__name-cell node-manager__entry-shell' : ''}`}>
                            <span className={`d-inline-flex align-items-center gap-2${dashboardMode ? ' node-manager__entry-head' : ''}`}>
                              <span className="node-card__dot" style={{ backgroundColor: dotColor }} />
                              <strong>{node.name}</strong>
                              {dashboardMode && (
                                <span
                                  className={`badge node-manager__access-badge${Boolean(node.read_only) ? ' is-ro' : ' is-rw'}`}
                                  style={{
                                    fontSize: '0.6rem',
                                    letterSpacing: '0.08em',
                                  }}
                                >
                                  {Boolean(node.read_only) ? 'RO' : 'RW'}
                                </span>
                              )}
                              {dashboardMode && (
                                <button
                                  className="btn btn-sm node-manager__entry-edit"
                                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                                  onClick={() => handleEditClick(node)}
                                  aria-label={t('common.edit')}
                                  title={t('common.edit')}
                                >
                                  <UIIcon name="edit" size={13} />
                                </button>
                              )}
                              {node.api_version && !dashboardMode && (
                                <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: 4, background: node.api_version === 'v3' ? '#0d6efd22' : '#6c757d22', color: node.api_version === 'v3' ? '#6ea8fe' : '#adb5bd', fontWeight: 600, letterSpacing: '0.03em' }}>
                                  {node.api_version}
                                </span>
                              )}
                            </span>
                            {tags.length > 0 && !dashboardMode && (
                              <div className="d-flex gap-1 flex-wrap">
                                {tags.map(tag => (
                                  <span key={tag} className="badge" style={{ backgroundColor: colors.accent + '22', color: colors.accent, fontSize: '0.62rem', cursor: 'pointer' }}
                                    onClick={() => setFilterTag(prev => prev === tag ? '' : tag)}>{tag}</span>
                                ))}
                              </div>
                            )}
                            {dashboardMode && (
                              <>
                                <div className="node-manager__address-cell node-manager__address-cell--dashboard">
                                  <div className="mono-inline node-manager__address-line">
                                    {node.scheme && (
                                      <span className="badge node-manager__scheme-badge" style={{ backgroundColor: node.scheme === 'https' ? colors.success + '33' : colors.warning + '33', color: node.scheme === 'https' ? colors.success : colors.warning, fontSize: '0.65rem' }}>
                                        {node.scheme}
                                      </span>
                                    )}
                                    {getNodeDisplayAddress(node)}
                                  </div>
                                </div>
                                {(nodePing[node.id] || status !== undefined) && (
                                  <div className="d-flex flex-wrap gap-2 align-items-center node-manager__meta-line" style={{ marginTop: '3px', fontSize: '0.67rem', color: colors.text.tertiary, lineHeight: 1.3 }}>
                                    {nodePing[node.id] && (
                                      <span style={{ color: nodePing[node.id] < 500 ? colors.success : nodePing[node.id] < 2000 ? colors.warning : colors.danger }}>
                                        LAT {nodePing[node.id]}ms
                                      </span>
                                    )}
                                    <span className={`node-manager__meta-status is-${status === true ? 'online' : status === false ? 'offline' : 'checking'}`}>
                                      {statusLabel}
                                    </span>
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        </td>
                        {!dashboardMode && <td className="col-hide-mobile">
                          <div className={`mono-inline${dashboardMode ? ' node-manager__address-line' : ''}`}>
                            {node.scheme && (
                              <span className={`badge me-1${dashboardMode ? ' node-manager__scheme-badge' : ''}`} style={{ backgroundColor: node.scheme === 'https' ? colors.success + '33' : colors.warning + '33', color: node.scheme === 'https' ? colors.success : colors.warning, fontSize: '0.65rem' }}>
                                {node.scheme}
                              </span>
                            )}
                            {getNodeDisplayAddress(node)}
                          </div>
                          {(nodeVersions[node.id] || nodePing[node.id] || nodeClientCounts[node.id] || nodeInboundCounts[node.id]) && (
                            <div className={`d-flex flex-wrap gap-2 align-items-center${dashboardMode ? ' node-manager__meta-line' : ''}`} style={{ marginTop: '3px', fontSize: '0.67rem', color: colors.text.tertiary, lineHeight: 1.3 }}>
                              {!dashboardMode && nodeVersions[node.id] && (
                                <span style={{ fontFamily: 'monospace', opacity: 0.75 }}>{nodeVersions[node.id]}</span>
                              )}
                              {nodePing[node.id] && (
                                <span style={{ color: nodePing[node.id] < 500 ? colors.success : nodePing[node.id] < 2000 ? colors.warning : colors.danger }}>
                                  LAT {nodePing[node.id]}ms
                                </span>
                              )}
                              {dashboardMode && (
                                <span className={`node-manager__meta-status is-${status === true ? 'online' : status === false ? 'offline' : 'checking'}`}>
                                  {statusLabel}
                                </span>
                              )}
                              {!dashboardMode && nodeClientCounts[node.id] ? (
                                <span><UIIcon name="clients" size={10} /> {nodeClientCounts[node.id]}</span>
                              ) : null}
                              {!dashboardMode && nodeInboundCounts[node.id] ? (
                                <span><UIIcon name="inbounds" size={10} /> {nodeInboundCounts[node.id]}</span>
                              ) : null}
                            </div>
                          )}
                        </td>}
                        {!dashboardMode && (
                          <td>
                            <span className={dashboardMode ? 'node-manager__status-pill node-manager__status-pill--dashboard-hidden' : ''} style={{ color: status === true ? colors.success : status === false ? colors.danger : colors.text.secondary }}>
                              {statusLabel}
                            </span>
                          </td>
                        )}
                        {!dashboardMode && (
                          <td style={{ whiteSpace: 'nowrap' }}>
                            <button
                              className={`btn btn-sm ${Boolean(node.read_only) ? 'btn-ghost-warning' : 'btn-ghost-success'}`}
                              onClick={() => handleToggleReadOnly(node)}
                              disabled={loading || Boolean(readOnlyUpdating[node.id])}
                              title={Boolean(node.read_only) ? t('nodes.switchWrite') : t('nodes.switchReadOnly')}
                            >
                              {readOnlyUpdating[node.id] ? '...' : Boolean(node.read_only) ? 'RO' : 'RW'}
                            </button>
                          </td>
                        )}
                      </tr>
                      {/* Action buttons row */}
                      {!dashboardMode && <tr style={{ borderTop: 'none' }}>
                        {!dashboardMode && <td style={{ paddingTop: 0, paddingBottom: '6px', borderTop: 'none' }} />}
                        <td colSpan={4} style={{ paddingTop: 0, paddingBottom: '6px', borderTop: 'none' }}>
                          <div className="node-manager__actions" style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '4px', justifyContent: 'flex-end' }}>
                            {(node.url || node.ip) && !dashboardMode && (
                              <>
                                <a
                                  className="btn btn-sm"
                                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                                  href={panelUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title={t('nodes.openPanelTitle', { url: panelUrl })}
                                >
                                  ↗
                                </a>
                                <button
                                  className="btn btn-sm"
                                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                                  title={t('nodes.copyUrlTitle', { url: panelUrl })}
                                  onClick={() => navigator.clipboard.writeText(panelUrl)}
                                >
                                  📋
                                </button>
                              </>
                            )}
                            {!dashboardMode && <button
                              className="btn btn-sm"
                              style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                              title={t('nodes.testThisConnectionTitle')}
                              onClick={async () => {
                                const nodeUrl = getNodePanelUrl(node);
                                const singlePayload: Record<string, string> = { url: nodeUrl };
                                if (node.bearer_token) singlePayload.bearer_token = node.bearer_token;
                                else { singlePayload.user = node.user ?? ''; singlePayload.password = node.password ?? ''; }
                                const t0 = Date.now();
                                setNodeStatuses(prev => ({ ...prev, [node.id]: null }));
                                try {
                                  const payload = await checkNodeConnection(singlePayload);
                                  const ping = Date.now() - t0;
                                  const ok = payload?.success === true;
                                  setNodeStatuses(prev => ({ ...prev, [node.id]: ok }));
                                  if (ok) setNodePing(prev => ({ ...prev, [node.id]: ping }));
                                  toast(`${node.name}: ${ok ? t('nodes.onlineWithPing', { ping }) : t('nodes.offline')}`, ok ? 'success' : 'error');
                                } catch {
                                  setNodeStatuses(prev => ({ ...prev, [node.id]: false }));
                                  toast(t('nodes.nodeConnectionFailed', { node: node.name }), 'error');
                                }
                              }}
                            >
                              ⟳
                            </button>}
                            {!dashboardMode && <button
                              className="btn btn-sm"
                              style={{ backgroundColor: tags.length > 0 ? colors.accent + '33' : colors.bg.tertiary, borderColor: tags.length > 0 ? colors.accent + '88' : colors.border, color: tags.length > 0 ? colors.accent : colors.text.secondary }}
                              title={tags.length > 0 ? t('nodes.tagsTitle', { tags: tags.join(', ') }) : t('nodes.addTagsTitle')}
                              onClick={() => {
                                const current = tags.join(', ');
                                const input = window.prompt(t('nodes.tagsPrompt', { name: node.name }), current);
                                if (input !== null) {
                                  const newTags = input.split(',').map(t => t.trim()).filter(Boolean);
                                  void saveNodeTags(node.id, newTags);
                                }
                              }}
                            >
                              🏷
                            </button>}
                            <button
                              className="btn btn-sm"
                              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                              onClick={() => handleEditClick(node)}
                              aria-label={t('common.edit')}
                            >
                              <UIIcon name="edit" size={14} />
                            </button>
                            {!dashboardMode && <button
                              className="btn btn-sm"
                              style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: colors.dangerText }}
                              onClick={() => handleDelete(node.id)}
                              aria-label={t('common.delete')}
                            >
                              <UIIcon name="x" size={14} />
                            </button>}
                          </div>
                        </td>
                      </tr>}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}
          </>
        ) : (
          <EmptyState
            icon="⬡"
            title={dashboardMode ? t('nodes.noNodesYet') : t('nodes.noNodesYet')}
            hint={dashboardMode ? t('dashboardSummary.ingressEmptyCopy') : t('nodes.addFirstNodeHint')}
            action={{ label: dashboardMode ? t('nodes.addNode') : `+ ${t('nodes.addNode')}`, onClick: () => setShowForm(true) }}
          />
        )}
      </section>
      )}

      {showEditModal && editingNode && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-dialog-centered modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>{t('nodes.editNode')}</h6>
                <button type="button" className="btn-close" aria-label={t('common.close')} onClick={closeEditModal} />
              </div>
              <form onSubmit={(event) => { event.preventDefault(); handleSaveNode(); }}>
              <div className="modal-body panel-block__stack">
                {error && <div className="alert alert-danger">{error}</div>}
                <div className="panel-field-grid">
                  <input
                    type="text"
                    name="edit-name"
                    className="form-control"
                    aria-label={t('nodes.nodeLabel')}
                    placeholder={t('nodes.nodeLabel')}
                    value={editingForm.name}
                    onChange={(e) => setEditingForm({ ...editingForm, name: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    autoFocus
                    required
                  />
                  <input
                    type="text"
                    name="edit-url"
                    className="form-control"
                    aria-label={t('nodes.nodeUrl')}
                    placeholder={t('nodes.nodeUrlPlaceholder')}
                    value={editingForm.url}
                    onChange={(e) => setEditingForm({ ...editingForm, url: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    required
                  />
                  <input
                    type="text"
                    inputMode="numeric"
                    name="edit-port"
                    className="form-control"
                    aria-label={t('inbounds.port')}
                    placeholder={t('inbounds.port')}
                    value={editingForm.port}
                    onChange={(e) => setEditingForm({ ...editingForm, port: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <input
                    type="text"
                    name="edit-user"
                    className="form-control"
                    aria-label={t('auth.username')}
                    placeholder={t('auth.username')}
                    value={editingForm.user}
                    onChange={(e) => setEditingForm({ ...editingForm, user: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <input
                    type="password"
                    name="edit-password"
                    className="form-control"
                    aria-label={t('nodes.newPasswordOptional')}
                    placeholder={t('nodes.newPasswordOptional')}
                    value={editingForm.password}
                    onChange={(e) => setEditingForm({ ...editingForm, password: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                </div>
                <div>
                  <label className="form-label small" htmlFor="edit-node-bearer-token" style={{ color: colors.text.secondary }}>
                    {t('nodes.bearerTokenLabel')}
                  </label>
                  <input
                    id="edit-node-bearer-token"
                    type="password"
                    name="edit-bearer_token"
                    className="form-control"
                    placeholder={t('nodes.newBearerTokenOptional')}
                    value={editingForm.bearer_token}
                    onChange={(e) => setEditingForm({ ...editingForm, bearer_token: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <div className="form-text small mt-1" style={{ color: colors.text.secondary }}>
                    {t('nodes.editCredentialsHint')}
                  </div>
                </div>
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button type="button" className="btn btn-sm" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }} onClick={closeEditModal}>
                  {t('common.cancel')}
                </button>
                <button type="submit" className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }} disabled={loading}>
                  {loading ? t('nodes.saving') : t('nodes.saveChanges')}
                </button>
              </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
