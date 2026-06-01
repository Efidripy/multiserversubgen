import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
import { UIIcon } from './UIIcon';
import { useToast } from './Toast';
import EmptyState from './EmptyState';

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
  url?: string;
  scheme?: string;
  base_path?: string;
  read_only?: boolean;
  api_version?: string;
  panel_version?: string;
}

interface BatchPreviewRow {
  name: string;
  url: string;
  user?: string;
  password?: string;
  bearer_token?: string;
}

const NODE_STATUS_CACHE_KEY = 'sub_manager_node_status_cache_v1';
const NODE_LIST_CACHE_KEY = 'sub_manager_node_list_cache_v1';
const NODE_SNAPSHOT_TTL_MS = 20_000;

type NodeSnapshotPayload = {
  nodes: Node[];
  statuses: Record<number, boolean | null>;
};

let sharedNodeSnapshot: NodeSnapshotPayload | null = null;
let sharedNodeSnapshotTs = 0;
let sharedNodeSnapshotInFlight: Promise<NodeSnapshotPayload> | null = null;

export const NodeManager: React.FC<{ onReload: () => void; showIntake?: boolean; showFleet?: boolean }> = ({
  onReload,
  showIntake = true,
  showFleet = true,
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
  const NODE_TAGS_KEY = 'sub_manager_node_tags_v1';
  const [nodeTags, setNodeTags] = useState<Record<number, string[]>>(() => {
    try { return JSON.parse(localStorage.getItem(NODE_TAGS_KEY) || '{}'); } catch { return {}; }
  });
  const [filterTag, setFilterTag] = useState<string>('');
  const saveNodeTags = (nodeId: number, tags: string[]) => {
    setNodeTags(prev => {
      const updated = { ...prev, [nodeId]: tags.filter(t => t.trim()) };
      localStorage.setItem(NODE_TAGS_KEY, JSON.stringify(updated));
      return updated;
    });
  };
  const allTags = Array.from(new Set(Object.values(nodeTags).flat())).sort();
  const [statusLoading, setStatusLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [addMode, setAddMode] = useState<'form' | 'batch'>('form');
  const [formData, setFormData] = useState({ name: '', url: '', user: '', password: '', bearer_token: '' });
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
  const [editingNode, setEditingNode] = useState<Node | null>(null);
  const [editingName, setEditingName] = useState('');
  const [showEditModal, setShowEditModal] = useState(false);
  const [checkingConnection, setCheckingConnection] = useState(false);
  const [readOnlyUpdating, setReadOnlyUpdating] = useState<Record<number, boolean>>({});

  const invalidateSharedSnapshot = () => {
    sharedNodeSnapshot = null;
    sharedNodeSnapshotTs = 0;
  };

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
    try {
      const now = Date.now();
      if (sharedNodeSnapshot && now - sharedNodeSnapshotTs < NODE_SNAPSHOT_TTL_MS) {
        setNodes(sharedNodeSnapshot.nodes);
        setNodeStatuses(sharedNodeSnapshot.statuses);
        setStatusLoading(false);
        return;
      }

      if (!sharedNodeSnapshotInFlight) {
        sharedNodeSnapshotInFlight = (async () => {
          const { user, password: pwd } = getAuth();
          const auth = { username: user, password: pwd };
          const nodesRes = await api.get('/v1/nodes', { auth });
          const nodeList = Array.isArray(nodesRes.data) ? nodesRes.data : [];
          const statuses: Record<number, boolean | null> = {};

          await Promise.all(
            nodeList.map(async (node) => {
              try {
                const response = await api.get(`/v1/nodes/${node.id}/server-status`, { auth });
                statuses[node.id] = Boolean(response.data?.available);
              } catch {
                statuses[node.id] = false;
              }
            }),
          );

          const payload: NodeSnapshotPayload = { nodes: nodeList, statuses };
          sharedNodeSnapshot = payload;
          sharedNodeSnapshotTs = Date.now();

          try {
            localStorage.setItem(NODE_LIST_CACHE_KEY, JSON.stringify(nodeList));
            localStorage.setItem(NODE_STATUS_CACHE_KEY, JSON.stringify(statuses));
          } catch {
            // Ignore cache failures.
          }

          return payload;
        })().finally(() => {
          sharedNodeSnapshotInFlight = null;
        });
      }

      setStatusLoading(true);
      const payload = await sharedNodeSnapshotInFlight;
      setNodes(payload.nodes);
      setNodeStatuses(payload.statuses);
      setStatusLoading(false);

      // Fetch versions, ping, and client counts in background for online nodes
      payload.nodes.forEach((node: { id: number; name: string }) => {
        if (payload.statuses[node.id] !== true) return;
        const t0 = Date.now();
        api.get(`/v1/nodes/${node.id}/panel-update-info`, { auth: getAuth() })
          .then(res => {
            setNodePing(prev => ({ ...prev, [node.id]: Date.now() - t0 }));
            const ver = res.data?.currentVersion ?? res.data?.current_version;
            if (ver) setNodeVersions(prev => ({ ...prev, [node.id]: ver }));
          })
          .catch(() => {});
        api.get('/v1/clients', { auth: getAuth(), params: { node_id: node.id } })
          .then(res => {
            const count = (res.data?.clients ?? res.data ?? []).length;
            if (count > 0) setNodeClientCounts(prev => ({ ...prev, [node.id]: count }));
          })
          .catch(() => {});
        api.get(`/v1/nodes/${node.id}/inbounds`, { auth: getAuth() })
          .then(res => {
            const count = (res.data?.inbounds ?? res.data ?? []).length;
            if (count > 0) setNodeInboundCounts(prev => ({ ...prev, [node.id]: count }));
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
    loadNodes();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');

    const urlVal = formData.url.trim();
    if (urlVal && !/^https?:\/\//i.test(urlVal)) {
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
        name: formData.name,
        url: formData.url,
      };
      
      if (hasToken) {
        payload.bearer_token = formData.bearer_token;
      } else {
        payload.user = formData.user;
        payload.password = formData.password;
      }

      const { user: u, password: p } = getAuth();
      await api.post('/v1/nodes', payload, { auth: { username: u, password: p } });
      setFormData({ name: '', url: '', user: '', password: '', bearer_token: '' });
      setSuccess(t('nodes.addSuccess'));
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
      const { user: bu, password: bp } = getAuth();
      const batchAuth = { username: bu, password: bp };
      const results = await Promise.allSettled(
        batchPreview.map((row) => api.post('/v1/nodes', row, { auth: batchAuth }))
      );
      const succeeded = results.filter((result) => result.status === 'fulfilled').length;
      const failed = results.length - succeeded;
      setBatchText('');
      setBatchPreview([]);
      setBatchAdded(true);
      if (failed > 0) {
        setSuccess(t('nodes.batchAdded', { count: succeeded }));
        setError(t('nodes.batchFailed', { count: failed }));
      } else {
        setSuccess(t('nodes.batchAdded', { count: succeeded }));
      }
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.batchAddFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleModeSwitch = (mode: 'form' | 'batch') => {
    setAddMode(mode);
    setFormData({ name: '', url: '', user: '', password: '', bearer_token: '' });
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
      const { user: du, password: dp } = getAuth();
      await api.delete(`/v1/nodes/${id}`, { auth: { username: du, password: dp } });
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
      const { user: ru, password: rp } = getAuth();
      await api.put(
        `/v1/nodes/${node.id}`,
        { read_only: nextReadOnly },
        { auth: { username: ru, password: rp } },
      );
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
    setEditingName(node.name);
    setShowEditModal(true);
  };

  const handleSaveName = async () => {
    if (!editingNode) return;
    const trimmed = editingName.trim();
    if (!trimmed) {
      setError(t('nodes.nameEmpty'));
      return;
    }
    setLoading(true);
    setError('');
    try {
      const { user: eu, password: ep } = getAuth();
      await api.put(`/v1/nodes/${editingNode.id}`, { name: trimmed }, { auth: { username: eu, password: ep } });
      setShowEditModal(false);
      setEditingNode(null);
      invalidateSharedSnapshot();
      loadNodes();
      onReload();
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
    
    if (!formData.url.trim()) {
      setError(t('nodes.fillConnectionFields'));
      return;
    }
    
    if (!hasToken && !hasCredentials) {
      setError(t('nodes.fillConnectionFields'));
      return;
    }

    setCheckingConnection(true);
    try {
      const checkData: { url: string; bearer_token?: string; user?: string; password?: string } = { url: formData.url };
      if (hasToken) {
        checkData.bearer_token = formData.bearer_token;
      } else {
        checkData.user = formData.user;
        checkData.password = formData.password;
      }
      
      const { user: cu, password: cp } = getAuth();
      const res = await api.post('/v1/nodes/check-connection', checkData, { auth: { username: cu, password: cp } });
      const payload = res.data || {};
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
    <div className="node-manager">
      {showIntake && (
      <section className="panel-block mb-4">
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title">{t('nodes.intakeTitle')}</h6>
              <p className="panel-block__hint">{t('nodes.intakeHint')}</p>
            </div>
            <button
              className="btn btn-sm"
              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
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
                      placeholder="https://server:443/path/"
                      value={formData.url}
                      onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
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
      <section className="panel-block h-100">
        <div className="panel-block__header">
          <div>
            <h6 className="panel-block__title">{t('nodes.registeredFleet')}</h6>
            <p className="panel-block__hint">
              {t('nodes.fleetHint')}
              {statusLoading ? ` ${t('nodes.statusSyncing')}` : ''}
            </p>
          </div>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
            title={t('nodes.testAllConnectionsTitle')}
            disabled={statusLoading || nodes.length === 0}
            onClick={async () => {
              setStatusLoading(true);
              const { user, password } = getAuth();
              const results = await Promise.allSettled(nodes.map(async node => {
                const nodeUrl = node.url || `${(node as any).scheme || 'http'}://${node.ip}:${node.port}`;
                try {
                  const res = await api.post('/v1/nodes/check-connection', { url: nodeUrl }, { auth: { username: user, password } });
                  return { id: node.id, ok: res.data?.success === true };
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
          </button>
        </div>

        {selectedNodeIds.size > 0 && (
          <div className="d-flex gap-2 mb-2 align-items-center p-2 rounded" style={{ backgroundColor: colors.bg.tertiary, border: `1px solid ${colors.border}` }}>
            <span className="small" style={{ color: colors.text.secondary }}>{t('nodes.selectedInline', { count: selectedNodeIds.size })}</span>
            <button className="btn btn-sm btn-ghost-info"
              title={t('nodes.downloadSelectedBackupsTitle')}
              onClick={async () => {
                if (!window.confirm(t('nodes.confirmDownloadSelectedBackups', { count: selectedNodeIds.size }))) return;
                const auth = getAuth();
                let ok = 0, fail = 0;
                for (const id of selectedNodeIds) {
                  try {
                    const res = await api.get(`/v1/backup/node/${id}`, { auth, responseType: 'blob' });
                    const url = URL.createObjectURL(res.data);
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
                const { user, password } = getAuth();
                let ok = 0, fail = 0;
                for (const id of selectedNodeIds) {
                  try { await api.post(`/v1/servers/${id}/restart-xray`, {}, { auth: { username: user, password } }); ok++; }
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
          {allTags.length > 0 && (
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
          <div className="table-responsive table-shell">
            <table className="table table-sm align-middle mb-0" style={{ color: colors.text.primary }}>
              <thead>
                <tr>
                  <th style={{ width: '32px' }}>
                    <input type="checkbox" onChange={e => setSelectedNodeIds(e.target.checked ? new Set(nodes.map(n => n.id)) : new Set())}
                      checked={selectedNodeIds.size === nodes.length && nodes.length > 0} />
                  </th>
                  <th>{t('common.name')}</th>
                  <th className="col-hide-mobile">{t('nodes.address')}</th>
                  <th>{t('common.status')}</th>
                  <th style={{ width: '1px', whiteSpace: 'nowrap' }}>{t('nodes.access')}</th>
                </tr>
              </thead>
              <tbody>
                {nodes.filter(n => !filterTag || (nodeTags[n.id] || []).includes(filterTag)).map((node) => {
                  const status = nodeStatuses[node.id];
                  const dotColor = status === true ? colors.success : status === false ? colors.danger : colors.text.secondary;
                  const statusLabel = status === true ? t('nodes.online') : status === false ? t('nodes.offline') : t('nodes.checking');
                  const tags = nodeTags[node.id] || [];
                  const _bp = (node.base_path || '').replace(/^\/|\/$/g, '');
                  const panelUrl = `${node.scheme || 'http'}://${node.ip}:${node.port}${_bp ? '/' + _bp + '/' : '/'}`;
                  return (
                    <React.Fragment key={node.id}>
                      <tr>
                        <td>
                          <input type="checkbox" checked={selectedNodeIds.has(node.id)}
                            onChange={e => setSelectedNodeIds(prev => { const n = new Set(prev); e.target.checked ? n.add(node.id) : n.delete(node.id); return n; })} />
                        </td>
                        <td>
                          <div className="d-flex align-items-start flex-column gap-1">
                            <span className="d-inline-flex align-items-center gap-2">
                              <span className="node-card__dot" style={{ backgroundColor: dotColor }} />
                              <strong>{node.name}</strong>
                              {node.api_version && (
                                <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: 4, background: node.api_version === 'v3' ? '#0d6efd22' : '#6c757d22', color: node.api_version === 'v3' ? '#6ea8fe' : '#adb5bd', fontWeight: 600, letterSpacing: '0.03em' }}>
                                  {node.api_version}
                                </span>
                              )}
                            </span>
                            {tags.length > 0 && (
                              <div className="d-flex gap-1 flex-wrap">
                                {tags.map(tag => (
                                  <span key={tag} className="badge" style={{ backgroundColor: colors.accent + '22', color: colors.accent, fontSize: '0.62rem', cursor: 'pointer' }}
                                    onClick={() => setFilterTag(prev => prev === tag ? '' : tag)}>{tag}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="col-hide-mobile">
                          <div className="mono-inline">
                            {node.scheme && (
                              <span className="badge me-1" style={{ backgroundColor: node.scheme === 'https' ? colors.success + '33' : colors.warning + '33', color: node.scheme === 'https' ? colors.success : colors.warning, fontSize: '0.65rem' }}>
                                {node.scheme}
                              </span>
                            )}
                            {node.ip}:{node.port}
                          </div>
                          {(nodeVersions[node.id] || nodePing[node.id] || nodeClientCounts[node.id] || nodeInboundCounts[node.id]) && (
                            <div className="d-flex flex-wrap gap-2 align-items-center" style={{ marginTop: '3px', fontSize: '0.67rem', color: colors.text.tertiary, lineHeight: 1.3 }}>
                              {nodeVersions[node.id] && (
                                <span style={{ fontFamily: 'monospace', opacity: 0.75 }}>{nodeVersions[node.id]}</span>
                              )}
                              {nodePing[node.id] && (
                                <span style={{ color: nodePing[node.id] < 500 ? colors.success : nodePing[node.id] < 2000 ? colors.warning : colors.danger }}>
                                  {nodePing[node.id]}ms
                                </span>
                              )}
                              {nodeClientCounts[node.id] ? (
                                <span><UIIcon name="clients" size={10} /> {nodeClientCounts[node.id]}</span>
                              ) : null}
                              {nodeInboundCounts[node.id] ? (
                                <span><UIIcon name="inbounds" size={10} /> {nodeInboundCounts[node.id]}</span>
                              ) : null}
                            </div>
                          )}
                        </td>
                        <td>
                          <span style={{ color: status === true ? colors.success : status === false ? colors.danger : colors.text.secondary }}>
                            {statusLabel}
                          </span>
                        </td>
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
                      </tr>
                      {/* Action buttons row */}
                      <tr style={{ borderTop: 'none' }}>
                        <td style={{ paddingTop: 0, paddingBottom: '6px', borderTop: 'none' }} />
                        <td colSpan={4} style={{ paddingTop: 0, paddingBottom: '6px', borderTop: 'none' }}>
                          <div style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '4px', justifyContent: 'flex-end' }}>
                            {(node.url || node.ip) && (
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
                            <button
                              className="btn btn-sm"
                              style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                              title={t('nodes.testThisConnectionTitle')}
                              onClick={async () => {
                                const nodeUrl = node.url || `${(node as any).scheme || 'http'}://${node.ip}:${node.port}`;
                                const t0 = Date.now();
                                setNodeStatuses(prev => ({ ...prev, [node.id]: null }));
                                try {
                                  const res = await api.post('/v1/nodes/check-connection', { url: nodeUrl }, { auth: getAuth() });
                                  const ping = Date.now() - t0;
                                  const ok = res.data?.success === true;
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
                            </button>
                            <button
                              className="btn btn-sm"
                              style={{ backgroundColor: tags.length > 0 ? colors.accent + '33' : colors.bg.tertiary, borderColor: tags.length > 0 ? colors.accent + '88' : colors.border, color: tags.length > 0 ? colors.accent : colors.text.secondary }}
                              title={tags.length > 0 ? t('nodes.tagsTitle', { tags: tags.join(', ') }) : t('nodes.addTagsTitle')}
                              onClick={() => {
                                const current = tags.join(', ');
                                const input = window.prompt(`Tags for "${node.name}" (comma-separated):`, current);
                                if (input !== null) {
                                  const newTags = input.split(',').map(t => t.trim()).filter(Boolean);
                                  saveNodeTags(node.id, newTags);
                                }
                              }}
                            >
                              🏷
                            </button>
                            <button
                              className="btn btn-sm"
                              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                              onClick={() => handleEditClick(node)}
                              aria-label={t('common.edit')}
                            >
                              <UIIcon name="edit" size={14} />
                            </button>
                            <button
                              className="btn btn-sm"
                              style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: colors.dangerText }}
                              onClick={() => handleDelete(node.id)}
                              aria-label={t('common.delete')}
                            >
                              <UIIcon name="x" size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          </>
        ) : (
          <EmptyState
            icon="⬡"
            title={t('nodes.noNodesYet')}
            hint="Add your first 3x-ui panel node to start managing clients."
            action={{ label: '+ Add Node', onClick: () => setShowForm(true) }}
          />
        )}
      </section>
      )}

      {showEditModal && editingNode && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-dialog-centered">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>{t('nodes.renameNode')}</h6>
                <button type="button" className="btn-close" aria-label={t('common.close')} onClick={() => setShowEditModal(false)} />
              </div>
              <div className="modal-body">
                {error && <div className="alert alert-danger">{error}</div>}
                <p className="small mb-1" style={{ color: colors.text.secondary }}>
                  {t('nodes.currentName')}: <strong style={{ color: colors.text.primary }}>{editingNode.name}</strong>
                </p>
                <input
                  type="text"
                  className="form-control"
                  placeholder={t('nodes.newNodeName')}
                  value={editingName}
                  onChange={(e) => setEditingName(e.target.value)}
                  style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  autoFocus
                />
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button className="btn btn-sm" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }} onClick={() => setShowEditModal(false)}>
                  {t('common.cancel')}
                </button>
                <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }} onClick={handleSaveName} disabled={loading}>
                  {loading ? t('nodes.saving') : t('common.save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
