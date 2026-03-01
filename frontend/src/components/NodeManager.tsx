import React, { useState, useEffect } from 'react';
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

export const NodeManager: React.FC<{ onReload: () => void }> = ({ onReload }) => {
  const { colors } = useTheme();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [nodeStatuses, setNodeStatuses] = useState<Record<number, boolean | null>>({});
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

  const loadNodes = async () => {
    try {
      const res = await api.get('/v1/nodes', {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      setNodes(res.data);
      loadNodeStatuses(res.data);
    } catch (err) {
      console.error('Failed to load nodes:', err);
      setError('Failed to load nodes');
    }
  };

  const loadNodeStatuses = async (nodeList: Node[]) => {
    const initial: Record<number, boolean | null> = {};
    nodeList.forEach(n => { initial[n.id] = null; });
    setNodeStatuses(initial);
    const results = await Promise.all(nodeList.map(async n => {
      try {
        await api.get(`/v1/nodes/${n.id}/server-status`, {
          auth: { username: getAuth().user, password: getAuth().password }
        });
        return [n.id, true] as const;
      } catch {
        return [n.id, false] as const;
      }
    }));
    const final: Record<number, boolean> = {};
    results.forEach(([id, status]) => { final[id] = status; });
    setNodeStatuses(final);
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
      setSuccess('Сервер добавлен успешно');
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
    const lines = batchText.split('\n').map(l => l.trim()).filter(l => l);
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
        batchPreview.map(row =>
          api.post('/v1/nodes', row, {
            auth: { username: getAuth().user, password: getAuth().password }
          })
        )
      );
      const succeeded = results.filter(r => r.status === 'fulfilled').length;
      const failed = results.length - succeeded;
      setBatchText('');
      setBatchPreview([]);
      setBatchAdded(true);
      if (failed > 0) {
        setSuccess(`Добавлено ${succeeded} серверов`);
        setError(`${failed} серверов не удалось добавить`);
      } else {
        setSuccess(`Добавлено ${succeeded} серверов`);
      }
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add servers');
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

  return (
    <div className="node-manager">
      <div className="card p-3 mb-4" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h6 className="mb-0" style={{ color: colors.accent }}>Узлы node panel</h6>
          <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }} onClick={() => { setShowForm(!showForm); setSuccess(''); setError(''); }}>
            <span className="d-inline-flex align-items-center gap-1">
              <UIIcon name={showForm ? 'x' : 'plus'} size={14} />
              {showForm ? 'Отмена' : 'Добавить'}
            </span>
          </button>
        </div>

        {error && <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{error}</div>}
        {success && <div className="alert alert-success" style={{ backgroundColor: colors.success + '22', borderColor: colors.success, color: colors.success }}>{success}</div>}

        {showForm && (
          <div>
            {/* Mode toggle */}
            <div className="btn-group btn-group-sm mb-3">
              <button
                type="button"
                className="btn"
                style={addMode === 'form' ? { backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' } : { backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                onClick={() => handleModeSwitch('form')}
              >
                Форма
              </button>
              <button
                type="button"
                className="btn"
                style={addMode === 'batch' ? { backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' } : { backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                onClick={() => handleModeSwitch('batch')}
              >
                Batch текст
              </button>
            </div>

            {addMode === 'form' && (
              <form onSubmit={handleSubmit} className="row g-2 small">
                <div className="col-md-3">
                  <input
                    type="text"
                    name="name"
                    className="form-control"
                    placeholder="Метка (напр. NL)"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    required
                  />
                </div>
                <div className="col-md-4">
                  <input
                    type="text"
                    name="url"
                    className="form-control"
                    placeholder="https://ip:port/path/"
                    value={formData.url}
                    onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    required
                  />
                </div>
                <div className="col-md-2">
                  <input
                    type="text"
                    name="user"
                    className="form-control"
                    placeholder="Логин"
                    value={formData.user}
                    onChange={(e) => setFormData({ ...formData, user: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    required
                  />
                </div>
                <div className="col-md-2">
                  <input
                    type="password"
                    name="password"
                    className="form-control"
                    placeholder="Пароль"
                    value={formData.password}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    required
                  />
                </div>
                <div className="col-md-1">
                  <button type="submit" className="btn w-100" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }} disabled={loading}>
                    {loading ? '...' : 'OK'}
                  </button>
                </div>
              </form>
            )}

            {addMode === 'batch' && (
              <div>
                <p className="small mb-1" style={{ color: colors.text.secondary }}>
                  Формат: <code>https://server.com:443  admin  password</code> (по одному на строку)
                </p>
                <textarea
                  className="form-control form-control-sm mb-2"
                  rows={5}
                  value={batchText}
                  onChange={(e) => { setBatchText(e.target.value); setBatchPreview([]); setBatchAdded(false); }}
                  placeholder={'https://server1.com:443  admin  password123\nhttps://server2.com:443/path  admin2  password456'}
                  style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                />
                <button
                  type="button"
                  className="btn btn-sm me-2"
                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                  onClick={parseBatchText}
                  disabled={!batchText.trim()}
                >
                  Parse &amp; Preview
                </button>

                {batchPreview.length > 0 && (
                  <div className="mt-3">
                    <div className="table-responsive">
                      <table className="table table-sm" style={{ color: colors.text.primary }}>
                        <thead>
                          <tr style={{ borderColor: colors.border }}>
                            <th style={{ color: colors.text.secondary }}>Имя</th>
                            <th style={{ color: colors.text.secondary }}>URL</th>
                            <th style={{ color: colors.text.secondary }}>Логин</th>
                            <th style={{ color: colors.text.secondary }}>Пароль</th>
                          </tr>
                        </thead>
                        <tbody>
                          {batchPreview.map((row, idx) => (
                            <tr key={idx} style={{ borderColor: colors.border }}>
                              <td>{row.name}</td>
                              <td><small>{row.url}</small></td>
                              <td>{row.user}</td>
                              <td>{row.password}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.success, borderColor: colors.success, color: '#ffffff' }}
                      onClick={handleBatchAddAll}
                      disabled={loading || batchAdded}
                    >
                      {loading ? '...' : `Add All (${batchPreview.length})`}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <h6 className="mb-3" style={{ color: colors.text.secondary }}>Список узлов</h6>
        {nodes.map((n) => {
          const status = nodeStatuses[n.id];
          const dotColor = status === true ? '#22c55e' : status === false ? '#ef4444' : colors.text.secondary;
          return (
            <div key={n.id} className="node-list-item d-flex align-items-center gap-2 mb-2 p-2">
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', flexShrink: 0, backgroundColor: dotColor, display: 'inline-block' }} />
              <strong style={{ color: colors.text.primary, flexShrink: 0 }}>{n.name}</strong>
              <span style={{ color: colors.text.secondary }}>|</span>
              <span style={{ color: colors.text.secondary, flexShrink: 0 }}>{n.ip}:{n.port}</span>
              <div className="ms-auto d-flex gap-1 flex-shrink-0">
                <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }} onClick={() => handleEditClick(n)} aria-label="Edit node">
                  <UIIcon name="edit" size={14} />
                </button>
                <button className="btn btn-sm" style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: '#ffffff' }} onClick={() => handleDelete(n.id)} aria-label="Delete node">
                  <UIIcon name="x" size={14} />
                </button>
              </div>
            </div>
          );
        })}
        {nodes.length === 0 && <p className="text-center py-3" style={{ color: colors.text.secondary }}>Нет добавленных узлов</p>}
      </div>

      {showEditModal && editingNode && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-dialog-centered">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>Переименовать сервер</h6>
                <button type="button" className="btn-close" aria-label="Close" onClick={() => setShowEditModal(false)} />
              </div>
              <div className="modal-body">
                {error && <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{error}</div>}
                <p className="small mb-1" style={{ color: colors.text.secondary }}>Текущее имя: <strong style={{ color: colors.text.primary }}>{editingNode.name}</strong></p>
                <input
                  type="text"
                  className="form-control"
                  placeholder="Новое имя"
                  value={editingName}
                  onChange={(e) => setEditingName(e.target.value)}
                  style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  autoFocus
                />
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button className="btn btn-sm" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }} onClick={() => setShowEditModal(false)}>
                  Отмена
                </button>
                <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }} onClick={handleSaveName} disabled={loading}>
                  {loading ? '...' : 'Сохранить'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
