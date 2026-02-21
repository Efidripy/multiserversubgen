import React, { useState, useEffect } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';

interface Inbound {
  id: number;
  node_name: string;
  node_ip: string;
  protocol: string;
  port: number;
  remark: string;
  enable: boolean;
  security: string;
  is_reality: boolean;
}

interface InboundManagerProps {
  onReload?: () => void;
}

export const InboundManager: React.FC<InboundManagerProps> = ({ onReload }) => {
  const { colors } = useTheme();
  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [filteredInbounds, setFilteredInbounds] = useState<Inbound[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  // Фильтры
  const [filterProtocol, setFilterProtocol] = useState('');
  const [filterSecurity, setFilterSecurity] = useState('');
  const [filterNode, setFilterNode] = useState('');
  
  // Clone modal state
  const [showCloneModal, setShowCloneModal] = useState(false);
  const [cloneSource, setCloneSource] = useState<Inbound | null>(null);
  const [cloneRemark, setCloneRemark] = useState('');
  const [clonePort, setClonePort] = useState('');
  
  useEffect(() => {
    loadInbounds();
  }, []);
  
  useEffect(() => {
    // Применить фильтры
    let filtered = inbounds;
    
    if (filterProtocol) {
      filtered = filtered.filter(ib => ib.protocol === filterProtocol);
    }
    
    if (filterSecurity) {
      filtered = filtered.filter(ib => ib.security === filterSecurity);
    }
    
    if (filterNode) {
      filtered = filtered.filter(ib => ib.node_name.toLowerCase().includes(filterNode.toLowerCase()));
    }
    
    setFilteredInbounds(filtered);
  }, [inbounds, filterProtocol, filterSecurity, filterNode]);
  
  const loadInbounds = async () => {
    setLoading(true);
    setError('');
    
    try {
      const res = await api.get('/v1/inbounds', {
        auth: getAuth()
      });
      
      setInbounds(res.data.inbounds || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load inbounds');
    } finally {
      setLoading(false);
    }
  };
  
  const handleDelete = async (inbound: Inbound) => {
    if (!window.confirm(`Delete inbound "${inbound.remark}" from ${inbound.node_name}?`)) return;
    
    setLoading(true);
    try {
      // Найти node_id по имени узла (требуется расширить API для получения node_id)
      await api.delete(`/v1/inbounds/${inbound.id}`, {
        params: { node_id: 1 }, // Временно, нужен правильный node_id
        auth: getAuth()
      });
      
      loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete inbound');
    } finally {
      setLoading(false);
    }
  };
  
  const handleCloneClick = (inbound: Inbound) => {
    setCloneSource(inbound);
    setCloneRemark(`${inbound.remark} (Clone)`);
    setClonePort(String(inbound.port));
    setShowCloneModal(true);
  };
  
  const handleCloneSubmit = async () => {
    if (!cloneSource) return;
    
    setLoading(true);
    setError('');
    
    try {
      const payload = {
        source_node_id: 1, // Временно, нужен правильный source_node_id
        source_inbound_id: cloneSource.id,
        target_node_ids: null, // Клонировать на все остальные узлы
        modifications: {
          remark: cloneRemark,
          port: parseInt(clonePort)
        }
      };
      
      await api.post('/v1/inbounds/clone', payload, {
        auth: getAuth()
      });
      
      setShowCloneModal(false);
      loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to clone inbound');
    } finally {
      setLoading(false);
    }
  };
  
  // Получить уникальные значения для фильтров
  const protocols = Array.from(new Set(inbounds.map(ib => ib.protocol)));
  const securities = Array.from(new Set(inbounds.map(ib => ib.security)));
  const nodes = Array.from(new Set(inbounds.map(ib => ib.node_name)));
  
  return (
    <div className="inbound-manager">
      <div className="card p-3 mb-4" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0" style={{ color: colors.accent }}>🔌 Inbound Management</h5>
          <button 
            className="btn btn-sm" 
            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
            onClick={loadInbounds}
            disabled={loading}
          >
            🔄 Reload
          </button>
        </div>
        
        {error && (
          <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
            {error}
          </div>
        )}
        
        {/* Фильтры */}
        <div className="row g-2 mb-3">
          <div className="col-md-3">
            <select 
              className="form-select form-select-sm" 
              value={filterProtocol}
              onChange={(e) => setFilterProtocol(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">All Protocols</option>
              {protocols.map(p => (
                <option key={p} value={p}>{p.toUpperCase()}</option>
              ))}
            </select>
          </div>
          <div className="col-md-3">
            <select 
              className="form-select form-select-sm" 
              value={filterSecurity}
              onChange={(e) => setFilterSecurity(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">All Security</option>
              {securities.map(s => (
                <option key={s} value={s}>{s || 'none'}</option>
              ))}
            </select>
          </div>
          <div className="col-md-3">
            <select 
              className="form-select form-select-sm" 
              value={filterNode}
              onChange={(e) => setFilterNode(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">All Nodes</option>
              {nodes.map(n => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
          <div className="col-md-3">
            <button 
              className="btn btn-sm w-100" 
              style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
              onClick={() => {
                setFilterProtocol('');
                setFilterSecurity('');
                setFilterNode('');
              }}
            >
              Clear Filters
            </button>
          </div>
        </div>
        
        {/* Список инбаундов */}
        {loading && <div className="text-center py-3"><div className="spinner-border spinner-border-sm" role="status"></div></div>}
        
        {!loading && filteredInbounds.length === 0 && (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>No inbounds found</p>
        )}
        
        <div className="table-responsive">
          <table className="table table-sm table-hover" style={{ color: colors.text.primary }}>
            <thead>
              <tr style={{ borderColor: colors.border }}>
                <th style={{ color: colors.text.secondary }}>Node</th>
                <th style={{ color: colors.text.secondary }}>Remark</th>
                <th style={{ color: colors.text.secondary }}>Protocol</th>
                <th style={{ color: colors.text.secondary }}>Port</th>
                <th style={{ color: colors.text.secondary }}>Security</th>
                <th style={{ color: colors.text.secondary }}>Status</th>
                <th style={{ color: colors.text.secondary }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredInbounds.map((ib) => (
                <tr key={`${ib.node_name}-${ib.id}`} style={{ borderColor: colors.border }}>
                  <td>
                    <span className="badge" style={{ backgroundColor: colors.bg.tertiary, color: colors.text.primary }}>{ib.node_name}</span>
                  </td>
                  <td>{ib.remark || <span style={{ color: colors.text.secondary }}>—</span>}</td>
                  <td>
                    <span className="badge" style={{ backgroundColor: colors.accent }}>
                      {ib.protocol.toUpperCase()}
                    </span>
                  </td>
                  <td className="text-monospace">{ib.port}</td>
                  <td>
                    {ib.is_reality && <span className="badge" style={{ backgroundColor: colors.success }}>Reality</span>}
                    {!ib.is_reality && ib.security && <span className="badge" style={{ backgroundColor: colors.info }}>{ib.security}</span>}
                    {!ib.security && <span style={{ color: colors.text.secondary }}>—</span>}
                  </td>
                  <td>
                    {ib.enable ? (
                      <span style={{ color: colors.success }}>● Active</span>
                    ) : (
                      <span style={{ color: colors.text.secondary }}>○ Disabled</span>
                    )}
                  </td>
                  <td>
                    <button 
                      className="btn btn-sm me-1" 
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                      onClick={() => handleCloneClick(ib)}
                      title="Clone to other nodes"
                    >
                      📋 Clone
                    </button>
                    <button 
                      className="btn btn-sm" 
                      style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: '#ffffff' }}
                      onClick={() => handleDelete(ib)}
                      title="Delete inbound"
                    >
                      🗑
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        
        <div className="mt-2 small" style={{ color: colors.text.secondary }}>
          Showing {filteredInbounds.length} of {inbounds.length} inbounds
        </div>
      </div>
      
      {/* Clone Modal */}
      {showCloneModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
          <div className="modal-dialog">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>Clone Inbound: {cloneSource?.remark}</h6>
                <button 
                  type="button" 
                  className="btn-close btn-close-white" 
                  onClick={() => setShowCloneModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <div className="mb-3">
                  <label className="form-label small" style={{ color: colors.text.secondary }}>New Remark</label>
                  <input 
                    type="text" 
                    className="form-control" 
                    value={cloneRemark}
                    onChange={(e) => setCloneRemark(e.target.value)}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                </div>
                <div className="mb-3">
                  <label className="form-label small" style={{ color: colors.text.secondary }}>New Port (optional)</label>
                  <input 
                    type="number" 
                    className="form-control" 
                    value={clonePort}
                    onChange={(e) => setClonePort(e.target.value)}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                </div>
                <p className="small" style={{ color: colors.text.secondary }}>
                  This will clone the inbound configuration to all other nodes.
                </p>
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button 
                  className="btn" 
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                  onClick={() => setShowCloneModal(false)}
                  disabled={loading}
                >
                  Cancel
                </button>
                <button 
                  className="btn" 
                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                  onClick={handleCloneSubmit}
                  disabled={loading}
                >
                  {loading ? 'Cloning...' : 'Clone Inbound'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

function getAuth() {
  if (typeof window !== 'undefined') {
    const auth = localStorage.getItem('sub_auth');
    if (auth) {
      const parsed = JSON.parse(auth);
      return { username: parsed.user, password: parsed.password };
    }
  }
  return { username: '', password: '' };
}
