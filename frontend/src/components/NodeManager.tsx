import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
import { UIIcon } from './UIIcon';

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
  read_only?: boolean;
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
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [nodeStatuses, setNodeStatuses] = useState<Record<number, boolean | null>>({});
  const [statusLoading, setStatusLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [addMode, setAddMode] = useState<'form' | 'batch'>('form');
  const [formData, setFormData] = useState({ name: '', url: '', user: '', password: '', bearer_token: '' });
  const [batchText, setBatchText] = useState('');
  const [batchPreview, setBatchPreview] = useState<BatchPreviewRow[]>([]);
  const [batchAdded, setBatchAdded] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
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
          const auth = { username: getAuth().user, password: getAuth().password };
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

    // Validate that either bearer_token OR (user + password) is provided
    const hasToken = formData.bearer_token.trim();
    const hasCredentials = formData.user.trim() && formData.password.trim();

    if (!hasToken && !hasCredentials) {
      setError(t('nodes.fillConnectionFields'));
      setLoading(false);
      return;
    }

    try {
      // Build payload - only include filled fields
      const payload: any = {
        name: formData.name,
        url: formData.url,
      };
      
      if (hasToken) {
        payload.bearer_token = formData.bearer_token;
      } else {
        payload.user = formData.user;
        payload.password = formData.password;
      }

      await api.post('/v1/nodes', payload, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
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
      const results = await Promise.allSettled(
        batchPreview.map((row) =>
          api.post('/v1/nodes', row, {
            auth: { username: getAuth().user, password: getAuth().password }
          })
        )
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
    try {
      await api.delete(`/v1/nodes/${id}`, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      invalidateSharedSnapshot();
      loadNodes();
      onReload();
    } catch (err) {
      console.error('Failed to delete node:', err);
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
      await api.put(
        `/v1/nodes/${node.id}`,
        { read_only: nextReadOnly },
        {
          auth: { username: getAuth().user, password: getAuth().password },
        }
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
      await api.put(`/v1/nodes/${editingNode.id}`, { name: trimmed }, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
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
      const checkData: any = { url: formData.url };
      if (hasToken) {
        checkData.bearer_token = formData.bearer_token;
      } else {
        checkData.user = formData.user;
        checkData.password = formData.password;
      }
      
      const res = await api.post('/v1/nodes/check-connection', checkData, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
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

          {error && <div className="alert alert-danger mb-3" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{error}</div>}
          {success && <div className="alert alert-success mb-3" style={{ backgroundColor: colors.success + '22', borderColor: colors.success, color: colors.success }}>{success}</div>}

          {showForm && (
            <div className="panel-block__stack">
              <div>
                <label className="form-label small" style={{ color: colors.text.secondary }}>{t('nodes.addMode')}</label>
                <div className="panel-inline-actions">
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={addMode === 'form' ? { backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText } : { backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    onClick={() => handleModeSwitch('form')}
                  >
                    {t('nodes.singleForm')}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={addMode === 'batch' ? { backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText } : { backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
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

                  <div className="panel-block__stack">
                    <div>
                      <label className="form-label small" style={{ color: colors.text.secondary }}>
                        Bearer Token
                      </label>
                      <input
                        type="password"
                        name="bearer_token"
                        className="form-control"
                        placeholder="token or bearer:TOKEN"
                        value={formData.bearer_token}
                        onChange={(e) => setFormData({ ...formData, bearer_token: e.target.value })}
                        style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      />
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
                    Примеры: <span className="mono-inline">https://server:443/path admin password</span> • <span className="mono-inline">https://server:443/path bearer:TOKEN</span>
                  </p>
                  <textarea
                    className="form-control form-control-sm"
                    rows={6}
                    value={batchText}
                    onChange={(e) => { setBatchText(e.target.value); setBatchPreview([]); setBatchAdded(false); }}
                    placeholder={"https://server:443/path admin password\nhttps://server:443/path bearer:TOKEN\nhttps://server:443/path admin2 password"}
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
                          </tr>
                        </thead>
                        <tbody>
                          {batchPreview.map((row, idx) => (
                            <tr key={idx} style={{ borderColor: colors.border }}>
                              <td>{row.name}</td>
                              <td><small className="mono-inline">{row.url}</small></td>
                              <td>{row.user}</td>
                              <td>{row.password}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
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
        </div>

        {nodes.length > 0 ? (
          <div className="table-responsive table-shell">
            <table className="table table-sm align-middle mb-0" style={{ color: colors.text.primary }}>
              <thead>
                <tr>
                  <th>{t('common.name')}</th>
                  <th>{t('nodes.address')}</th>
                  <th>{t('common.status')}</th>
                  <th>{t('nodes.access')}</th>
                  <th style={{ width: '120px' }}>{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node) => {
                  const status = nodeStatuses[node.id];
                  const dotColor = status === true ? colors.success : status === false ? colors.danger : colors.text.secondary;
                  const statusLabel = status === true ? t('nodes.online') : status === false ? t('nodes.offline') : t('nodes.checking');
                  return (
                    <tr key={node.id}>
                      <td>
                        <span className="d-inline-flex align-items-center gap-2">
                          <span className="node-card__dot" style={{ backgroundColor: dotColor }} />
                          <strong>{node.name}</strong>
                        </span>
                      </td>
                      <td className="mono-inline">{node.ip}:{node.port}</td>
                      <td style={{ color: status === true ? colors.success : status === false ? colors.danger : colors.text.secondary }}>
                        {statusLabel}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm"
                          style={Boolean(node.read_only)
                            ? { backgroundColor: colors.warning + '22', borderColor: colors.warning, color: colors.warning }
                            : { backgroundColor: colors.success + '22', borderColor: colors.success, color: colors.success }}
                          onClick={() => handleToggleReadOnly(node)}
                          disabled={loading || Boolean(readOnlyUpdating[node.id])}
                          title={Boolean(node.read_only) ? t('nodes.switchWrite') : t('nodes.switchReadOnly')}
                        >
                          {readOnlyUpdating[node.id]
                            ? '...'
                            : Boolean(node.read_only)
                            ? 'RO'
                            : 'RW'}
                        </button>
                      </td>
                      <td>
                        <div className="panel-inline-actions">
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
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-center py-3 mb-0" style={{ color: colors.text.secondary }}>{t('nodes.noNodesYet')}</p>
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
                {error && <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{error}</div>}
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
