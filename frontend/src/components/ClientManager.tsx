import React, { useState, useEffect, useRef } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { AddClientMultiServer } from './AddClientMultiServer';
import { getAuth } from '../auth';
import { UIIcon } from './UIIcon';

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
  upload?: number | string;
  download?: number | string;
  up?: number | string;
  down?: number | string;
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

const clientKey = (client: Client): string =>
  `${client.node_id ?? client.node_name}:${client.id}:${client.email}`;

const CLIENTS_PAGE_CACHE_KEY = 'sub_manager_clients_page_cache_v1';
const CLIENTS_PAGE_CACHE_MAX_AGE_MS = 10 * 60 * 1000; // 10 minutes
const CLIENTS_PAGE_REFRESH_MS = 5 * 60 * 1000; // background refresh interval
const ENABLE_LIVE_CLIENT_TRAFFIC = true;
const TRAFFIC_FETCH_MAX_CLIENTS = 120;
const TRAFFIC_FETCH_CONCURRENCY = 4;
const TRAFFIC_FETCH_TIMEOUT_MS = 8000;

const asFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const normalized = trimmed.replace(',', '.');
  const numeric = Number(normalized);
  if (Number.isFinite(numeric)) return numeric;
  const match = normalized.match(/^(-?\d+(?:\.\d+)?)\s*([kmgt]?i?b)$/i);
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return null;
  const unit = match[2].toLowerCase();
  const multipliers: Record<string, number> = {
    b: 1,
    kb: 1024,
    kib: 1024,
    mb: 1024 ** 2,
    mib: 1024 ** 2,
    gb: 1024 ** 3,
    gib: 1024 ** 3,
    tb: 1024 ** 4,
    tib: 1024 ** 4,
  };
  const factor = multipliers[unit];
  return factor ? amount * factor : null;
};

