import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useTheme } from '../contexts/ThemeContext';

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
}

export const NodeManager: React.FC<{ onReload: () => void }> = ({ onReload }) => {
  const { colors } = useTheme();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({ name: '', url: '', user: '', password: '' });
  const [error, setError] = useState('');

  const loadNodes = async () => {
    try {
      const res = await axios.get('/api/v1/nodes', {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      setNodes(res.data);
    } catch (err) {
      console.error('Failed to load nodes:', err);
      setError('Failed to load nodes');
    }
  };

  useEffect(() => {
    loadNodes();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    
    try {
      await axios.post('/api/v1/nodes', formData, {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      setShowForm(false);
      setFormData({ name: '', url: '', user: '', password: '' });
      loadNodes();
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add node');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Are you sure you want to delete this node?')) return;
    
    setLoading(true);
    try {
      await axios.delete(`/api/v1/nodes/${id}`, {
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

  return (
    <div className="node-manager">
      <div className="card p-3 mb-4" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h6 className="mb-0" style={{ color: colors.accent }}>Узлы 3X-UI</h6>
          <button className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }} onClick={() => setShowForm(!showForm)}>
            {showForm ? '× Отмена' : '+ Добавить'}
          </button>
        </div>

        {error && <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{error}</div>}

        {showForm && (
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
      </div>

      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <h6 className="mb-3" style={{ color: colors.text.secondary }}>Список узлов</h6>
        {nodes.map((n) => (
          <div key={n.id} className="d-flex justify-content-between align-items-center mb-2 p-2 border-bottom" style={{ borderColor: colors.border }}>
            <div>
              <strong style={{ color: colors.text.primary }}>{n.name}</strong>
              <br />
              <small style={{ color: colors.text.secondary }}>{n.ip}:{n.port}</small>
            </div>
            <button className="btn btn-sm" style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: '#ffffff' }} onClick={() => handleDelete(n.id)}>
              ×
            </button>
          </div>
        ))}
        {nodes.length === 0 && <p className="text-center py-3" style={{ color: colors.text.secondary }}>Нет добавленных узлов</p>}
      </div>
    </div>
  );
};

function getAuth() {
  if (typeof window !== 'undefined') {
    const auth = localStorage.getItem('sub_auth');
    if (auth) {
      return JSON.parse(auth);
    }
  }
  return { user: '', password: '' };
}