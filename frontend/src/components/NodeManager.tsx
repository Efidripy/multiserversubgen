import React, { useEffect, useRef, useState } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
import { UIIcon } from './UIIcon';

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
}

interface BatchPreviewRow {
  name: string;
  url: string;
  user: string;
  password: string;
}

const NODE_STATUS_CACHE_KEY = 'sub_manager_node_status_cache_v1';
const NODE_LIST_CACHE_KEY = 'sub_manager_node_list_cache_v1';

export const NodeManager: React.FC<{ onReload: () => void; showIntake?: boolean; showFleet?: boolean }> = ({
  onReload,
  showIntake = true,
  showFleet = true,
}) => {
  const { colors } = useTheme();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [nodeStatuses, setNodeStatuses] = useState<Record<number, boolean | null>>({});
  const [statusLoading, setStatusLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [addMode, setAddMode] = useState<'form' | 'batch'>('form');
  const [formData, setFormData] = useState({ name: '', url: '', user: '', password: '' });
  const [batchText, setBatchText] = useState('');
  const [batchPreview, setBatchPreview] = useState<BatchPreviewRow[]>([]);
  const [batchAdded, setBatchAdded] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [editingNode, setEditingNode] = useState<Node | null>(null);
  const [editingName, setEditingName] = useState('');
  const [showEditModal, setShowEditModal] = useState(false);
  const [checkingConnection, setCheckingConnection] = useState(false);
  const statusRequestIdRef = useRef(0);

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
      const auth = { username: getAuth().user, password: getAuth().password };
      const nodesRes = await api.get('/v1/nodes', { auth });
      const nodeList = Array.isArray(nodesRes.data) ? nodesRes.data : [];
      setNodes(nodeList);
      try {
        localStorage.setItem(NODE_LIST_CACHE_KEY, JSON.stringify(nodeList));
      } catch {}
      let cachedStatuses: Record<number, boolean | null> = {};
      try {
        const raw = localStorage.getItem(NODE_STATUS_CACHE_KEY);
        cachedStatuses = raw ? JSON.parse(raw) : {};
      } catch {
        cachedStatuses = {};
      }
      const initial: Record<number, boolean | null> = {};
      nodeList.forEach((node) => { initial[node.id] = node.id in cachedStatuses ? cachedStatuses[node.id] : null; });
      setNodeStatuses(initial);
      setStatusLoading(true);
      const requestId = Date.now();
      statusRequestIdRef.current = requestId;
      loadNodeStatuses(nodeList, requestId);
    } catch (err) {
      console.error('Failed to load nodes:', err);
      setError('Failed to load nodes');
    }
  };

  const loadNodeStatuses = async (nodeList: Node[], requestId: number) => {
    if (nodeList.length === 0) {
      setStatusLoading(false);
      return;
    }

    let pending = nodeList.length;
    nodeList.forEach((node) => {
      api.get(`/v1/nodes/${node.id}/server-status`, {
        auth: { username: getAuth().user, password: getAuth().password }
      })
        .then((response) => {
          if (statusRequestIdRef.current !== requestId) return;
          const available = Boolean(response.data?.available);
          setNodeStatuses((prev) => {
            const next = { ...prev, [node.id]: available };
            try {
              localStorage.setItem(NODE_STATUS_CACHE_KEY, JSON.stringify(next));
            } catch {}
            return next;
          });
        })
        .catch(() => {
          if (statusRequestIdRef.current !== requestId) return;
          setNodeStatuses((prev) => {
            const next = { ...prev, [node.id]: false };
            try {
              localStorage.setItem(NODE_STATUS_CACHE_KEY, JSON.stringify(next));
            } catch {}
            return next;
          });
        })
        .finally(() => {
          if (statusRequestIdRef.current !== requestId) return;
          pending -= 1;
          if (pending <= 0) {
            setStatusLoading(false);
          }
        });
    });
  };

  useEffect(() => {
    loadNodes();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');

    try {
      await api.post('/v1/nodes', formData, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      setFormData({ name: '', url: '', user: '', password: '' });
      setSuccess('Server added successfully');
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add node');
    } finally {
      setLoading(false);
    }
  };

  const parseBatchText = () => {
    setError('');
    const lines = batchText.split('\n').map((line) => line.trim()).filter(Boolean);
    const rows: BatchPreviewRow[] = lines.map((line, idx) => {
      const parts = line.split(/\s+/);
      return {
        name: `Server-${idx + 1}`,
        url: parts[0] || '',
        user: parts[1] || '',
        password: parts[2] || '',
      };
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
        setSuccess(`Added ${succeeded} nodes`);
        setError(`${failed} nodes failed to add`);
      } else {
        setSuccess(`Added ${succeeded} nodes`);
      }
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add nodes');
    } finally {
      setLoading(false);
    }
  };

  const handleModeSwitch = (mode: 'form' | 'batch') => {
    setAddMode(mode);
    setFormData({ name: '', url: '', user: '', password: '' });
    setBatchText('');
    setBatchPreview([]);
    setBatchAdded(false);
    setError('');
    setSuccess('');
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Are you sure you want to delete this node?')) return;
    setLoading(true);
    try {
      await api.delete(`/v1/nodes/${id}`, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      loadNodes();
      onReload();
    } catch (err) {
      console.error('Failed to delete node:', err);
    } finally {
      setLoading(false);
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
      setError('Name cannot be empty');
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
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update node');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckConnection = async () => {
    setError('');
    setSuccess('');
    if (!formData.url.trim() || !formData.user.trim() || !formData.password.trim()) {
      setError('Fill URL, login and password first');
      return;
    }

    setCheckingConnection(true);
    try {
      const res = await api.post('/v1/nodes/check-connection', {
        url: formData.url,
        user: formData.user,
        password: formData.password,
      }, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      const payload = res.data || {};
      if (payload.success) {
        const count = Number.isFinite(payload.inbounds_count) ? payload.inbounds_count : null;
        setSuccess(count !== null ? `Connection OK, inbounds: ${count}` : 'Connection OK');
      } else {
        setError(payload.message || 'Connection failed');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Connection check failed');
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
              <h6 className="panel-block__title">Node intake</h6>
              <p className="panel-block__hint">Register a single panel or batch-import multiple endpoints.</p>
            </div>
            <button
              className="btn btn-sm"
              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
              onClick={() => { setShowForm(!showForm); setSuccess(''); setError(''); }}
            >
              <span className="d-inline-flex align-items-center gap-1">
                <UIIcon name={showForm ? 'x' : 'plus'} size={14} />
                {showForm ? 'Close' : 'Add node'}
              </span>
            </button>
          </div>

          {error && <div className="alert alert-danger mb-3" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{error}</div>}
          {success && <div className="alert alert-success mb-3" style={{ backgroundColor: colors.success + '22', borderColor: colors.success, color: colors.success }}>{success}</div>}

          {showForm && (
            <div className="panel-block__stack">
              <div>
                <label className="form-label small" style={{ color: colors.text.secondary }}>Add mode</label>
                <div className="panel-inline-actions">
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={addMode === 'form' ? { backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText } : { backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    onClick={() => handleModeSwitch('form')}
                  >
                    Single form
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={addMode === 'batch' ? { backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText } : { backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    onClick={() => handleModeSwitch('batch')}
                  >
                    Batch text
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
                      placeholder="Node label"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                    <input
                      type="text"
                      name="url"
                      className="form-control"
                      placeholder="https://host/path/"
                      value={formData.url}
                      onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                    <input
                      type="text"
                      name="user"
                      className="form-control"
                      placeholder="Login"
                      value={formData.user}
                      onChange={(e) => setFormData({ ...formData, user: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                    <input
                      type="password"
                      name="password"
                      className="form-control"
                      placeholder="Password"
                      value={formData.password}
                      onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                  </div>
                  <div className="panel-inline-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.warning + '33', borderColor: colors.warning + '66', color: colors.warning }}
                      onClick={handleCheckConnection}
                      disabled={loading || checkingConnection}
                    >
                      {checkingConnection ? 'Checking...' : 'Check connection'}
                    </button>
                    <button
                      type="submit"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                      disabled={loading || checkingConnection}
                    >
                      {loading ? 'Saving...' : 'Save node'}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="panel-block__stack">
                  <p className="small mb-0" style={{ color: colors.text.secondary }}>
                    Format: <span className="mono-inline">https://server:443/path admin password</span>
                  </p>
                  <textarea
                    className="form-control form-control-sm"
                    rows={6}
                    value={batchText}
                    onChange={(e) => { setBatchText(e.target.value); setBatchPreview([]); setBatchAdded(false); }}
                    placeholder={'https://server1.com:443 admin password123\nhttps://server2.com/path admin2 password456'}
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
                      Parse and preview
                    </button>
                    {batchPreview.length > 0 && (
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ backgroundColor: colors.success, borderColor: colors.success, color: colors.successText }}
                        onClick={handleBatchAddAll}
                        disabled={loading || batchAdded}
                      >
                        {loading ? 'Adding...' : `Add all (${batchPreview.length})`}
                      </button>
                    )}
                  </div>

                  {batchPreview.length > 0 && (
                    <div className="table-responsive table-shell">
                      <table className="table table-sm align-middle mb-0" style={{ color: colors.text.primary }}>
                        <thead>
                          <tr style={{ borderColor: colors.border }}>
                            <th>Name</th>
                            <th>URL</th>
                            <th>Login</th>
                            <th>Password</th>
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
            <h6 className="panel-block__title">Registered fleet</h6>
            <p className="panel-block__hint">
              Edit node names or remove outdated panel entries.
              {statusLoading ? ' Statuses are still syncing.' : ''}
            </p>
          </div>
        </div>

        {nodes.length > 0 ? (
          <div className="table-responsive table-shell">
            <table className="table table-sm align-middle mb-0" style={{ color: colors.text.primary }}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Address</th>
                  <th>Status</th>
                  <th style={{ width: '120px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node) => {
                  const status = nodeStatuses[node.id];
                  const dotColor = status === true ? colors.success : status === false ? colors.danger : colors.text.secondary;
                  const statusLabel = status === true ? 'online' : status === false ? 'offline' : 'checking';
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
                        <div className="panel-inline-actions">
                          <button
                            className="btn btn-sm"
                            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                            onClick={() => handleEditClick(node)}
                            aria-label="Edit node"
                          >
                            <UIIcon name="edit" size={14} />
                          </button>
                          <button
                            className="btn btn-sm"
                            style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: colors.dangerText }}
                            onClick={() => handleDelete(node.id)}
                            aria-label="Delete node"
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
          <p className="text-center py-3 mb-0" style={{ color: colors.text.secondary }}>No nodes registered yet.</p>
        )}
      </section>
      )}

      {showEditModal && editingNode && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-dialog-centered">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>Rename node</h6>
                <button type="button" className="btn-close" aria-label="Close" onClick={() => setShowEditModal(false)} />
              </div>
              <div className="modal-body">
                {error && <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{error}</div>}
                <p className="small mb-1" style={{ color: colors.text.secondary }}>
                  Current name: <strong style={{ color: colors.text.primary }}>{editingNode.name}</strong>
                </p>
                <input
                  type="text"
                  className="form-control"
                  placeholder="New node name"
                  value={editingName}
                  onChange={(e) => setEditingName(e.target.value)}
                  style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  autoFocus
                />
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button className="btn btn-sm" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }} onClick={() => setShowEditModal(false)}>
                  Cancel
                </button>
                <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }} onClick={handleSaveName} disabled={loading}>
                  {loading ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
