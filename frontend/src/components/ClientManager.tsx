import React, { useState, useEffect, useRef } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { AddClientMultiServer } from './AddClientMultiServer';
import { getAuth } from '../auth';

interface Client {
  id: number;
  email: string;
  enable: boolean;
  total: number;
  up: number;
  down: number;
  expiryTime: number;
  inbound_id: number;
  node_name: string;
  node_id?: number;
  protocol: string;
}

interface TrafficData {
  upload: number;
  download: number;
  total: number;
  enable: boolean;
  expiryTime: number;
}

interface BatchAddClient {
  email: string;
  total_gb?: number;
  expiry_days?: number;
  enable: boolean;
}

interface ClientsPageCache {
  ts: number;
  clients: Client[];
  trafficCache: Record<string, TrafficData | null>;
  endpointMode?: 'unknown' | 'query' | 'legacy' | 'disabled';
}

const CLIENTS_PAGE_CACHE_KEY = 'sub_manager_clients_page_cache_v1';
const CLIENTS_PAGE_CACHE_MAX_AGE_MS = 10 * 60 * 1000; // 10 minutes
const CLIENTS_PAGE_REFRESH_MS = 5 * 60 * 1000; // background refresh interval
const TRAFFIC_FETCH_MAX_CLIENTS = 30;
const TRAFFIC_FETCH_CONCURRENCY = 4;
const TRAFFIC_FETCH_TIMEOUT_MS = 8000;

