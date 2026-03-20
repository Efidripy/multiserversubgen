import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { AddClientMultiServer } from './AddClientMultiServer';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';
import { readStaleCache, writeStaleCache } from '../services/staleCache';
import { useTrafficStatsSubscription, TrafficUpdate } from '../services/useTrafficStatsSubscription';

interface Client {
  id?: string | null;
  password?: string;
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
  totalGB?: number;
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
  inbound_id?: number;
  inbound_remark?: string;
  totalGB?: number;
  expiryTime?: number;
  enable: boolean;
  flow?: string;
}

interface InboundOption {
  id: number;
  node_name: string;
  protocol: string;
  remark: string;
}

interface ClientsPageCache {
  ts: number;
  clients: Client[];
  trafficCache: Record<string, TrafficData | null>;
  endpointMode?: 'unknown' | 'query' | 'legacy' | 'disabled';
}

const clientIdentifier = (client: Client): string | null =>
  (client.id && String(client.id).trim()) ||
  (client.password && String(client.password).trim()) ||
  null;

const clientKey = (client: Client): string =>
  `${client.node_id ?? client.node_name}:${clientIdentifier(client) ?? "no-id"}:${client.email}`;

const CLIENTS_PAGE_CACHE_KEY = 'sub_manager_clients_page_cache_v1';
const CLIENTS_PAGE_CACHE_MAX_AGE_MS = 10 * 60 * 1000; // 10 minutes
const CLIENTS_PAGE_REFRESH_MS = 5 * 60 * 1000; // background refresh interval
const ENABLE_LIVE_CLIENT_TRAFFIC = true;
const TRAFFIC_FETCH_MAX_CLIENTS = 20;
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
  const { t } = useTranslation();
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
  const [batchInboundMode, setBatchInboundMode] = useState<'id' | 'remark'>('id');
  const [batchInboundId, setBatchInboundId] = useState('1');
  const [batchInboundRemark, setBatchInboundRemark] = useState('');
  const [batchFlow, setBatchFlow] = useState('');
  const [batchEnable, setBatchEnable] = useState(true);
  const [batchTotalGB, setBatchTotalGB] = useState('50');
  const [batchExpiryDays, setBatchExpiryDays] = useState('30');
  const [inboundOptions, setInboundOptions] = useState<InboundOption[]>([]);
  
  // Selection
  const [selectedClientKeys, setSelectedClientKeys] = useState<Set<string>>(new Set());
  const refreshInFlightRef = useRef(false);
  const requestIdRef = useRef(0);
  const trafficRefreshTimerRef = useRef<number | null>(null);
  const clientsLoadAbortRef = useRef<AbortController | null>(null);
  const trafficFetchAbortRef = useRef<AbortController | null>(null);
  const realtimeRefreshRef = useRef(0);
  
  useEffect(() => {
    // Show cached snapshot instantly if available, then refresh in background.
    const cached = readStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, CLIENTS_PAGE_CACHE_MAX_AGE_MS);
    if (cached.data) {
      if (Array.isArray(cached.data.clients)) setClients(cached.data.clients);
      if (cached.data.trafficCache && typeof cached.data.trafficCache === 'object') {
        setTrafficCache(cached.data.trafficCache);
      }
      if (cached.data.endpointMode) {
        trafficEndpointModeRef.current = cached.data.endpointMode;
      }
    }

    loadClients(cached.isFresh);

    return () => {
      clientsLoadAbortRef.current?.abort();
      trafficFetchAbortRef.current?.abort();
    };
  }, []);
  
  useEffect(() => {
    applyFilters();
  }, [clients, searchTerm, filterNode, filterStatus, filterProtocol, sortField, sortDirection, trafficCache]);

  useEffect(() => {
    if (!ENABLE_LIVE_CLIENT_TRAFFIC || filteredClients.length === 0) return;

    const visibleSlice = filteredClients.slice(0, TRAFFIC_FETCH_MAX_CLIENTS);
    const missing = visibleSlice.filter((client) => {
      if (client.node_id == null) return false;
      const key = `${client.node_id}:${client.email}`;
      return !(key in trafficCache);
    });

    if (missing.length === 0) return;

    if (trafficRefreshTimerRef.current) {
      window.clearTimeout(trafficRefreshTimerRef.current);
    }

    trafficRefreshTimerRef.current = window.setTimeout(() => {
      loadTraffic(missing).catch(() => undefined);
    }, 350);

    return () => {
      if (trafficRefreshTimerRef.current) {
        window.clearTimeout(trafficRefreshTimerRef.current);
        trafficRefreshTimerRef.current = null;
      }
    };
  }, [filteredClients, trafficCache]);
  
  const loadClients = async (silent = false) => {
    if (refreshInFlightRef.current) {
      clientsLoadAbortRef.current?.abort();
    }

    const controller = new AbortController();
    clientsLoadAbortRef.current = controller;

    refreshInFlightRef.current = true;
    if (!silent) setLoading(true);
    setError('');
    
    try {
      const nodesRes = await api.get('/v1/nodes', { auth: getAuth(), signal: controller.signal });
      const nodeList: { id: number; name: string }[] = nodesRes.data || [];
      const nodeNameToId: Record<string, number> = {};
      nodeList.forEach(n => { nodeNameToId[n.name] = n.id; });

      const inboundsPromise = api.get('/v1/inbounds', { auth: getAuth(), signal: controller.signal });
      const requestId = Date.now();
      requestIdRef.current = requestId;
      let pending = nodeList.length;

      if (nodeList.length === 0) {
        setClients([]);
        setLoading(false);
        refreshInFlightRef.current = false;
        return;
      }

      nodeList.forEach((node) => {
        api.get(`/v1/nodes/${node.id}/clients`, { auth: getAuth(), signal: controller.signal })
          .then((clientsRes) => {
            if (requestIdRef.current !== requestId) return;
            const mappedClients: Client[] = (clientsRes.data.clients || []).map((c: any) => ({
              ...c,
              id: c.id != null ? String(c.id) : null,
              total: Number(c.total ?? c.totalGB ?? 0) || 0,
              up: Number(c.up ?? 0) || 0,
              down: Number(c.down ?? 0) || 0,
              node_id: node.id,
              node_name: c.node_name || node.name,
            }));
            setClients((prev) => {
              const replaced = [
                ...prev.filter((client) => (client.node_id ?? nodeNameToId[client.node_name]) !== node.id),
                ...mappedClients,
              ];
              const deduped = new Map<string, Client>();
              replaced.forEach((client) => {
                deduped.set(clientKey(client), client);
              });
              const next = Array.from(deduped.values());
              writeStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, {
                ts: Date.now(),
                clients: next,
                trafficCache,
                endpointMode: trafficEndpointModeRef.current,
              });
              return next;
            });
          })
          .catch(() => undefined)
          .finally(() => {
            if (requestIdRef.current !== requestId) return;
            pending -= 1;
            if (pending <= 0) {
              if (!silent && trafficEndpointModeRef.current === 'disabled') {
                trafficEndpointModeRef.current = 'unknown';
              }
              if (!silent) setLoading(false);
              refreshInFlightRef.current = false;
            }
          });
      });

      if (!silent && trafficEndpointModeRef.current === 'disabled') {
        // Re-probe endpoints on manual reload to recover after temporary backend mismatch.
        trafficEndpointModeRef.current = 'unknown';
      }

      inboundsPromise
        .then((inboundsRes) => {
          const inboundList: InboundOption[] = (inboundsRes.data?.inbounds || []).map((ib: any) => ({
            id: ib.id,
            node_name: ib.node_name,
            protocol: ib.protocol,
            remark: ib.remark || '',
          }));
          setInboundOptions(inboundList);
        })
        .catch(() => undefined);

    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') {
        if (!silent) setLoading(false);
        refreshInFlightRef.current = false;
        return;
      }
      setError(err.response?.data?.detail || t('clients.loadFailed'));
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

    trafficFetchAbortRef.current?.abort();
    const controller = new AbortController();
    trafficFetchAbortRef.current = controller;

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
            signal: controller.signal,
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
            { auth: getAuth(), signal: controller.signal }
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
          signal: controller.signal,
        });
        return res.data as TrafficData;
      };

      const tryLegacy = async (): Promise<TrafficData> => {
        const res = await api.get(
          `/v1/nodes/${node_id}/client/${encodeURIComponent(email)}/traffic`,
          { auth: getAuth(), timeout: TRAFFIC_FETCH_TIMEOUT_MS, signal: controller.signal }
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

    const entries = Array.from(pairs.entries())
      .filter(([key]) => !(key in trafficCache))
      .slice(0, TRAFFIC_FETCH_MAX_CLIENTS);
    if (entries.length === 0) {
      setTrafficLoading(false);
      return;
    }
    const results: Array<readonly [string, TrafficData | null]> = [];
    let cursor = 0;

    const worker = async () => {
      while (cursor < entries.length) {
        if (controller.signal.aborted) return;
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

    if (controller.signal.aborted) {
      setTrafficLoading(false);
      return;
    }

    const cache: Record<string, TrafficData | null> = { ...trafficCache };
    results.forEach(([key, data]) => { cache[key] = data; });
    setTrafficCache(cache);
    setTrafficLoading(false);

    // Persist latest snapshot for instant next open.
    writeStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, {
      ts: Date.now(),
      clients: clientList,
      trafficCache: cache,
      endpointMode: trafficEndpointModeRef.current,
    });
  };

  const handleRealtimeUpdate = useCallback(
    (update: TrafficUpdate) => {
      if (update.type !== 'client_update' && update.type !== 'traffic_update' && update.type !== 'server_status') {
        return;
      }
      const now = Date.now();
      if (now - realtimeRefreshRef.current < 3000) return;
      realtimeRefreshRef.current = now;
      loadClients(true);
    },
    [],
  );

  useTrafficStatsSubscription({
    channels: ['clients', 'traffic', 'server_status'],
    onUpdate: handleRealtimeUpdate,
    onError: (err) => console.warn('[ClientManager] realtime error:', err),
    fallbackPollIntervalMs: CLIENTS_PAGE_REFRESH_MS,
    fallbackRun: () => loadClients(true),
  });
  
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
      const byId = String(a.id ?? '').localeCompare(String(b.id ?? ''));

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
      alert(t('clients.noEmailsProvided'));
      return;
    }
    
    setLoading(true);
    setError('');
    
    const emails = batchText.split('\n').map(e => e.trim()).filter(e => e);
    const inboundId = parseInt(batchInboundId, 10);
    const inboundRemark = batchInboundRemark.trim();
    const totalGb = parseFloat(batchTotalGB);
    const expiryDays = parseInt(batchExpiryDays, 10);
    const expiryTime = Number.isFinite(expiryDays) && expiryDays > 0
      ? Date.now() + expiryDays * 24 * 60 * 60 * 1000
      : 0;

    if (batchInboundMode === 'id' && (!Number.isFinite(inboundId) || inboundId < 1)) {
      alert(t('clients.invalidInboundId'));
      setLoading(false);
      return;
    }
    if (batchInboundMode === 'remark' && !inboundRemark) {
      alert(t('clients.invalidInboundRemark'));
      setLoading(false);
      return;
    }

    const clientsToAdd: BatchAddClient[] = emails.map(email => ({
      email,
      ...(batchInboundMode === 'id'
        ? { inbound_id: inboundId }
        : { inbound_remark: inboundRemark }),
      totalGB: Number.isFinite(totalGb) && totalGb > 0 ? Math.floor(totalGb * 1024 * 1024 * 1024) : 0,
      expiryTime,
      enable: batchEnable,
      flow: batchFlow,
    }));
    
    try {
      await api.post('/v1/clients/batch-add', {
        node_ids: null,
        clients: clientsToAdd
      }, {
        auth: getAuth()
      });
      
      setShowBatchModal(false);
      setBatchText('');
      setBatchFlow('');
      setBatchEnable(true);
      loadClients();
      alert(t('clients.addedSuccess', { count: emails.length }));
    } catch (err: any) {
      setError(err.response?.data?.detail || t('clients.addFailed'));
    } finally {
      setLoading(false);
    }
  };
  
  const handleBatchDelete = async (type: 'selected' | 'expired' | 'depleted') => {
    setLoading(true);
    try {
      if (type === 'selected') {
        const selected = clients.filter((c) => selectedClientKeys.has(clientKey(c)));
        if (selected.length === 0) {
          alert(t('clients.noClientsSelected'));
          return;
        }
        if (!window.confirm(t('clients.confirmDeleteSelected', { count: selected.length }))) return;

        let failed = 0;
        for (const client of selected) {
          const identifier = clientIdentifier(client);
          if (!identifier || !client.inbound_id) {
            failed += 1;
            continue;
          }
          try {
            await api.delete(`/v1/clients/${encodeURIComponent(identifier)}`, {
              auth: getAuth(),
              params: {
                node_id: client.node_id,
                inbound_id: client.inbound_id,
              },
            });
          } catch {
            failed += 1;
          }
        }

        setSelectedClientKeys(new Set());
        await loadClients();
        if (failed > 0) {
          alert(t('clients.deletePartialError', { count: failed }));
        } else {
          alert(t('clients.deleteSuccess'));
        }
        return;
      }

      const confirmMsg = type === 'expired' ? t('clients.confirmDeleteAllExpired') : t('clients.confirmDeleteAllDepleted');
      if (!window.confirm(confirmMsg)) return;
      await api.post('/v1/clients/batch-delete', {
        node_ids: null,
        email_pattern: null,
        expired_only: type === 'expired',
        depleted_only: type === 'depleted',
      }, {
        auth: getAuth()
      });

      await loadClients();
      alert(t('clients.deleteSuccess'));
    } catch (err: any) {
      setError(err.response?.data?.detail || t('clients.deleteFailed'));
    } finally {
      setLoading(false);
    }
  };
  
  const handleResetTraffic = async (client: Client | null) => {
    if (client) {
      if (!window.confirm(t('clients.confirmResetTraffic'))) return;
    } else {
      if (!window.confirm(t('clients.confirmResetTrafficAll'))) return;
    }
    
    setLoading(true);
    try {
      if (client) {
        const identifier = clientIdentifier(client);
        if (!identifier) {
          throw new Error(t('clients.clientIdentifierMissing'));
        }
        await api.post(`/v1/clients/${encodeURIComponent(identifier)}/reset-traffic`, {
          node_id: client.node_id,
          inbound_id: client.inbound_id,
          email: client.email,
        }, {
          auth: getAuth()
        });
      } else {
        await api.post('/v1/automation/reset-all-traffic', {
          node_ids: null,
        }, {
          auth: getAuth()
        });
      }
      
      loadClients();
      alert(t('clients.resetTrafficSuccess'));
    } catch (err: any) {
      setError(err.response?.data?.detail || t('clients.resetTrafficFailed'));
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
            {t('clients.title')}
          </h5>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
            {error}
          </div>
        )}

        <div className="panel-grid">
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: colors.text.primary }}>{t('common.actions')}</h6>
                <p className="panel-block__hint" style={{ color: colors.text.secondary }}>
                  {t('clients.actionsHint')}
                </p>
              </div>
            </div>
            <div className="panel-inline-actions">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                onClick={() => setShowBatchModal(true)}
              >
                <span className="d-inline-flex align-items-center gap-1"><UIIcon name="plus" size={14} />{t('clients.batchAdd')}</span>
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.success, borderColor: colors.success, color: colors.successText }}
                onClick={exportToCSV}
              >
                <span className="d-inline-flex align-items-center gap-1"><UIIcon name="download" size={14} />{t('clients.exportCsv')}</span>
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                onClick={() => loadClients()}
                disabled={loading}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name={loading ? 'spinner' : 'refresh'} size={14} />
                  {t('common.refresh')}
                </span>
              </button>
            </div>
          </div>

          <div className="panel-block panel-block--wide">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: colors.text.primary }}>{t('common.filter')}</h6>
                <p className="panel-block__hint" style={{ color: colors.text.secondary }}>
                  {t('clients.filtersHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              <input
                type="text"
                className="form-control form-control-sm"
                placeholder={t('clients.searchPlaceholder')}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
              />
              <ChoiceChips
                options={[{ value: '', label: t('clients.allNodes') }, ...nodes.map((n) => ({ value: n, label: n }))]}
                value={filterNode}
                onChange={(value) => setFilterNode(value)}
                colors={colors}
              />
              <ChoiceChips
                options={[{ value: '', label: t('clients.allProtocols') }, ...protocols.map((p) => ({ value: p, label: p.toUpperCase() }))]}
                value={filterProtocol}
                onChange={(value) => setFilterProtocol(value)}
                colors={colors}
              />
              <ChoiceChips
                options={[
                  { value: '', label: t('clients.allStatus') },
                  { value: 'active', label: t('clients.active') },
                  { value: 'disabled', label: t('clients.disabled') },
                  { value: 'expired', label: t('clients.expired') },
                  { value: 'depleted', label: t('clients.depleted') },
                ]}
                value={filterStatus}
                onChange={(value) => setFilterStatus(value)}
                colors={colors}
              />
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                onClick={() => {
                  setSearchTerm('');
                  setFilterNode('');
                  setFilterProtocol('');
                  setFilterStatus('');
                }}
              >
                {t('inbounds.clearFilters')}
              </button>
            </div>
          </div>

          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: colors.text.primary }}>{t('clients.bulkCleanupTitle')}</h6>
                <p className="panel-block__hint" style={{ color: colors.text.secondary }}>
                  {t('clients.bulkCleanupHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              {selectedClientKeys.size > 0 && (
                <div className="alert mb-0" style={{ backgroundColor: colors.accent + '22', borderColor: colors.accent, color: colors.text.primary }}>
                  <strong>{t('clients.selectedCount', { count: selectedClientKeys.size })}</strong>
                  <button
                    className="btn btn-sm ms-2"
                    style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: colors.dangerText }}
                    onClick={() => handleBatchDelete('selected')}
                  >
                    <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />{t('clients.deleteSelected')}</span>
                  </button>
                </div>
              )}
              <div className="panel-inline-actions">
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: colors.text.primary }}
                  onClick={() => handleBatchDelete('expired')}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />{t('clients.deleteExpired')}</span>
                </button>
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: colors.text.primary }}
                  onClick={() => handleBatchDelete('depleted')}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />{t('clients.deleteDepleted')}</span>
                </button>
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.info, borderColor: colors.info, color: colors.infoText }}
                  onClick={() => handleResetTraffic(null)}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="refresh" size={14} />{t('clients.resetAllTraffic')}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      {/* Client Table */}
      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        {loading && filteredClients.length > 0 && (
          <div className="text-center py-1 small" style={{ color: colors.text.secondary }}>
            <div className="spinner-border spinner-border-sm me-1" style={{ width: '0.75rem', height: '0.75rem' }}></div>
            {t('clients.loadingRows')}
          </div>
        )}
        {loading && filteredClients.length === 0 && <div className="text-center py-3"><div className="spinner-border spinner-border-sm"></div></div>}
        {!loading && trafficLoading && (
          <div className="text-center py-1 small" style={{ color: colors.text.secondary }}>
            <div className="spinner-border spinner-border-sm me-1" style={{ width: '0.75rem', height: '0.75rem' }}></div>
            {t('clients.loadingTraffic')}
          </div>
        )}
        
        {!loading && filteredClients.length === 0 && (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>{t('clients.noClientsFound')}</p>
        )}
        
        {filteredClients.length > 0 && (
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
                      {t('clients.email')}{sortIndicator('email')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('node')}>
                      {t('traffic.node')}{sortIndicator('node')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>{t('inbounds.protocol')}</th>
                  <th style={{ color: colors.text.secondary }}>{t('common.status')}</th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('download')}>
                      {t('traffic.download')}{sortIndicator('download')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('total')}>
                      {t('clients.totalLimit')}{sortIndicator('total')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: colors.text.secondary }} onClick={() => applySortFromHeader('expiry')}>
                      {t('clients.expiryTime')}{sortIndicator('expiry')}
                    </button>
                  </th>
                  <th style={{ color: colors.text.secondary }}>{t('common.actions')}</th>
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
                          <span style={{ color: colors.success }}>● {t('clients.active')}</span>
                        )}
                        {!client.enable && (
                          <span style={{ color: colors.text.secondary }}>○ {t('clients.disabled')}</span>
                        )}
                        {isExpired && (
                          <span className="d-inline-flex align-items-center gap-1" style={{ color: colors.danger }}>
                            <UIIcon name="clock" size={13} />
                            {t('clients.expired')}
                          </span>
                        )}
                        {isDepleted && (
                          <span className="d-inline-flex align-items-center gap-1" style={{ color: colors.warning }}>
                            <UIIcon name="traffic" size={13} />
                            {t('clients.depleted')}
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
                          <span style={{ color: colors.text.secondary }}>{t('clients.never')}</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm"
                          style={{ backgroundColor: colors.info, borderColor: colors.info, color: colors.infoText }}
                          onClick={() => handleResetTraffic(client)}
                          title={t('clients.resetTraffic')}
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
          {t('clients.showingCount', { filtered: filteredClients.length, total: clients.length })}
        </div>
      </div>
      
      {/* Batch Add Modal */}
      {showBatchModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>{t('clients.batchAddTitle')}</h6>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => setShowBatchModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <div className="mb-3">
                  <label className="form-label small" style={{ color: colors.text.secondary }}>
                    {t('clients.batchEmailsLabel')}
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
                      {t('clients.inboundSelector')}
                    </label>
                    <ChoiceChips
                      options={[
                        { value: 'id', label: t('clients.inboundById') },
                        { value: 'remark', label: t('clients.inboundByRemark') },
                      ]}
                      value={batchInboundMode}
                      onChange={(value) => setBatchInboundMode(value)}
                      colors={colors}
                      size="md"
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: colors.text.secondary }}>
                      {batchInboundMode === 'id' ? t('clients.inboundIdLabel') : t('clients.inboundRemarkLabel')}
                    </label>
                    {batchInboundMode === 'id' ? (
                      <input
                        type="number"
                        className="form-control"
                        value={batchInboundId}
                        onChange={(e) => setBatchInboundId(e.target.value)}
                        style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      />
                    ) : (
                      <input
                        type="text"
                        className="form-control"
                        value={batchInboundRemark}
                        onChange={(e) => setBatchInboundRemark(e.target.value)}
                        placeholder={t('clients.inboundRemarkPlaceholder')}
                        style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      />
                    )}
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: colors.text.secondary }}>
                      {t('clients.flowLabel')}
                    </label>
                    <ChoiceChips
                      options={[
                        { value: '', label: t('header.common.none') },
                        { value: 'xtls-rprx-vision', label: 'vision' },
                        { value: 'xtls-rprx-vision-udp443', label: 'vision-udp443' },
                      ]}
                      value={batchFlow}
                      onChange={(value) => setBatchFlow(value)}
                      colors={colors}
                      size="md"
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: colors.text.secondary }}>
                      {t('clients.totalGbOptional')}
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
                      {t('clients.expiryDaysOptional')}
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
                  <div className="col-md-4 d-flex align-items-end">
                    <div className="form-check form-switch">
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id="batchEnableToggle"
                        checked={batchEnable}
                        onChange={(e) => setBatchEnable(e.target.checked)}
                      />
                      <label className="form-check-label small" htmlFor="batchEnableToggle" style={{ color: colors.text.secondary }}>
                        {t('clients.enableAfterAdd')}
                      </label>
                    </div>
                  </div>
                </div>
                {inboundOptions.length > 0 && (
                  <div className="mt-3 small" style={{ color: colors.text.secondary, maxHeight: '120px', overflowY: 'auto' }}>
                    {t('clients.knownInbounds')}:
                    {inboundOptions.slice(0, 40).map((ib) => (
                      <div key={`${ib.node_name}:${ib.id}`}>
                        {ib.node_name} | id={ib.id} | {ib.protocol} | {ib.remark || '-'}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button
                  className="btn"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                  onClick={() => setShowBatchModal(false)}
                >
                  {t('common.cancel')}
                </button>
                <button
                  className="btn"
                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                  onClick={handleBatchAdd}
                  disabled={loading}
                >
                  {loading ? t('nodes.adding') : t('clients.addClients')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
