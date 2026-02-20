import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useTheme } from '../contexts/ThemeContext';

interface Stats {
  count: number;
  last: string;
}

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
}

interface SubscriptionGroup {
  identifier: string;
  emails: string[];
  count: number;
}


export const SubscriptionManager: React.FC<{ apiUrl: string }> = ({ apiUrl }) => {
  const { colors } = useTheme();
  const [emails, setEmails] = useState<string[]>([]);
  const [stats, setStats] = useState<Record<string, Stats>>({});
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'individual' | 'grouped'>('individual');
  const [groups, setGroups] = useState<SubscriptionGroup[]>([]);
  const [filterProtocol, setFilterProtocol] = useState('');
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);

  const loadEmails = async () => {
    setLoading(true);
    try {
      const res = await axios.get('/api/v1/emails', {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      setEmails(res.data.emails || []);
      setStats(res.data.stats || {});
    } catch (err) {
      console.error('Failed to load subscriptions:', err);
    } finally {
      setLoading(false);
    }
  };
  
  const loadNodes = async () => {
    try {
      const res = await axios.get('/api/v1/nodes', {
        auth: { username: getAuth().user, password: getAuth().password }
      });
      setNodes(res.data || []);
    } catch (err) {
      console.error('Failed to load nodes:', err);
    }
  };
  
  const analyzeGroups = () => {
    // Анализ email для группировки
    const groupMap = new Map<string, string[]>();
    
    emails.forEach(email => {
      // Группировка по домену
      const domain = email.split('@')[1] || 'unknown';
      if (!groupMap.has(domain)) {
        groupMap.set(domain, []);
      }
      groupMap.get(domain)!.push(email);
      
      // Группировка по префиксам (первые 3-5 символов до цифр)
      const match = email.match(/^([a-zA-Z]{3,})/); 
      if (match) {
        const prefix = match[1].toLowerCase();
        if (!groupMap.has(prefix)) {
          groupMap.set(prefix, []);
        }
        groupMap.get(prefix)!.push(email);
      }
    });
    
    // Создать список групп с 2+ email
    const groupList: SubscriptionGroup[] = [];
    groupMap.forEach((emailList, identifier) => {
      if (emailList.length >= 2) {
        groupList.push({
          identifier,
          emails: emailList,
          count: emailList.length
        });
      }
    });
    
    // Сортировка по количеству
    groupList.sort((a, b) => b.count - a.count);
    setGroups(groupList);
  };

  useEffect(() => {
    loadEmails();
    loadNodes();
  }, []);
  
  useEffect(() => {
    if (viewMode === 'grouped') {
      analyzeGroups();
    }
  }, [emails, viewMode]);

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      alert('Copied!');
    } catch (err) {
      const el = document.createElement('textarea');
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
  };
  
  const buildSubscriptionUrl = (email: string, isGrouped: boolean = false) => {
    const baseUrl = isGrouped 
      ? `${apiUrl}/api/v1/sub-grouped/${email}`
      : `${apiUrl}/api/v1/sub/${email}`;
    
    const params = new URLSearchParams();
    if (filterProtocol) params.append('protocol', filterProtocol);
    if (selectedNodes.length > 0) params.append('nodes', selectedNodes.join(','));
    
    return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
  };

  if (loading && emails.length === 0) {
    return <div className="text-center py-5" style={{ color: colors.text.secondary }}>Loading...</div>;
  }
  
  const toggleNodeSelection = (nodeName: string) => {
    setSelectedNodes(prev => 
      prev.includes(nodeName) 
        ? prev.filter(n => n !== nodeName)
        : [...prev, nodeName]
    );
  };

  return (
    <div className="subscription-manager">
      {/* Фильтры и настройки */}
      <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0" style={{ color: colors.accent }}>🔗 Subscriptions</h5>
          <div className="btn-group" role="group">
            <button
              className="btn btn-sm"
              style={{
                backgroundColor: viewMode === 'individual' ? colors.accent : colors.bg.tertiary,
                borderColor: colors.border,
                color: viewMode === 'individual' ? '#ffffff' : colors.text.primary
              }}
              onClick={() => setViewMode('individual')}
            >
              👤 Individual
            </button>
            <button
              className="btn btn-sm"
              style={{
                backgroundColor: viewMode === 'grouped' ? colors.accent : colors.bg.tertiary,
                borderColor: colors.border,
                color: viewMode === 'grouped' ? '#ffffff' : colors.text.primary
              }}
              onClick={() => setViewMode('grouped')}
            >
              📁 Grouped
            </button>
          </div>
        </div>
        
        {/* Фильтры */}
        <div className="row g-2 mb-2">
          <div className="col-md-3">
            <label className="form-label small" style={{ color: colors.text.secondary }}>Protocol Filter</label>
            <select
              className="form-select form-select-sm"
              value={filterProtocol}
              onChange={(e) => setFilterProtocol(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">All Protocols</option>
              <option value="vless">VLESS</option>
              <option value="vmess">VMess</option>
              <option value="trojan">Trojan</option>
            </select>
          </div>
          <div className="col-md-9">
            <label className="form-label small" style={{ color: colors.text.secondary }}>Node Filter (select nodes)</label>
            <div className="d-flex flex-wrap gap-2">
              {nodes.map(node => (
                <button
                  key={node.id}
                  className="btn btn-sm"
                  style={{
                    backgroundColor: selectedNodes.includes(node.name) ? colors.accent : colors.bg.tertiary,
                    borderColor: colors.border,
                    color: selectedNodes.includes(node.name) ? '#ffffff' : colors.text.primary
                  }}
                  onClick={() => toggleNodeSelection(node.name)}
                >
                  {selectedNodes.includes(node.name) ? '✓ ' : ''}{node.name}
                </button>
              ))}
              {selectedNodes.length > 0 && (
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: '#000' }}
                  onClick={() => setSelectedNodes([])}
                >
                  ✕ Clear
                </button>
              )}
            </div>
          </div>
        </div>
        
        {(filterProtocol || selectedNodes.length > 0) && (
          <div className="alert mt-2 mb-0" style={{ backgroundColor: colors.info + '22', borderColor: colors.info, color: colors.text.primary }}>
            <small>
              <strong>ℹ️ Active filters:</strong>
              {filterProtocol && ` Protocol: ${filterProtocol.toUpperCase()}`}
              {selectedNodes.length > 0 && ` | Nodes: ${selectedNodes.join(', ')}`}
            </small>
          </div>
        )}
      </div>
      
      {/* Подписки */}
      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <h6 className="mb-3" style={{ color: colors.text.primary }}>
          {viewMode === 'individual' ? `👥 Individual Subscriptions (${emails.length})` : `📁 Grouped Subscriptions (${groups.length} groups)`}
        </h6>
        {emails.length === 0 ? (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>Нет пользователей. Добавьте узлы node panel.</p>
        ) : viewMode === 'individual' ? (
          <table className="table table-hover small" style={{ color: colors.text.primary }}>
            <thead>
              <tr style={{ borderColor: colors.border }}>
                <th style={{ color: colors.text.secondary }}>Email</th>
                <th style={{ color: colors.text.secondary }}>Скачиваний</th>
                <th style={{ color: colors.text.secondary }}>Последний раз</th>
                <th style={{ color: colors.text.secondary }}>Ссылка</th>
              </tr>
            </thead>
            <tbody>
              {emails.map((email) => (
                <tr key={email} style={{ borderColor: colors.border }}>
                  <td className="align-middle">
                    <strong style={{ color: colors.text.primary }}>{email}</strong>
                  </td>
                  <td className="align-middle">
                    <span className="badge" style={{ backgroundColor: colors.info }}>
                      {stats[email]?.count || 0}
                    </span>
                  </td>
                  <td className="align-middle">
                    <small style={{ color: colors.text.secondary }}>{stats[email]?.last || '--'}</small>
                  </td>
                  <td className="align-middle">
                    <div className="input-group input-group-sm">
                      <input
                        type="text"
                        id={`sub-${email}`}
                        className="form-control form-control-sm"
                        readOnly
                        value={buildSubscriptionUrl(email)}
                        style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      />
                      <button
                        className="btn"
                        style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                        onClick={() => copyToClipboard(buildSubscriptionUrl(email))}
                      >
                        Copy
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          // Групповой режим
          <div className="row g-3">
            {groups.map((group, idx) => (
              <div className="col-md-6" key={idx}>
                <div className="card p-3" style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border }}>
                  <div className="d-flex justify-content-between align-items-center mb-2">
                    <div>
                      <h6 className="mb-0" style={{ color: colors.accent }}>
                        📁 {group.identifier}
                      </h6>
                      <small style={{ color: colors.text.secondary }}>
                        {group.count} clients
                      </small>
                    </div>
                    <span className="badge" style={{ backgroundColor: colors.accent }}>
                      {group.count}
                    </span>
                  </div>
                  
                  <div className="mb-2" style={{ maxHeight: '100px', overflowY: 'auto' }}>
                    {group.emails.map((email, i) => (
                      <div key={i} className="small" style={{ color: colors.text.secondary }}>
                        • {email}
                      </div>
                    ))}
                  </div>
                  
                  <div className="input-group input-group-sm">
                    <input
                      type="text"
                      className="form-control form-control-sm"
                      readOnly
                      value={buildSubscriptionUrl(group.identifier, true)}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                    <button
                      className="btn"
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                      onClick={() => copyToClipboard(buildSubscriptionUrl(group.identifier, true))}
                    >
                      Copy
                    </button>
                  </div>
                </div>
              </div>
            ))}
            {groups.length === 0 && (
              <div className="col-12">
                <p className="text-center py-3" style={{ color: colors.text.secondary }}>
                  No groups found. Groups require at least 2 clients with similar identifiers.
                </p>
              </div>
            )}
          </div>
        )}
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