export const ClientManager: React.FC = () => {
  const { colors } = useTheme();
  const [clients, setClients] = useState<Client[]>([]);
  const [filteredClients, setFilteredClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(false);
  const [trafficLoading, setTrafficLoading] = useState(false);
  const [error, setError] = useState('');
  // Map of "node_id:email" -> TrafficData
  const [trafficCache, setTrafficCache] = useState<Record<string, TrafficData | null>>({});
  // Endpoint mode compatibility:
  // - unknown: probe new endpoint first
  // - query: use /client-traffic?email=
  // - legacy: use /client/{email}/traffic
  // - disabled: skip traffic calls (both endpoints unavailable)
  const trafficEndpointModeRef = useRef<'unknown' | 'query' | 'legacy' | 'disabled'>('unknown');
  const trafficEndpointProbeRef = useRef<Promise<void> | null>(null);
  
  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [filterNode, setFilterNode] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterProtocol, setFilterProtocol] = useState('');
  
  // Batch add modal
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [batchText, setBatchText] = useState('');
  const [batchInboundId, setBatchInboundId] = useState('1');
  const [batchTotalGB, setBatchTotalGB] = useState('50');
  const [batchExpiryDays, setBatchExpiryDays] = useState('30');
  
  // Selection
  const [selectedClients, setSelectedClients] = useState<Set<number>>(new Set());
  const refreshInFlightRef = useRef(false);
  
  useEffect(() => {
    // Show cached snapshot instantly if available, then refresh in background.
    try {
      const raw = localStorage.getItem(CLIENTS_PAGE_CACHE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as ClientsPageCache;
        if (
          parsed &&
          typeof parsed.ts === 'number' &&
          Date.now() - parsed.ts < CLIENTS_PAGE_CACHE_MAX_AGE_MS
        ) {
          if (Array.isArray(parsed.clients)) setClients(parsed.clients);
          if (parsed.trafficCache && typeof parsed.trafficCache === 'object') {
            setTrafficCache(parsed.trafficCache);
          }
          if (parsed.endpointMode) {
            trafficEndpointModeRef.current = parsed.endpointMode;
          }
        }
      }
    } catch {
      // Ignore malformed cache.
    }

    loadClients();

    const timer = setInterval(() => {
      loadClients(true);
    }, CLIENTS_PAGE_REFRESH_MS);
    return () => clearInterval(timer);
  }, []);
  
  useEffect(() => {
    applyFilters();
  }, [clients, searchTerm, filterNode, filterStatus, filterProtocol]);
  
  const loadClients = async (silent = false) => {
    if (refreshInFlightRef.current) return;
    refreshInFlightRef.current = true;
    if (!silent) setLoading(true);
    setError('');
    
    try {
      const [clientsRes, nodesRes] = await Promise.all([
        api.get('/v1/clients', { auth: getAuth() }),
        api.get('/v1/nodes', { auth: getAuth() })
      ]);
      
      const nodeList: { id: number; name: string }[] = nodesRes.data || [];
      const nodeNameToId: Record<string, number> = {};
      nodeList.forEach(n => { nodeNameToId[n.name] = n.id; });

      const rawClients: Client[] = (clientsRes.data.clients || []).map((c: Client) => ({
        ...c,
        node_id: nodeNameToId[c.node_name],
      }));

      setClients(rawClients);
      if (!silent) {
        loadTraffic(rawClients).catch(() => undefined);
      }

      // Cache clients immediately, even before traffic refresh completes.
      try {
        const cacheData: ClientsPageCache = {
          ts: Date.now(),
          clients: rawClients,
          trafficCache,
          endpointMode: trafficEndpointModeRef.current,
        };
        localStorage.setItem(CLIENTS_PAGE_CACHE_KEY, JSON.stringify(cacheData));
      } catch {
        // Ignore localStorage write errors.
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load clients');
    } finally {
      if (!silent) setLoading(false);
      refreshInFlightRef.current = false;
    }
  };

  const loadTraffic = async (clientList: Client[]) => {
    // Deduplicate by node_id + email
    const pairs = new Map<string, { node_id: number; email: string }>();
    clientList.forEach(c => {
      if (c.node_id != null) {
        const key = `${c.node_id}:${c.email}`;
        if (!pairs.has(key)) pairs.set(key, { node_id: c.node_id as number, email: c.email });
      }
    });

    if (pairs.size === 0) return;

    setTrafficLoading(true);
    const ensureTrafficEndpointMode = async (node_id: number, email: string) => {
      if (trafficEndpointModeRef.current !== 'unknown') return;
      if (trafficEndpointProbeRef.current) {
        await trafficEndpointProbeRef.current;
        return;
      }

      trafficEndpointProbeRef.current = (async () => {
        try {
          await api.get(`/v1/nodes/${node_id}/client-traffic`, {
            auth: getAuth(),
            params: { email },
          });
          trafficEndpointModeRef.current = 'query';
          return;
        } catch (err: any) {
          if (err?.response?.status !== 404) {
            // Endpoint likely exists; avoid fallback churn on transient errors.
            trafficEndpointModeRef.current = 'query';
            return;
          }
        }

        try {
          await api.get(
            `/v1/nodes/${node_id}/client/${encodeURIComponent(email)}/traffic`,
            { auth: getAuth() }
          );
          trafficEndpointModeRef.current = 'legacy';
        } catch (legacyErr: any) {
          trafficEndpointModeRef.current = legacyErr?.response?.status === 404 ? 'disabled' : 'legacy';
        }
      })();

      try {
        await trafficEndpointProbeRef.current;
      } finally {
        trafficEndpointProbeRef.current = null;
      }
    };

    const firstPair = pairs.values().next().value as { node_id: number; email: string } | undefined;
    if (firstPair) {
      await ensureTrafficEndpointMode(firstPair.node_id, firstPair.email);
    }

    const fetchTraffic = async (node_id: number, email: string): Promise<TrafficData | null> => {
      if (trafficEndpointModeRef.current === 'disabled') {
        return null;
      }

      const tryQuery = async (): Promise<TrafficData> => {
        const res = await api.get('/v1/nodes/' + node_id + '/client-traffic', {
          auth: getAuth(),
          params: { email },
          timeout: TRAFFIC_FETCH_TIMEOUT_MS,
        });
        return res.data as TrafficData;
      };

      const tryLegacy = async (): Promise<TrafficData> => {
        const res = await api.get(
          `/v1/nodes/${node_id}/client/${encodeURIComponent(email)}/traffic`,
          { auth: getAuth(), timeout: TRAFFIC_FETCH_TIMEOUT_MS }
        );
        return res.data as TrafficData;
      };

      try {
        if (trafficEndpointModeRef.current === 'query') {
          return await tryQuery();
        }
        if (trafficEndpointModeRef.current === 'legacy') {
          return await tryLegacy();
        }

        // Unknown mode should be resolved by one-time probe above.
        return await tryQuery();
      } catch (err: any) {
        const status = err?.response?.status;

        // New endpoint not present on older backend => fallback to legacy
        if (trafficEndpointModeRef.current !== 'legacy' && status === 404) {
          try {
            const data = await tryLegacy();
            trafficEndpointModeRef.current = 'legacy';
            return data;
          } catch (legacyErr: any) {
            if (legacyErr?.response?.status === 404) {
              trafficEndpointModeRef.current = 'disabled';
            }
            return null;
          }
        }

        return null;
      }
    };

    const entries = Array.from(pairs.entries()).slice(0, TRAFFIC_FETCH_MAX_CLIENTS);
    const results: Array<readonly [string, TrafficData | null]> = [];
    let cursor = 0;

    const worker = async () => {
      while (cursor < entries.length) {
        const idx = cursor++;
        const [key, { node_id, email }] = entries[idx];
        try {
          const data = await fetchTraffic(node_id, email);
          results[idx] = [key, data] as const;
        } catch {
          results[idx] = [key, null] as const;
        }
      }
    };

    await Promise.all(
      Array.from({ length: Math.min(TRAFFIC_FETCH_CONCURRENCY, entries.length) }, () => worker())
    );

    const cache: Record<string, TrafficData | null> = {};
    results.forEach(([key, data]) => { cache[key] = data; });
    setTrafficCache(cache);
    setTrafficLoading(false);

    // Persist latest snapshot for instant next open.
    try {
      const cacheData: ClientsPageCache = {
        ts: Date.now(),
        clients: clientList,
        trafficCache: cache,
        endpointMode: trafficEndpointModeRef.current,
      };
      localStorage.setItem(CLIENTS_PAGE_CACHE_KEY, JSON.stringify(cacheData));
    } catch {
      // Ignore localStorage write errors.
    }
  };
  
  const applyFilters = () => {
    let filtered = clients;
    
    if (searchTerm) {
      filtered = filtered.filter(c => 
        c.email.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }
    
    if (filterNode) {
      filtered = filtered.filter(c => c.node_name === filterNode);
    }
    
    if (filterStatus === 'active') {
      filtered = filtered.filter(c => c.enable);
    } else if (filterStatus === 'disabled') {
      filtered = filtered.filter(c => !c.enable);
    } else if (filterStatus === 'expired') {
      filtered = filtered.filter(c => c.expiryTime > 0 && c.expiryTime < Date.now());
    } else if (filterStatus === 'depleted') {
      filtered = filtered.filter(c => c.total > 0 && (c.up + c.down) >= c.total);
    }
    
    if (filterProtocol) {
      filtered = filtered.filter(c => c.protocol === filterProtocol);
    }
    
    setFilteredClients(filtered);
  };
  
  const handleBatchAdd = async () => {
    if (!batchText.trim()) {
      alert('Please enter email addresses');
      return;
    }
    
    setLoading(true);
    setError('');
    
    const emails = batchText.split('\n').map(e => e.trim()).filter(e => e);
    const clientsToAdd: BatchAddClient[] = emails.map(email => ({
      email,
      total_gb: parseFloat(batchTotalGB) || undefined,
      expiry_days: parseInt(batchExpiryDays) || undefined,
      enable: true
    }));
    
    try {
      await api.post('/v1/clients/batch-add', {
        inbound_id: parseInt(batchInboundId),
        clients: clientsToAdd
      }, {
        auth: getAuth()
      });
      
      setShowBatchModal(false);
      setBatchText('');
      loadClients();
      alert(`Successfully added ${emails.length} clients`);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add clients');
    } finally {
      setLoading(false);
    }
  };
  
  const handleBatchDelete = async (type: 'selected' | 'expired' | 'depleted') => {
    let clientsToDelete: number[] = [];
    let confirmMessage = '';
    
    if (type === 'selected') {
      clientsToDelete = Array.from(selectedClients);
      confirmMessage = `Delete ${clientsToDelete.length} selected clients?`;
    } else if (type === 'expired') {
      clientsToDelete = clients
        .filter(c => c.expiryTime > 0 && c.expiryTime < Date.now())
        .map(c => c.id);
      confirmMessage = `Delete ${clientsToDelete.length} expired clients?`;
    } else if (type === 'depleted') {
      clientsToDelete = clients
        .filter(c => c.total > 0 && (c.up + c.down) >= c.total)
        .map(c => c.id);
      confirmMessage = `Delete ${clientsToDelete.length} depleted clients?`;
    }
    
    if (clientsToDelete.length === 0) {
      alert('No clients to delete');
      return;
    }
    
    if (!window.confirm(confirmMessage)) return;
    
    setLoading(true);
    try {
      await api.post('/v1/clients/batch-delete', {
        client_ids: clientsToDelete,
        filter: type === 'selected' ? null : type
      }, {
        auth: getAuth()
      });
      
      setSelectedClients(new Set());
      loadClients();
      alert('Clients deleted successfully');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete clients');
    } finally {
      setLoading(false);
    }
  };
  
  const handleResetTraffic = async (clientId: number | null) => {
    if (clientId) {
      if (!window.confirm('Reset traffic for this client?')) return;
    } else {
      if (!window.confirm('Reset traffic for ALL clients?')) return;
    }
    
    setLoading(true);
    try {
      if (clientId) {
        await api.post(`/v1/clients/${clientId}/reset-traffic`, {}, {
          auth: getAuth()
        });
      } else {
        await api.post('/v1/automation/reset-all-traffic', {}, {
          auth: getAuth()
        });
      }
      
      loadClients();
      alert('Traffic reset successfully');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to reset traffic');
    } finally {
      setLoading(false);
    }
  };
  
  const exportToCSV = () => {
    const headers = ['Email', 'Node', 'Protocol', 'Status', 'Download (GB)', 'Total (GB)', 'Expiry Date'];
    const rows = filteredClients.map(c => [
      c.email,
      c.node_name,
      c.protocol,
      c.enable ? 'Active' : 'Disabled',
      (c.down / 1073741824).toFixed(2),
      c.total > 0 ? (c.total / 1073741824).toFixed(2) : 'Unlimited',
      c.expiryTime > 0 ? new Date(c.expiryTime).toLocaleDateString() : 'Never'
    ]);
    
    const csv = [headers, ...rows].map(row => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `clients_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };
  
  const toggleSelection = (clientId: number) => {
    const newSelection = new Set(selectedClients);
    if (newSelection.has(clientId)) {
      newSelection.delete(clientId);
    } else {
      newSelection.add(clientId);
    }
    setSelectedClients(newSelection);
  };
  
  const toggleSelectAll = () => {
    if (selectedClients.size === filteredClients.length) {
      setSelectedClients(new Set());
    } else {
      setSelectedClients(new Set(filteredClients.map(c => c.id)));
    }
  };
  
  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 GB';
    const gb = bytes / 1073741824;
    return gb.toFixed(2) + ' GB';
  };

  /** Returns bytes from cache if loaded, fallback value if not yet loaded, or null if unavailable. */
  const getTrafficBytes = (key: string | null, field: 'upload' | 'download', fallback: number): number | null => {
    if (key == null) return fallback;
    if (!(key in trafficCache)) return fallback; // not yet loaded
    const entry = trafficCache[key];
    if (entry == null) return null; // node unreachable
    return entry[field];
  };
  
  const nodes = Array.from(new Set(clients.map(c => c.node_name)));
  const protocols = Array.from(new Set(clients.map(c => c.protocol)));
  
  return (
    <div className="client-manager">
      <AddClientMultiServer />
      <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0" style={{ color: colors.accent }}>👥 Client Management</h5>
          <div>
            <button 
              className="btn btn-sm me-2"
              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
              onClick={() => setShowBatchModal(true)}
            >
              ➕ Batch Add
            </button>
            <button 
              className="btn btn-sm me-2"
              style={{ backgroundColor: colors.success, borderColor: colors.success, color: '#ffffff' }}
              onClick={exportToCSV}
            >
              📥 Export CSV
            </button>
            <button 
              className="btn btn-sm"
              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
              onClick={() => loadClients()}
              disabled={loading}
            >
              {loading ? '⏳' : '🔄'} Reload
            </button>
          </div>
        </div>
        
        {error && (
          <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
            {error}
          </div>
        )}
        
        {/* Filters */}
        <div className="row g-2 mb-3">
          <div className="col-md-3">
            <input
              type="text"
              className="form-control form-control-sm"
              placeholder="🔍 Search email..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            />
          </div>
          <div className="col-md-2">
            <select
              className="form-select form-select-sm"
              value={filterNode}
              onChange={(e) => setFilterNode(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">All Nodes</option>
              {nodes.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="col-md-2">
            <select
              className="form-select form-select-sm"
              value={filterProtocol}
              onChange={(e) => setFilterProtocol(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">All Protocols</option>
              {protocols.map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
            </select>
          </div>
          <div className="col-md-2">
            <select
              className="form-select form-select-sm"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">All Status</option>
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
              <option value="expired">Expired</option>
              <option value="depleted">Depleted</option>
            </select>
          </div>
          <div className="col-md-3">
            <button
              className="btn btn-sm w-100"
              style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
              onClick={() => {
                setSearchTerm('');
                setFilterNode('');
                setFilterProtocol('');
                setFilterStatus('');
              }}
            >
              Clear Filters
            </button>
          </div>
        </div>
        
        {/* Batch Actions */}
        {selectedClients.size > 0 && (
          <div className="alert mb-3" style={{ backgroundColor: colors.accent + '22', borderColor: colors.accent, color: colors.text.primary }}>
            <strong>{selectedClients.size} clients selected</strong>
            <button
              className="btn btn-sm ms-2"
              style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: '#ffffff' }}
              onClick={() => handleBatchDelete('selected')}
            >
              🗑 Delete Selected
            </button>
          </div>
        )}
        
        <div className="mb-3 d-flex gap-2">
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: '#000' }}
            onClick={() => handleBatchDelete('expired')}
          >
            🗑 Delete Expired
          </button>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: '#000' }}
            onClick={() => handleBatchDelete('depleted')}
          >
            🗑 Delete Depleted
          </button>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.info, borderColor: colors.info, color: '#ffffff' }}
            onClick={() => handleResetTraffic(null)}
          >
            🔄 Reset All Traffic
          </button>
        </div>
      </div>
      
      {/* Client Table */}
      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        {loading && <div className="text-center py-3"><div className="spinner-border spinner-border-sm"></div></div>}
        {!loading && trafficLoading && (
          <div className="text-center py-1 small" style={{ color: colors.text.secondary }}>
            <div className="spinner-border spinner-border-sm me-1" style={{ width: '0.75rem', height: '0.75rem' }}></div>
            Загрузка трафика...
          </div>
        )}
        
        {!loading && filteredClients.length === 0 && (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>No clients found</p>
        )}
        
        {!loading && filteredClients.length > 0 && (
          <div className="table-responsive">
            <table className="table table-sm table-hover" style={{ color: colors.text.primary }}>
              <thead>
                <tr style={{ borderColor: colors.border }}>
                  <th style={{ color: colors.text.secondary }}>
                    <input
                      type="checkbox"
                      checked={selectedClients.size === filteredClients.length}
                      onChange={toggleSelectAll}
                    />
                  </th>
                  <th style={{ color: colors.text.secondary }}>Email</th>
                  <th style={{ color: colors.text.secondary }}>Node</th>
                  <th style={{ color: colors.text.secondary }}>Protocol</th>
                  <th style={{ color: colors.text.secondary }}>Status</th>
                  <th style={{ color: colors.text.secondary }}>Download</th>
                  <th style={{ color: colors.text.secondary }}>Total Limit</th>
                  <th style={{ color: colors.text.secondary }}>Expiry</th>
                  <th style={{ color: colors.text.secondary }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredClients.map((client) => {
                  const trafficKey = client.node_id != null ? `${client.node_id}:${client.email}` : null;
                  const downloadBytes = getTrafficBytes(trafficKey, 'download', client.down);
                  const isExpired = client.expiryTime > 0 && client.expiryTime < Date.now();
                  const isDepleted = client.total > 0 && (client.up + client.down) >= client.total;
                  
                  return (
                    <tr key={client.id} style={{ borderColor: colors.border }}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedClients.has(client.id)}
                          onChange={() => toggleSelection(client.id)}
                        />
                      </td>
                      <td>
                        <strong style={{ color: colors.text.primary }}>{client.email}</strong>
                      </td>
                      <td>
                        <span className="badge" style={{ backgroundColor: colors.bg.tertiary, color: colors.text.primary }}>
                          {client.node_name}
                        </span>
                      </td>
                      <td>
                        <span className="badge" style={{ backgroundColor: colors.accent }}>
                          {client.protocol.toUpperCase()}
                        </span>
                      </td>
                      <td>
                        {client.enable && !isExpired && !isDepleted && (
                          <span style={{ color: colors.success }}>● Active</span>
                        )}
                        {!client.enable && (
                          <span style={{ color: colors.text.secondary }}>○ Disabled</span>
                        )}
                        {isExpired && (
                          <span style={{ color: colors.danger }}>⏰ Expired</span>
                        )}
                        {isDepleted && (
                          <span style={{ color: colors.warning }}>📊 Depleted</span>
                        )}
                      </td>
                      <td>{downloadBytes != null ? formatBytes(downloadBytes) : <span style={{ color: colors.text.secondary }}>—</span>}</td>
                      <td>
                        {client.total > 0 ? formatBytes(client.total) : (
                          <span style={{ color: colors.text.secondary }}>∞</span>
                        )}
                      </td>
                      <td>
                        {client.expiryTime > 0 ? (
                          <small style={{ color: isExpired ? colors.danger : colors.text.secondary }}>
                            {new Date(client.expiryTime).toLocaleDateString()}
                          </small>
                        ) : (
                          <span style={{ color: colors.text.secondary }}>Never</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm"
                          style={{ backgroundColor: colors.info, borderColor: colors.info, color: '#ffffff' }}
                          onClick={() => handleResetTraffic(client.id)}
                          title="Reset traffic"
                        >
                          🔄
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        
        <div className="mt-2 small" style={{ color: colors.text.secondary }}>
          Showing {filteredClients.length} of {clients.length} clients
        </div>
      </div>
      
      {/* Batch Add Modal */}
      {showBatchModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>Batch Add Clients</h6>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => setShowBatchModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <div className="mb-3">
                  <label className="form-label small" style={{ color: colors.text.secondary }}>
                    Email addresses (one per line)
                  </label>
                  <textarea
                    className="form-control"
                    rows={8}
                    value={batchText}
                    onChange={(e) => setBatchText(e.target.value)}
                    placeholder="user1@example.com&#10;user2@example.com&#10;user3@example.com"
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                </div>
                <div className="row g-2">
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: colors.text.secondary }}>
                      Inbound ID
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={batchInboundId}
                      onChange={(e) => setBatchInboundId(e.target.value)}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: colors.text.secondary }}>
                      Total GB (optional)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={batchTotalGB}
                      onChange={(e) => setBatchTotalGB(e.target.value)}
                      placeholder="50"
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: colors.text.secondary }}>
                      Expiry Days (optional)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={batchExpiryDays}
                      onChange={(e) => setBatchExpiryDays(e.target.value)}
                      placeholder="30"
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button
                  className="btn"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                  onClick={() => setShowBatchModal(false)}
                >
                  Cancel
                </button>
                <button
                  className="btn"
                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                  onClick={handleBatchAdd}
                  disabled={loading}
                >
                  {loading ? 'Adding...' : 'Add Clients'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