const pickTrafficField = (
  entry: TrafficData | null | undefined,
  field: 'upload' | 'download'
): number | null => {
  if (!entry) return null;
  if (field === 'download') {
    return (
      asFiniteNumber(entry.download) ??
      asFiniteNumber(entry.down) ??
      null
    );
  }
  return (
    asFiniteNumber(entry.upload) ??
    asFiniteNumber(entry.up) ??
    null
  );
};

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
  const [sortField, setSortField] = useState<'email' | 'node' | 'download' | 'total' | 'expiry'>('email');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  
  // Batch add modal
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [batchText, setBatchText] = useState('');
  const [batchInboundId, setBatchInboundId] = useState('1');
  const [batchTotalGB, setBatchTotalGB] = useState('50');
  const [batchExpiryDays, setBatchExpiryDays] = useState('30');
  
  // Selection
  const [selectedClientKeys, setSelectedClientKeys] = useState<Set<string>>(new Set());
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
  }, [clients, searchTerm, filterNode, filterStatus, filterProtocol, sortField, sortDirection, trafficCache]);
  
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

      const mappedClients: Client[] = (clientsRes.data.clients || []).map((c: Client) => ({
        ...c,
        node_id: nodeNameToId[c.node_name],
      }));
      // Defensive dedupe in case API/cache returns accidental repeated rows.
      const deduped = new Map<string, Client>();
      mappedClients.forEach((client) => {
        deduped.set(clientKey(client), client);
      });
      const rawClients: Client[] = Array.from(deduped.values());

      setClients(rawClients);
      if (!silent && trafficEndpointModeRef.current === 'disabled') {
        // Re-probe endpoints on manual reload to recover after temporary backend mismatch.
        trafficEndpointModeRef.current = 'unknown';
      }
      if (!silent && ENABLE_LIVE_CLIENT_TRAFFIC) {
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

    const getSortMultiplier = () => (sortDirection === 'asc' ? 1 : -1);
    const compareText = (a: string, b: string) =>
      a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });
    const resolveDownloadBytes = (client: Client): number => {
      const key = client.node_id != null ? `${client.node_id}:${client.email}` : null;
      if (!key) return client.down;
      const entry = trafficCache[key];
      const normalized = pickTrafficField(entry, 'download');
      return normalized ?? client.down;
    };

    const sorted = [...filtered].sort((a, b) => {
      const dir = getSortMultiplier();
      const byEmail = compareText(a.email, b.email);
      const byNode = compareText(a.node_name, b.node_name);
      const byId = a.id - b.id;

      if (sortField === 'email') {
        if (byEmail !== 0) return byEmail * dir;
        if (byNode !== 0) return byNode * dir;
        return byId * dir;
      }

      if (sortField === 'node') {
        if (byNode !== 0) return byNode * dir;
        if (byEmail !== 0) return byEmail * dir;
        return byId * dir;
      }

      if (sortField === 'download') {
        const byDownload = resolveDownloadBytes(a) - resolveDownloadBytes(b);
        if (byDownload !== 0) return byDownload * dir;
        if (byEmail !== 0) return byEmail;
        if (byNode !== 0) return byNode;
        return byId;
      }

      if (sortField === 'total') {
        const byTotal = a.total - b.total;
        if (byTotal !== 0) return byTotal * dir;
        if (byEmail !== 0) return byEmail;
        if (byNode !== 0) return byNode;
        return byId;
      }

      const aExpiry = a.expiryTime > 0 ? a.expiryTime : Number.MAX_SAFE_INTEGER;
      const bExpiry = b.expiryTime > 0 ? b.expiryTime : Number.MAX_SAFE_INTEGER;
      const byExpiry = aExpiry - bExpiry;
      if (byExpiry !== 0) return byExpiry * dir;
      if (byEmail !== 0) return byEmail;
      if (byNode !== 0) return byNode;
      return byId;
    });

    setFilteredClients(sorted);
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
      clientsToDelete = Array.from(
        new Set(
          clients
            .filter((c) => selectedClientKeys.has(clientKey(c)))
            .map((c) => c.id)
        )
      );
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
      
      setSelectedClientKeys(new Set());
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
  
  const toggleSelection = (client: Client) => {
    const key = clientKey(client);
    const newSelection = new Set(selectedClientKeys);
    if (newSelection.has(key)) {
      newSelection.delete(key);
    } else {
      newSelection.add(key);
    }
    setSelectedClientKeys(newSelection);
  };
  
  const toggleSelectAll = () => {
    const visibleKeys = filteredClients.map((c) => clientKey(c));
    const allSelected =
      visibleKeys.length > 0 && visibleKeys.every((key) => selectedClientKeys.has(key));

    if (allSelected) {
      setSelectedClientKeys(new Set());
    } else {
      setSelectedClientKeys(new Set(visibleKeys));
    }
  };

  const applySortFromHeader = (field: 'email' | 'node' | 'download' | 'total' | 'expiry') => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortField(field);
    setSortDirection('asc');
  };
  const sortIndicator = (field: 'email' | 'node' | 'download' | 'total' | 'expiry') =>
    sortField === field ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : '';
  
  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 GB';
    const gb = bytes / 1073741824;
    return gb.toFixed(2) + ' GB';
  };

  /** Returns bytes from cache if loaded, fallback value if not yet loaded, or null if unavailable. */
  const getTrafficBytes = (key: string | null, field: 'upload' | 'download', fallback: number): number => {
    const safeFallback = asFiniteNumber(fallback) ?? 0;
    if (key == null) return safeFallback;
    if (!(key in trafficCache)) return safeFallback; // not yet loaded
    const entry = trafficCache[key];
    if (entry == null) return safeFallback; // unavailable live traffic -> keep DB value
    return pickTrafficField(entry, field) ?? safeFallback;
  };
  
  const nodes = Array.from(new Set(clients.map(c => c.node_name)));
  const protocols = Array.from(new Set(clients.map(c => c.protocol)));
  
  return (
    <div className="client-manager">
      <AddClientMultiServer />
      <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0 d-flex align-items-center gap-2" style={{ color: colors.accent }}>
            <UIIcon name="clients" size={16} />
            Client Management
          </h5>
          <div>
            <button 
              className="btn btn-sm me-2"
              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
              onClick={() => setShowBatchModal(true)}
            >
              <span className="d-inline-flex align-items-center gap-1"><UIIcon name="plus" size={14} />Batch Add</span>
            </button>
            <button 
              className="btn btn-sm me-2"
              style={{ backgroundColor: colors.success, borderColor: colors.success, color: '#ffffff' }}
              onClick={exportToCSV}
            >
              <span className="d-inline-flex align-items-center gap-1"><UIIcon name="download" size={14} />Export CSV</span>
            </button>
            <button 
              className="btn btn-sm"
              style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
              onClick={() => loadClients()}
              disabled={loading}
            >
              <span className="d-inline-flex align-items-center gap-1">
                <UIIcon name={loading ? 'spinner' : 'refresh'} size={14} />
                Reload
              </span>
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
              placeholder="Search email..."
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

        <div className="row g-2 mb-3">
          <div className="col-md-3">
            <select
              className="form-select form-select-sm"
              value={sortField}
              onChange={(e) => setSortField(e.target.value as 'email' | 'node' | 'download' | 'total' | 'expiry')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="email">Sort: Name</option>
              <option value="node">Sort: Node</option>
              <option value="download">Sort: Download Traffic</option>
              <option value="total">Sort: Total Limit</option>
              <option value="expiry">Sort: Expiry Date</option>
            </select>
          </div>
          <div className="col-md-2">
            <select
              className="form-select form-select-sm"
              value={sortDirection}
              onChange={(e) => setSortDirection(e.target.value as 'asc' | 'desc')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="asc">Asc (min→max)</option>
              <option value="desc">Desc (max→min)</option>
            </select>
          </div>
        </div>
        
        {/* Batch Actions */}
        {selectedClientKeys.size > 0 && (
          <div className="alert mb-3" style={{ backgroundColor: colors.accent + '22', borderColor: colors.accent, color: colors.text.primary }}>
            <strong>{selectedClientKeys.size} clients selected</strong>
            <button
              className="btn btn-sm ms-2"
              style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: '#ffffff' }}
              onClick={() => handleBatchDelete('selected')}
            >
              <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />Delete Selected</span>
            </button>
          </div>
        )}
        
        <div className="mb-3 d-flex gap-2">
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: colors.text.primary }}
            onClick={() => handleBatchDelete('expired')}
          >
            <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />Delete Expired</span>
          </button>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: colors.text.primary }}
            onClick={() => handleBatchDelete('depleted')}
          >
            <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />Delete Depleted</span>
          </button>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.info, borderColor: colors.info, color: '#ffffff' }}
            onClick={() => handleResetTraffic(null)}
          >
            <span className="d-inline-flex align-items-center gap-1"><UIIcon name="refresh" size={14} />Reset All Traffic</span>
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
                      checked={
                        filteredClients.length > 0 &&
                        filteredClients.every((c) => selectedClientKeys.has(clientKey(c)))
                      }
                      onChange={toggleSelectAll}
                    />
                  </th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('email')}>
                      Email{sortIndicator('email')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('node')}>
                      Node{sortIndicator('node')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>Protocol</th>
                  <th style={{ color: colors.text.secondary }}>Status</th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('download')}>
                      Download{sortIndicator('download')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('total')}>
                      Total Limit{sortIndicator('total')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('expiry')}>
                      Expiry{sortIndicator('expiry')}
                    </button>
                  </th>
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
                    <tr key={clientKey(client)} style={{ borderColor: colors.border }}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedClientKeys.has(clientKey(client))}
                          onChange={() => toggleSelection(client)}
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
                          <span className="d-inline-flex align-items-center gap-1" style={{ color: colors.danger }}>
                            <UIIcon name="clock" size={13} />
                            Expired
                          </span>
                        )}
                        {isDepleted && (
                          <span className="d-inline-flex align-items-center gap-1" style={{ color: colors.warning }}>
                            <UIIcon name="traffic" size={13} />
                            Depleted
                          </span>
                        )}
                      </td>
                      <td>{formatBytes(downloadBytes)}</td>
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
                          <UIIcon name="refresh" size={14} />
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
