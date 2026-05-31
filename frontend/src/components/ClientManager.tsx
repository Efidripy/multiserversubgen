import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useToast } from './Toast';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { AddClientMultiServer } from './AddClientMultiServer';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';
import { readStaleCache, writeStaleCache } from '../services/staleCache';
import { useTrafficStatsSubscription, TrafficUpdate } from '../services/useTrafficStatsSubscription';
import EmptyState from './EmptyState';
import { ClientEditModal } from './ClientEditModal';

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
  flow?: string;
  remark?: string;
  limitIp?: number;
  security?: string;
  network?: string;
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
  const { t } = useTranslation();
  const { toast } = useToast();
  const _cmPrefs = (() => { try { return JSON.parse(localStorage.getItem('sub_manager_cm_prefs_v1') || '{}'); } catch { return {}; } })();
  const [autoRefresh, setAutoRefresh] = useState<boolean>(_cmPrefs.autoRefresh ?? false);
  const [refreshInterval, setRefreshInterval] = useState<number>(_cmPrefs.refreshInterval ?? 60);
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
  
  // Filters — persisted in localStorage
  const FILTER_STORAGE_KEY = 'sub_manager_client_filters_v1';
  const _savedFilters = (() => { try { return JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY) || '{}'); } catch { return {}; } })();
  const [searchTerm, setSearchTerm] = useState<string>(_savedFilters.searchTerm ?? '');
  const [filterNode, setFilterNode] = useState<string>(_savedFilters.filterNode ?? '');
  const [filterStatus, setFilterStatus] = useState<string>(_savedFilters.filterStatus ?? '');
  const [filterProtocol, setFilterProtocol] = useState<string>(_savedFilters.filterProtocol ?? '');
  const [filterInboundId, setFilterInboundId] = useState<number | null>(null);
  const [filterExpiringSoon, setFilterExpiringSoon] = useState<boolean>(_savedFilters.filterExpiringSoon ?? false);
  const [expiringSoonDays, setExpiringSoonDays] = useState<number>(_savedFilters.expiringSoonDays ?? 7);
  // Online clients map: email → true
  const [onlineEmails, setOnlineEmails] = useState<Set<string>>(new Set());
  const [sortField, setSortField] = useState<'email' | 'node' | 'download' | 'total' | 'expiry' | 'lastOnline' | 'usedPct' | 'health'>(_savedFilters.sortField ?? 'email');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>(_savedFilters.sortDirection ?? 'asc');
  const [onlineFirst, setOnlineFirst] = useState<boolean>(false);
  
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

  // Client Edit Modal
  const [editingClient, setEditingClient] = useState<Client | null>(null);

  // Del Depleted
  const [delDepletedLoading, setDelDepletedLoading] = useState(false);

  // QR modal
  const [qrLinks, setQrLinks] = useState<string[]>([]);
  const [qrEmail, setQrEmail] = useState('');
  const [showQrModal, setShowQrModal] = useState(false);

  // Last online map: email → ISO string
  const [lastOnlineMap, setLastOnlineMap] = useState<Record<string, string>>({});

  // Bulk Adjust Modal
  const [showBulkAdjust, setShowBulkAdjust] = useState(false);
  const [bulkAdjustMode, setBulkAdjustMode] = useState<'add' | 'set'>('add');
  const [bulkAdjustDays, setBulkAdjustDays] = useState('30');
  const [bulkAdjustGB, setBulkAdjustGB] = useState('0');
  const [bulkSetExpiryDate, setBulkSetExpiryDate] = useState('');
  const [bulkAdjustLoading, setBulkAdjustLoading] = useState(false);
  const refreshInFlightRef = useRef(false);
  const requestIdRef = useRef(0);
  const trafficRefreshTimerRef = useRef<number | null>(null);
  const clientsLoadAbortRef = useRef<AbortController | null>(null);
  const trafficFetchAbortRef = useRef<AbortController | null>(null);
  const realtimeRefreshRef = useRef(0);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Attach/Detach inbounds modal
  const [showAttachModal, setShowAttachModal] = useState(false);
  const [attachClient, setAttachClient] = useState<Client | null>(null);
  const [attachInbounds, setAttachInbounds] = useState<Array<{id: number; remark: string; protocol: string}>>([]);
  const [attachSelected, setAttachSelected] = useState<Set<number>>(new Set());
  const [attachLoading, setAttachLoading] = useState(false);
  const [attachMode, setAttachMode] = useState<'attach' | 'detach'>('attach');

  const [denseView, setDenseView] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const NOTES_KEY = 'sub_manager_client_notes_v1';
  const [clientNotes, setClientNotes] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem(NOTES_KEY) || '{}'); } catch { return {}; }
  });
  const saveClientNote = (key: string, note: string) => {
    setClientNotes(prev => {
      const updated = { ...prev };
      if (note.trim()) updated[key] = note.trim();
      else delete updated[key];
      localStorage.setItem(NOTES_KEY, JSON.stringify(updated));
      return updated;
    });
  };

  // IP Search modal
  const [showIpSearch, setShowIpSearch] = useState(false);
  const [ipSearchValue, setIpSearchValue] = useState('');
  const [ipSearchResults, setIpSearchResults] = useState<Array<{email: string; node: string; ips: string[]}>>([]);
  const [ipSearchLoading, setIpSearchLoading] = useState(false);

  // Client Groups modal
  const [showGroupsModal, setShowGroupsModal] = useState(false);
  const [groupsNodeId, setGroupsNodeId] = useState<number | null>(null);
  const [groupsNodeName, setGroupsNodeName] = useState('');
  const [groupsList, setGroupsList] = useState<string[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [groupNewName, setGroupNewName] = useState('');
  const [groupRenameFrom, setGroupRenameFrom] = useState('');
  const [groupRenameTo, setGroupRenameTo] = useState('');
  const [showGroupMembers, setShowGroupMembers] = useState('');
  const [groupMemberEmails, setGroupMemberEmails] = useState<string[]>([]);
  const [groupMembersLoading, setGroupMembersLoading] = useState(false);
  const [groupAddEmails, setGroupAddEmails] = useState('');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const copyWithFeedback = useCallback((text: string, key: string, label = 'Copied') => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedKey(key);
      toast(label, 'info');
      setTimeout(() => setCopiedKey(k => k === key ? null : k), 1500);
    });
  }, [toast]);

  useEffect(() => {
    // Handle navigation from InboundManager — apply inbound filter if set
    try {
      const nav = sessionStorage.getItem('sm_nav_inbound_filter');
      if (nav) {
        sessionStorage.removeItem('sm_nav_inbound_filter');
        const { id } = JSON.parse(nav);
        if (id) setFilterInboundId(Number(id));
      }
    } catch {}
    // Handle navigation from TrafficStats — apply email search filter if set
    try {
      const emailNav = sessionStorage.getItem('sm_nav_client_search');
      if (emailNav) {
        sessionStorage.removeItem('sm_nav_client_search');
        setSearchTerm(emailNav);
      }
    } catch {}
    // Handle navigation from InboundManager "Add Client" — open batch add with pre-filled inbound
    try {
      const addToInbound = sessionStorage.getItem('sm_nav_add_to_inbound');
      if (addToInbound) {
        sessionStorage.removeItem('sm_nav_add_to_inbound');
        setBatchInboundId(addToInbound);
        setShowBatchModal(true);
      }
    } catch {}

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

    // Load online clients
    const { user, password } = getAuth();
    api.get('/v1/clients/online', { auth: { username: user, password } })
      .then(res => {
        const list: Array<{email: string}> = res.data?.online || [];
        setOnlineEmails(new Set(list.map(x => x.email)));
      })
      .catch(() => {});

    // Load last-online timestamps
    api.post('/v1/clients/last-online', {}, { auth: { username: user, password } })
      .then(res => {
        const map: Record<string, string> = {};
        const results: Array<{email: string; last_online?: string}> = res.data?.results || [];
        results.forEach(r => { if (r.last_online) map[r.email] = r.last_online; });
        setLastOnlineMap(map);
      })
      .catch(() => {});

    return () => {
      clientsLoadAbortRef.current?.abort();
      trafficFetchAbortRef.current?.abort();
    };
  }, []);
  
  useEffect(() => {
    applyFilters();
    setCurrentPage(1);
    try {
      localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({ searchTerm, filterNode, filterStatus, filterProtocol, filterExpiringSoon, expiringSoonDays, sortField, sortDirection }));
    } catch {}
  }, [clients, searchTerm, filterNode, filterStatus, filterProtocol, filterExpiringSoon, expiringSoonDays, filterInboundId, sortField, sortDirection, onlineFirst, onlineEmails, trafficCache]);

  // Auto-refresh
  useEffect(() => {
    try { localStorage.setItem('sub_manager_cm_prefs_v1', JSON.stringify({ autoRefresh, refreshInterval })); } catch {}
  }, [autoRefresh, refreshInterval]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => loadClients(true), refreshInterval * 1000);
    return () => clearInterval(id);
  }, [autoRefresh, refreshInterval]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

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

    const requestId = Date.now();
    requestIdRef.current = requestId;

    try {
      // Fire both requests in parallel — backend serves from cache (20s fresh / 180s stale).
      const [nodesRes, clientsRes, inboundsRes] = await Promise.all([
        api.get('/v1/nodes', { auth: getAuth(), signal: controller.signal }),
        api.get('/v1/clients', { auth: getAuth(), signal: controller.signal }),
        api.get('/v1/inbounds', { auth: getAuth(), signal: controller.signal }),
      ]);

      if (requestIdRef.current !== requestId) return;

      const nodeList: { id: number; name: string }[] = nodesRes.data || [];
      const nodeNameToId: Record<string, number> = {};
      nodeList.forEach(n => { nodeNameToId[n.name] = n.id; });

      const rawClients: any[] = clientsRes.data?.clients || [];
      const mappedClients: Client[] = rawClients.map((c: any) => ({
        ...c,
        id: c.id != null ? String(c.id) : null,
        total: Number(c.total ?? c.totalGB ?? 0) || 0,
        up: Number(c.up ?? 0) || 0,
        down: Number(c.down ?? 0) || 0,
        node_id: c.node_id ?? nodeNameToId[c.node_name] ?? null,
        node_name: c.node_name || '',
      }));

      const deduped = new Map<string, Client>();
      mappedClients.forEach(c => deduped.set(clientKey(c), c));
      const next = Array.from(deduped.values());

      setClients(next);
      writeStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, {
        ts: Date.now(),
        clients: next,
        trafficCache,
        endpointMode: trafficEndpointModeRef.current,
      });

      const inboundList: InboundOption[] = (inboundsRes.data?.inbounds || []).map((ib: any) => ({
        id: ib.id,
        node_name: ib.node_name,
        protocol: ib.protocol,
        remark: ib.remark || '',
      }));
      setInboundOptions(inboundList);

      if (!silent && trafficEndpointModeRef.current === 'disabled') {
        trafficEndpointModeRef.current = 'unknown';
      }
      if (!silent) setLoading(false);
      refreshInFlightRef.current = false;

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
  
  const handleClientEditClick = (client: Client) => {
    setEditingClient(client);
  };

  const handleDelDepleted = async () => {
    if (!window.confirm(t('messages.delDepletedConfirm'))) return;
    setDelDepletedLoading(true);
    const { user, password } = getAuth();
    try {
      const res = await api.post('/v1/clients/del-depleted', {}, { auth: { username: user, password } });
      toast(t('messages.delDepletedDone', { count: res.data?.total_deleted ?? 0 }), 'success');
      loadClients(true);
    } catch (e: any) {
      toast(e.response?.data?.detail || 'Failed', 'error');
    } finally {
      setDelDepletedLoading(false);
    }
  };

  const handleBulkAdjust = async () => {
    const { user, password } = getAuth();
    const selectedEmails = filteredClients
      .filter((c) => selectedClientKeys.has(clientKey(c)))
      .map((c) => c.email);
    const targetEmails = selectedEmails.length > 0 ? selectedEmails : filteredClients.map(c => c.email);

    setBulkAdjustLoading(true);
    try {
      if (bulkAdjustMode === 'set') {
        // Set exact expiry date for each client individually
        if (!bulkSetExpiryDate) { toast('Please select a date', 'warning'); setBulkAdjustLoading(false); return; }
        const expiryMs = new Date(bulkSetExpiryDate).getTime();
        const targetClients = filteredClients.filter(c => targetEmails.includes(c.email));
        let done = 0;
        for (const c of targetClients) {
          try {
            await api.put(`/v1/clients/${c.id}`, {
              node_id: c.node_id,
              inbound_id: c.inbound_id,
              updates: { email: c.email, expiryTime: expiryMs, enable: c.enable, totalGB: c.totalGB ?? c.total },
            }, { auth: { username: user, password } });
            done++;
          } catch { /* continue */ }
        }
        toast(`Expiry date set for ${done} clients`, 'success');
      } else {
        const addDays = parseInt(bulkAdjustDays) || 0;
        const addGB = parseFloat(bulkAdjustGB) || 0;
        const addBytes = Math.round(addGB * 1024 * 1024 * 1024);
        if (!addDays && !addBytes) { setBulkAdjustLoading(false); return; }
        const res = await api.post('/v1/clients/bulk-adjust', {
          emails: targetEmails,
          add_days: addDays,
          add_bytes: addBytes,
        }, { auth: { username: user, password } });
        toast(t('messages.bulkAdjustDone', { count: res.data?.total_adjusted ?? 0 }), 'success');
      }
      setShowBulkAdjust(false);
      loadClients(true);
    } catch (e: any) {
      toast(e.response?.data?.detail || 'Failed', 'error');
    } finally {
      setBulkAdjustLoading(false);
    }
  };

  const handleOpenAttach = async (client: Client, mode: 'attach' | 'detach') => {
    if (!client.node_id) { toast('Client has no node_id', 'warning'); return; }
    setAttachClient(client);
    setAttachMode(mode);
    setAttachSelected(new Set());
    setShowAttachModal(true);
    setAttachLoading(true);
    try {
      const res = await api.get('/v1/inbounds', { auth: getAuth() });
      const all: Array<{id: number; node_id: number; protocol: string; remark: string}> = res.data?.inbounds || res.data || [];
      setAttachInbounds(all.filter(ib => ib.node_id === client.node_id).map(ib => ({ id: ib.id, remark: ib.remark, protocol: ib.protocol })));
    } catch { setAttachInbounds([]); }
    finally { setAttachLoading(false); }
  };

  const handleAttachSubmit = async () => {
    if (!attachClient || !attachClient.node_id || attachSelected.size === 0) return;
    const endpoint = attachMode === 'attach'
      ? `/v1/clients/${encodeURIComponent(attachClient.email)}/attach`
      : `/v1/clients/${encodeURIComponent(attachClient.email)}/detach`;
    try {
      await api.post(endpoint, { node_id: attachClient.node_id, inbound_ids: Array.from(attachSelected) }, { auth: getAuth() });
      toast(`${attachMode === 'attach' ? 'Attached' : 'Detached'} successfully`, 'success');
      setShowAttachModal(false);
      loadClients(true);
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleOpenGroups = async (nodeId: number, nodeName: string) => {
    setGroupsNodeId(nodeId);
    setGroupsNodeName(nodeName);
    setShowGroupsModal(true);
    setGroupsLoading(true);
    setGroupsList([]);
    setShowGroupMembers('');
    setGroupMemberEmails([]);
    setGroupNewName('');
    setGroupRenameFrom('');
    setGroupRenameTo('');
    try {
      const res = await api.get(`/v1/nodes/${nodeId}/client-groups`, { auth: getAuth() });
      setGroupsList(res.data?.groups ?? res.data ?? []);
    } catch { setGroupsList([]); }
    finally { setGroupsLoading(false); }
  };

  const handleCreateGroup = async () => {
    if (!groupsNodeId || !groupNewName.trim()) return;
    try {
      await api.post(`/v1/nodes/${groupsNodeId}/client-groups`, { name: groupNewName.trim() }, { auth: getAuth() });
      setGroupNewName('');
      await handleOpenGroups(groupsNodeId, groupsNodeName);
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleDeleteGroup = async (name: string) => {
    if (!groupsNodeId || !window.confirm(`Delete group "${name}"?`)) return;
    try {
      await api.delete(`/v1/nodes/${groupsNodeId}/client-groups/${encodeURIComponent(name)}`, { auth: getAuth() });
      setGroupsList(prev => prev.filter(g => g !== name));
      if (showGroupMembers === name) { setShowGroupMembers(''); setGroupMemberEmails([]); }
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleRenameGroup = async () => {
    if (!groupsNodeId || !groupRenameFrom || !groupRenameTo.trim()) return;
    try {
      await api.put(`/v1/nodes/${groupsNodeId}/client-groups/${encodeURIComponent(groupRenameFrom)}`, { newName: groupRenameTo.trim() }, { auth: getAuth() });
      setGroupsList(prev => prev.map(g => g === groupRenameFrom ? groupRenameTo.trim() : g));
      setGroupRenameFrom('');
      setGroupRenameTo('');
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleViewGroupMembers = async (name: string) => {
    if (!groupsNodeId) return;
    if (showGroupMembers === name) { setShowGroupMembers(''); setGroupMemberEmails([]); return; }
    setShowGroupMembers(name);
    setGroupMembersLoading(true);
    setGroupMemberEmails([]);
    try {
      const res = await api.get(`/v1/nodes/${groupsNodeId}/client-groups/${encodeURIComponent(name)}/emails`, { auth: getAuth() });
      setGroupMemberEmails(res.data?.emails ?? res.data ?? []);
    } catch { setGroupMemberEmails([]); }
    finally { setGroupMembersLoading(false); }
  };

  const handleAddToGroup = async (groupName: string) => {
    if (!groupsNodeId || !groupAddEmails.trim()) return;
    const emails = groupAddEmails.split(/[\n,;]+/).map(e => e.trim()).filter(Boolean);
    try {
      await api.post(`/v1/nodes/${groupsNodeId}/client-groups/${encodeURIComponent(groupName)}/add`, { emails }, { auth: getAuth() });
      setGroupAddEmails('');
      await handleViewGroupMembers(groupName);
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const handleRemoveFromGroup = async (groupName: string, email: string) => {
    if (!groupsNodeId) return;
    try {
      await api.post(`/v1/nodes/${groupsNodeId}/client-groups/${encodeURIComponent(groupName)}/remove`, { emails: [email] }, { auth: getAuth() });
      setGroupMemberEmails(prev => prev.filter(e => e !== email));
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
  };

  const getHealthScore = (client: Client): number => {
    if (!client.enable) return 0;
    const now = Date.now();
    const isExpired = client.expiryTime > 0 && client.expiryTime < now;
    if (isExpired) return 5;
    const isDepleted = client.total > 0 && (client.up + client.down) >= client.total;
    if (isDepleted) return 10;
    let score = 60;
    if (client.total > 0) {
      const usedPct = (client.up + client.down) / client.total;
      score += Math.round((1 - usedPct) * 25);
    } else {
      score += 25;
    }
    if (client.expiryTime > 0) {
      const daysLeft = (client.expiryTime - now) / 86400_000;
      score += Math.round(Math.min(daysLeft / 30, 1) * 15);
    } else {
      score += 15;
    }
    return Math.min(score, 100);
  };

  const applyFilters = () => {
    let filtered = clients;
    
    if (searchTerm) {
      const q = searchTerm.toLowerCase().trim();
      // Support space-separated AND terms, or | for OR
      const orParts = q.split('|').map(p => p.trim()).filter(Boolean);
      filtered = filtered.filter(c => {
        const haystack = `${c.email} ${c.node_name} ${c.protocol}`.toLowerCase();
        return orParts.some(orPart => {
          const andTerms = orPart.split(' ').filter(Boolean);
          return andTerms.every(term => haystack.includes(term));
        });
      });
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
    } else if (filterStatus === 'online') {
      filtered = filtered.filter(c => onlineEmails.has(c.email));
    } else if (filterStatus === 'offline') {
      filtered = filtered.filter(c => !onlineEmails.has(c.email));
    }
    
    if (filterProtocol) {
      filtered = filtered.filter(c => c.protocol === filterProtocol);
    }
    if (filterInboundId !== null) {
      filtered = filtered.filter(c => c.inbound_id === filterInboundId);
    }
    if (filterExpiringSoon) {
      const inNd = Date.now() + expiringSoonDays * 86400 * 1000;
      filtered = filtered.filter(c => c.expiryTime > 0 && c.expiryTime <= inNd && c.expiryTime > Date.now());
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

      if (sortField === 'usedPct') {
        const pct = (c: Client) => c.total > 0 ? (c.up + c.down) / c.total : 0;
        const byPct = pct(a) - pct(b);
        if (byPct !== 0) return byPct * dir;
        if (byEmail !== 0) return byEmail;
        return byNode;
      }

      if (sortField === 'lastOnline') {
        const aLo = lastOnlineMap[a.email] ? new Date(lastOnlineMap[a.email]).getTime() : 0;
        const bLo = lastOnlineMap[b.email] ? new Date(lastOnlineMap[b.email]).getTime() : 0;
        const byLo = aLo - bLo;
        if (byLo !== 0) return byLo * dir;
        if (byEmail !== 0) return byEmail;
        return byNode;
      }

      if (sortField === 'health') {
        const byHealth = getHealthScore(a) - getHealthScore(b);
        if (byHealth !== 0) return byHealth * dir;
        if (byEmail !== 0) return byEmail;
        return byNode;
      }

      const aExpiry = a.expiryTime > 0 ? a.expiryTime : Number.MAX_SAFE_INTEGER;
      const bExpiry = b.expiryTime > 0 ? b.expiryTime : Number.MAX_SAFE_INTEGER;
      const byExpiry = aExpiry - bExpiry;
      if (byExpiry !== 0) return byExpiry * dir;
      if (byEmail !== 0) return byEmail;
      if (byNode !== 0) return byNode;
      return byId;
    });

    if (onlineFirst) {
      sorted.sort((a, b) => {
        const aOnline = onlineEmails.has(a.email) ? 1 : 0;
        const bOnline = onlineEmails.has(b.email) ? 1 : 0;
        return bOnline - aOnline;
      });
    }
    setFilteredClients(sorted);
  };

  const handleBatchAdd = async () => {
    if (!batchText.trim()) {
      toast(t('clients.noEmailsProvided'), 'warning');
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
      toast(t('clients.invalidInboundId'), 'warning');
      setLoading(false);
      return;
    }
    if (batchInboundMode === 'remark' && !inboundRemark) {
      toast(t('clients.invalidInboundRemark'), 'warning');
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
      toast(t('clients.addedSuccess', { count: emails.length }), 'success');
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
          toast(t('clients.noClientsSelected'), 'warning');
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
          toast(t('clients.deletePartialError', { count: failed }), 'warning');
        } else {
          toast(t('clients.deleteSuccess'), 'success');
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
      toast(t('clients.deleteSuccess'), 'success');
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
      toast(t('clients.resetTrafficSuccess'), 'success');
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

  const selectAllBy = (predicate: (c: Client) => boolean) => {
    const now = Date.now();
    const keys = clients.filter(predicate).map(clientKey);
    setSelectedClientKeys(prev => {
      const next = new Set(prev);
      keys.forEach(k => next.add(k));
      return next;
    });
    void now;
  };

  const applySortFromHeader = (field: 'email' | 'node' | 'download' | 'total' | 'expiry' | 'lastOnline' | 'usedPct' | 'health') => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortField(field);
    setSortDirection('asc');
  };
  const sortIndicator = (field: 'email' | 'node' | 'download' | 'total' | 'expiry' | 'lastOnline' | 'usedPct' | 'health') =>
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
    <div className={`client-manager${showAddForm ? '' : ' client-manager--no-form'}`}>
      {showAddForm && <AddClientMultiServer />}
      <div className="card p-3 mb-3">


        {error && (
          <div className="alert alert-danger">
            {error}
          </div>
        )}

        <div className="panel-grid panel-grid--3col">
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title">{t('common.actions')}</h6>
                <p className="panel-block__hint">
                  {t('clients.actionsHint')}
                </p>
              </div>
            </div>
            <div className="panel-inline-actions">
              <button
                className={`btn btn-sm ${showAddForm ? 'btn-ghost-accent' : 'btn-accent'}`}
                onClick={() => setShowAddForm(v => !v)}
                title={showAddForm ? 'Hide add form' : 'Add client to multiple servers'}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name={showAddForm ? 'x' : 'plus'} size={14} />
                  {showAddForm ? t('common.close') : t('common.add')}
                </span>
              </button>
              <button
                className="btn btn-sm btn-neutral"
                onClick={() => setShowBatchModal(true)}
              >
                <span className="d-inline-flex align-items-center gap-1"><UIIcon name="plus" size={14} />{t('clients.batchAdd')}</span>
              </button>
              <button
                className="btn btn-sm btn-success-fill"
                onClick={exportToCSV}
              >
                <span className="d-inline-flex align-items-center gap-1"><UIIcon name="download" size={14} />{t('clients.exportCsv')}</span>
              </button>
              <label
                className="btn btn-sm btn-neutral mb-0"
                title="Import clients from CSV (columns: email, totalGB, expiry_days, protocol)"
              >
                <span className="d-inline-flex align-items-center gap-1"><UIIcon name="upload" size={14} /> Import CSV</span>
                <input type="file" accept=".csv,.txt" className="d-none"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (!file) return;
                    const text = await file.text();
                    const lines = text.split(/[\r\n]+/).filter(l => l.trim());
                    // Skip header if it looks like one
                    const start = lines[0]?.toLowerCase().includes('email') ? 1 : 0;
                    const emails: string[] = [];
                    for (let i = start; i < lines.length; i++) {
                      const [email] = lines[i].split(',');
                      if (email?.trim()) emails.push(email.trim());
                    }
                    if (emails.length === 0) { toast('No emails found in CSV', 'error'); return; }
                    // Open batch modal with these emails pre-filled
                    const emailsStr = emails.join('\n');
                    setBatchText(emailsStr);
                    setShowBatchModal(true);
                    toast(`Loaded ${emails.length} emails from CSV`, 'info');
                  }}
                />
              </label>
              <button
                className="btn btn-sm btn-accent"
                onClick={() => loadClients()}
                disabled={loading}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name={loading ? 'spinner' : 'refresh'} size={14} />
                  {t('common.refresh')}
                </span>
              </button>
              <button
                className={`btn btn-sm ${autoRefresh ? 'btn-ghost-accent' : 'btn-neutral'}`}
                onClick={() => setAutoRefresh(v => !v)}
                title={autoRefresh ? `Auto-refresh every ${refreshInterval}s — click to stop` : 'Enable auto-refresh'}
              >
                ⟳ Auto
              </button>
              {autoRefresh && (
                <select className="form-select form-select-sm form-select-inline"
                  value={refreshInterval} onChange={e => setRefreshInterval(Number(e.target.value))}>
                  {[15, 30, 60, 120, 300].map(s => <option key={s} value={s}>{s}s</option>)}
                </select>
              )}
            </div>
          </div>

          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title">{t('common.filter')}</h6>
                <p className="panel-block__hint">
                  {t('clients.filtersHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              <input
                ref={searchInputRef}
                type="text"
                className="form-control form-control-sm"
                placeholder={t('clients.searchPlaceholder') + ' (Ctrl+/) — space=AND, |=OR'}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}

              />
              <ChoiceChips
                options={[{ value: '', label: t('clients.allNodes') }, ...nodes.map((n) => ({ value: n, label: n }))]}
                value={filterNode}
                onChange={(value) => setFilterNode(value)}
                
              />
              <ChoiceChips
                options={[{ value: '', label: t('clients.allProtocols') }, ...protocols.map((p) => ({ value: p, label: p.toUpperCase() }))]}
                value={filterProtocol}
                onChange={(value) => setFilterProtocol(value)}
                
              />
              {inboundOptions.length > 0 && (
                <select
                  className="form-select form-select-sm form-select-inline"
                  value={filterInboundId ?? ''}
                  onChange={e => setFilterInboundId(e.target.value ? Number(e.target.value) : null)}
                  style={{ maxWidth: '180px', fontSize: '0.75rem' }}
                >
                  <option value="">All inbounds</option>
                  {inboundOptions.slice(0, 40).map((ib, i) => (
                    <option key={`${i}-${ib.id}`} value={ib.id}>{ib.remark || `#${ib.id}`} ({ib.node_name})</option>
                  ))}
                </select>
              )}
              <ChoiceChips
                options={[
                  { value: '', label: t('clients.allStatus') },
                  { value: 'active', label: t('clients.active') },
                  { value: 'disabled', label: t('clients.disabled') },
                  { value: 'expired', label: t('clients.expired') },
                  { value: 'depleted', label: t('clients.depleted') },
                  { value: 'online', label: '● Online' },
                  { value: 'offline', label: '○ Offline' },
                ]}
                value={filterStatus}
                onChange={(value) => setFilterStatus(value)}
                
              />
              <div className="d-flex align-items-center gap-1">
                <button
                  className={`btn btn-sm ${filterExpiringSoon ? 'btn-warning-fill' : 'btn-neutral'}`}
                  style={{ fontSize: '0.75rem' }}
                  onClick={() => setFilterExpiringSoon(v => !v)}
                >
                  ⏱ Expiring {expiringSoonDays}d
                </button>
                <select
                  className="form-select form-select-sm form-select-inline"
                  value={expiringSoonDays}
                  onChange={e => setExpiringSoonDays(Number(e.target.value))}
                  style={{ padding: '2px 20px 2px 6px' }}
                >
                  {[1, 3, 7, 14, 30, 60].map(d => (
                    <option key={d} value={d}>{d}d</option>
                  ))}
                </select>
              </div>
              <button
                className={`btn btn-sm ${onlineFirst ? 'btn-ghost-accent' : 'btn-neutral'}`}
                onClick={() => setOnlineFirst(v => !v)}
                title="Show online clients first"
              >
                ● Online first
              </button>
              <button
                className="btn btn-sm btn-neutral"
                title="Find clients with same email on multiple nodes (duplicates)"
                onClick={() => {
                  const emailCount: Record<string, string[]> = {};
                  clients.forEach(c => {
                    if (!emailCount[c.email]) emailCount[c.email] = [];
                    emailCount[c.email].push(c.node_name || c.node_id?.toString() || '?');
                  });
                  const dupes = Object.entries(emailCount).filter(([, nodes]) => nodes.length > 1);
                  if (dupes.length === 0) { toast('No duplicate emails found', 'info'); return; }
                  setSearchTerm(dupes[0][0]);
                  toast(`${dupes.length} duplicate email(s) found — showing first: "${dupes[0][0]}" (${dupes[0][1].join(', ')})`, 'warning');
                }}
              >
                ⎊ Duplicates
              </button>
              {(searchTerm || filterNode || filterProtocol || filterStatus || filterExpiringSoon || filterInboundId !== null) && (
                <button
                  className="btn btn-sm btn-ghost-warning"
                  onClick={() => {
                    setSearchTerm('');
                    setFilterNode('');
                    setFilterProtocol('');
                    setFilterStatus('');
                    setFilterExpiringSoon(false);
                    setFilterInboundId(null);
                  }}
                >
                  ✕ {t('inbounds.clearFilters')}
                </button>
              )}
            </div>
          </div>

          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title">{t('clients.bulkCleanupTitle')}</h6>
                <p className="panel-block__hint">
                  {t('clients.bulkCleanupHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              {selectedClientKeys.size > 0 && (
                <div className="selection-bar">
                  <strong className="selection-bar__count">{t('clients.selectedCount', { count: selectedClientKeys.size })}</strong>
                  <button className="btn btn-sm btn-neutral"
                    title="Copy emails of selected clients to clipboard"
                    onClick={() => {
                      const emails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      navigator.clipboard.writeText(emails.join('\n')).then(() => toast(`Copied ${emails.length} email(s)`, 'info'));
                    }}>
                    <UIIcon name="copy" size={13} /> Copy emails
                  </button>
                  <button className="btn btn-sm btn-danger-fill" onClick={() => handleBatchDelete('selected')}>
                    <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={13} />{t('clients.deleteSelected')}</span>
                  </button>
                  <button className="btn btn-sm btn-success-fill"
                    onClick={async () => {
                      const emails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      const { user, password } = getAuth();
                      try {
                        await api.post('/v1/clients/bulk-enable', { emails, enable: true }, { auth: { username: user, password } });
                        toast(`Enabled ${emails.length} clients`, 'success');
                        loadClients(true);
                      } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                    }}>
                    ● Enable
                  </button>
                  <button className="btn btn-sm btn-neutral"
                    onClick={async () => {
                      const emails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      const { user, password } = getAuth();
                      try {
                        await api.post('/v1/clients/bulk-enable', { emails, enable: false }, { auth: { username: user, password } });
                        toast(`Disabled ${emails.length} clients`, 'success');
                        loadClients(true);
                      } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                    }}>
                    ○ Disable
                  </button>
                  <button className="btn btn-sm btn-accent"
                    onClick={() => { setBulkAdjustMode('add'); setShowBulkAdjust(true); }}>
                    +days/GB
                  </button>
                  <button className="btn btn-sm btn-neutral"
                    title="Set an exact traffic limit for selected clients"
                    onClick={async () => {
                      const selected = filteredClients.filter(c => selectedClientKeys.has(clientKey(c)));
                      const input = window.prompt(`Set traffic limit (GB) for ${selected.length} clients (0 = unlimited):`, '50');
                      const gb = parseFloat(input || '');
                      if (isNaN(gb) || gb < 0) return;
                      const { user, password } = getAuth();
                      let done = 0;
                      for (const c of selected) {
                        try {
                          await api.put(`/v1/clients/${encodeURIComponent(c.id || '')}`, {
                            node_id: c.node_id, inbound_id: c.inbound_id,
                            updates: { email: c.email, totalGB: gb, enable: c.enable },
                          }, { auth: { username: user, password } });
                          done++;
                        } catch { /* continue */ }
                      }
                      toast(`Limit set for ${done} clients`, 'success');
                      loadClients(true);
                    }}>
                    Set Limit
                  </button>
                  <button className="btn btn-sm btn-info-fill"
                    onClick={async () => {
                      const emails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      if (!window.confirm(`Reset traffic for ${emails.length} clients?`)) return;
                      const { user, password } = getAuth();
                      try {
                        const res = await api.post('/v1/clients/bulk-reset-traffic', { emails }, { auth: { username: user, password } });
                        toast(`Traffic reset: ${res.data?.successful ?? emails.length} clients`, 'success');
                        loadClients(true);
                      } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                    }}>
                    Reset Traffic
                  </button>
                  <button className="btn btn-sm btn-ghost-warning"
                    title="Freeze all selected clients (expire immediately + disable)"
                    onClick={async () => {
                      const selected = filteredClients.filter(c => selectedClientKeys.has(clientKey(c)));
                      if (!window.confirm(`Freeze ${selected.length} clients? This sets expiry=now and disables them.`)) return;
                      const now = Date.now();
                      let done = 0;
                      for (const c of selected) {
                        const id = clientIdentifier(c);
                        if (!id) continue;
                        try {
                          await api.put(`/v1/clients/${encodeURIComponent(id)}`, {
                            node_id: c.node_id, inbound_id: c.inbound_id,
                            updates: { email: c.email, expiryTime: now, enable: false },
                          }, { auth: getAuth() });
                          done++;
                        } catch { /* continue */ }
                      }
                      toast(`Frozen ${done} clients`, 'warning');
                      loadClients(true);
                    }}>
                    🧊 Freeze Selected
                  </button>
                  <button className="btn btn-sm btn-neutral"
                    title="Export selected clients as CSV"
                    onClick={() => {
                      const selected = filteredClients.filter(c => selectedClientKeys.has(clientKey(c)));
                      const headers = ['Email', 'Node', 'Protocol', 'Status', 'Download (GB)', 'Total (GB)', 'Expiry'];
                      const rows = selected.map(c => [
                        c.email, c.node_name, c.protocol, c.enable ? 'Active' : 'Disabled',
                        (c.down / 1073741824).toFixed(2),
                        c.total > 0 ? (c.total / 1073741824).toFixed(2) : 'Unlimited',
                        c.expiryTime > 0 ? new Date(c.expiryTime).toLocaleDateString() : 'Never',
                      ]);
                      const csv = [headers, ...rows].map(r => r.join(',')).join('\n');
                      const blob = new Blob([csv], { type: 'text/csv' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a'); a.href = url;
                      a.download = `selected_clients_${new Date().toISOString().slice(0,10)}.csv`;
                      a.click(); URL.revokeObjectURL(url);
                      toast(`Exported ${selected.length} clients`, 'success');
                    }}>
                    <UIIcon name="download" size={13} /> Export CSV
                  </button>
                  <button className="btn btn-sm btn-neutral"
                    title="Download subscription links for all selected clients"
                    onClick={async () => {
                      const selected = filteredClients.filter(c => selectedClientKeys.has(clientKey(c)));
                      const lines: string[] = [];
                      for (const c of selected) {
                        try {
                          const res = await api.get(`/v1/clients/${encodeURIComponent(c.email)}/links`, { auth: getAuth() });
                          const links: string[] = res.data?.links || [];
                          if (links.length > 0) {
                            lines.push(`# ${c.email}`);
                            lines.push(...links);
                            lines.push('');
                          }
                        } catch { /* skip */ }
                      }
                      if (lines.length === 0) { toast('No links found', 'warning'); return; }
                      const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = `links_${new Date().toISOString().slice(0,10)}.txt`;
                      a.click();
                      URL.revokeObjectURL(url);
                    }}>
                    <UIIcon name="download" size={13} /> Export Links
                  </button>
                  <button className="btn btn-sm btn-neutral"
                    onClick={async () => {
                      const selectedEmails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      const nodeMap = new Map<string, number>();
                      clients.filter(c => selectedClientKeys.has(clientKey(c))).forEach(c => { if (c.node_id) nodeMap.set(c.node_name, c.node_id); });
                      const nodeEntries = Array.from(nodeMap.entries());
                      if (nodeEntries.length === 0) { toast('No node found for selected clients', 'warning'); return; }
                      // Use first node's groups
                      const [nodeName, nodeId] = nodeEntries[0];
                      try {
                        const res = await api.get(`/v1/nodes/${nodeId}/client-groups`, { auth: getAuth() });
                        const groups: string[] = res.data?.groups ?? res.data ?? [];
                        if (groups.length === 0) { toast(`No groups on node "${nodeName}". Create one first in Groups manager.`, 'warning'); return; }
                        const choice = window.prompt(`Add ${selectedEmails.length} clients to group on "${nodeName}":\n\n${groups.map((g, i) => `${i+1}. ${g}`).join('\n')}\n\nEnter group name or number:`);
                        if (!choice) return;
                        const groupName = groups[parseInt(choice) - 1] || choice;
                        await api.post(`/v1/nodes/${nodeId}/client-groups/${encodeURIComponent(groupName)}/add`, { emails: selectedEmails }, { auth: getAuth() });
                        toast(`Added ${selectedEmails.length} clients to "${groupName}"`, 'success');
                      } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                    }}>
                    <UIIcon name="group" size={13} /> Add to Group
                  </button>
                </div>
              )}
              <div className="d-flex gap-2 mb-2 flex-wrap align-items-center">
                <span className="small text-muted-2">Quick select:</span>
                <button className="btn btn-sm btn-ghost-danger" style={{ fontSize: '0.75rem' }}
                  onClick={() => selectAllBy(c => c.expiryTime > 0 && c.expiryTime < Date.now())}>
                  + All Expired
                </button>
                <button className="btn btn-sm btn-ghost-warning" style={{ fontSize: '0.75rem' }}
                  onClick={() => selectAllBy(c => c.total > 0 && c.up + c.down >= c.total)}>
                  + All Depleted
                </button>
                <button className="btn btn-sm btn-neutral" style={{ fontSize: '0.75rem' }}
                  onClick={() => selectAllBy(c => !c.enable)}>
                  + All Disabled
                </button>
                <button className="btn btn-sm btn-neutral" style={{ fontSize: '0.75rem' }}
                  onClick={() => setSelectedClientKeys(new Set())}>
                  Clear selection
                </button>
              </div>
              <div className="panel-inline-actions">
                <button
                  className="btn btn-sm btn-warning-fill"
                  onClick={() => handleBatchDelete('expired')}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />{t('clients.deleteExpired')}</span>
                </button>
                <button
                  className="btn btn-sm btn-warning-fill"
                  onClick={() => handleBatchDelete('depleted')}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />{t('clients.deleteDepleted')}</span>
                </button>
                <button
                  className="btn btn-sm btn-info-fill"
                  onClick={() => handleResetTraffic(null)}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="refresh" size={14} />{t('clients.resetAllTraffic')}</span>
                </button>
                <button
                  className="btn btn-sm btn-danger-fill"
                  onClick={handleDelDepleted}
                  disabled={delDepletedLoading}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="trash" size={14} />{t('messages.delDepleted')}</span>
                </button>
                <button
                  className="btn btn-sm btn-warning-fill"
                  title="Reset traffic for all depleted clients"
                  onClick={async () => {
                    const depleted = clients.filter(c => c.total > 0 && c.up + c.down >= c.total);
                    if (depleted.length === 0) { toast('No depleted clients', 'info'); return; }
                    if (!window.confirm(`Reset traffic for ${depleted.length} depleted clients?`)) return;
                    const { user, password } = getAuth();
                    try {
                      const res = await api.post('/v1/clients/bulk-reset-traffic', {
                        emails: depleted.map(c => c.email),
                      }, { auth: { username: user, password } });
                      toast(`Reset: ${res.data?.successful ?? depleted.length} clients`, 'success');
                      loadClients(true);
                    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                  }}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="refresh" size={14} /> Reset Depleted</span>
                </button>
                <button
                  className="btn btn-sm btn-info-fill"
                  title="Renew all expired clients — prompts for number of days"
                  onClick={async () => {
                    const expired = clients.filter(c => c.expiryTime > 0 && c.expiryTime < Date.now());
                    if (expired.length === 0) { toast('No expired clients found', 'info'); return; }
                    const input = window.prompt(`Renew ${expired.length} expired clients. Add how many days?`, '30');
                    const days = parseInt(input || '') || 0;
                    if (!days) return;
                    const { user, password } = getAuth();
                    try {
                      const res = await api.post('/v1/clients/bulk-adjust', {
                        emails: expired.map(c => c.email),
                        add_days: days,
                        add_bytes: 0,
                      }, { auth: { username: user, password } });
                      toast(`Renewed ${res.data?.total_adjusted ?? expired.length} clients (+${days} days)`, 'success');
                      loadClients(true);
                    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                  }}
                >
                  <span className="d-inline-flex align-items-center gap-1">⟳ Renew Expired</span>
                </button>
                <button
                  className="btn btn-sm btn-ghost-warning"
                  title={`Extend all clients expiring within ${expiringSoonDays} days`}
                  onClick={async () => {
                    const now = Date.now();
                    const expiring = clients.filter(c => c.expiryTime > now && c.expiryTime < now + expiringSoonDays * 86400000);
                    if (expiring.length === 0) { toast(`No clients expiring within ${expiringSoonDays}d`, 'info'); return; }
                    const input = window.prompt(`Extend ${expiring.length} clients expiring within ${expiringSoonDays}d. Add how many days?`, '30');
                    const days = parseInt(input || '') || 0;
                    if (!days) return;
                    const { user, password } = getAuth();
                    try {
                      const res = await api.post('/v1/clients/bulk-adjust', {
                        emails: expiring.map(c => c.email), add_days: days, add_bytes: 0,
                      }, { auth: { username: user, password } });
                      toast(`Extended ${res.data?.successful ?? expiring.length} clients by ${days}d`, 'success');
                      loadClients(true);
                    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                  }}
                >
                  ⏱ Extend Expiring
                </button>
                <button
                  className="btn btn-sm btn-accent"
                  onClick={() => setShowBulkAdjust(true)}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="edit" size={14} />{t('messages.bulkAdjustTitle')}</span>
                </button>
                <button
                  className="btn btn-sm btn-neutral"
                  onClick={() => {
                    const nodeMap = new Map<string, number>();
                    clients.forEach(c => { if (c.node_id) nodeMap.set(c.node_name, c.node_id); });
                    const entries = Array.from(nodeMap.entries());
                    if (entries.length === 1) {
                      handleOpenGroups(entries[0][1], entries[0][0]);
                    } else {
                      setShowGroupsModal(true);
                      setGroupsNodeId(null);
                      setGroupsNodeName('');
                      setGroupsList([]);
                    }
                  }}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="group" size={13} /> Groups</span>
                </button>
                <button
                  className={`btn btn-sm ${denseView ? 'btn-accent' : 'btn-neutral'}`}
                  title="Toggle compact/dense table view"
                  onClick={() => setDenseView(v => !v)}
                >
                  <span className="d-inline-flex align-items-center gap-1">⚏ Dense</span>
                </button>
                <button
                  className="btn btn-sm btn-neutral"
                  title="Find clients by IP address"
                  onClick={() => { setIpSearchValue(''); setIpSearchResults([]); setShowIpSearch(true); }}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="search" size={13} /> Find by IP</span>
                </button>
                <button
                  className="btn btn-sm btn-neutral"
                  title="Copy all visible email addresses to clipboard"
                  onClick={() => {
                    const emails = filteredClients.map(c => c.email).join('\n');
                    navigator.clipboard.writeText(emails).then(() => toast(`Copied ${filteredClients.length} emails`, 'info'));
                  }}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="copy" size={13} /> Copy Emails</span>
                </button>
                <button
                  className="btn btn-sm btn-neutral"
                  title="Export visible clients as JSON"
                  onClick={() => {
                    const data = filteredClients.map(c => ({
                      email: c.email, protocol: c.protocol, node: c.node_name,
                      enable: c.enable, totalGB: c.total > 0 ? (c.total / 1024**3).toFixed(2) : null,
                      expiryTime: c.expiryTime > 0 ? new Date(c.expiryTime).toISOString() : null,
                    }));
                    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `clients_${new Date().toISOString().slice(0,10)}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="download" size={13} /> JSON</span>
                </button>
                <button
                  className="btn btn-sm btn-neutral"
                  title="Export visible clients as CSV"
                  onClick={() => {
                    const rows = filteredClients.map(c => {
                      const exp = c.expiryTime > 0 ? new Date(c.expiryTime).toISOString().slice(0,10) : '';
                      const usedGB = ((c.up + c.down) / (1024**3)).toFixed(2);
                      const totalGB = c.total > 0 ? (c.total / (1024**3)).toFixed(2) : '';
                      return [c.email, c.node_name, c.protocol, c.enable ? 'enabled' : 'disabled', usedGB, totalGB, exp]
                        .map(v => `"${String(v).replace(/"/g, '""')}"`).join(',');
                    });
                    const csv = ['email,node,protocol,status,used_gb,total_gb,expiry', ...rows].join('\n');
                    const blob = new Blob([csv], { type: 'text/csv' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `clients_${new Date().toISOString().slice(0,10)}.csv`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  <span className="d-inline-flex align-items-center gap-1"><UIIcon name="download" size={13} /> CSV</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      {/* Stats bar */}
      {clients.length > 0 && (() => {
        const now = Date.now();
        const active = clients.filter(c => c.enable && !(c.expiryTime > 0 && c.expiryTime < now) && !(c.total > 0 && c.up + c.down >= c.total)).length;
        const expired = clients.filter(c => c.expiryTime > 0 && c.expiryTime < now).length;
        const depleted = clients.filter(c => c.total > 0 && c.up + c.down >= c.total).length;
        const disabled = clients.filter(c => !c.enable).length;
        const online = onlineEmails.size;
        return (
          <div className="d-flex flex-wrap gap-2 mb-2">
            {[
              { label: 'Total',    value: clients.length, cls: '',          status: '' },
              { label: 'Active',   value: `${active} (${clients.length ? Math.round(active / clients.length * 100) : 0}%)`, cls: 'text-success', status: 'active' },
              { label: 'Online',   value: `${online} (${active ? Math.round(online / active * 100) : 0}%)`, cls: 'text-accent',  status: 'online' },
              { label: 'Expired',  value: expired,  cls: 'text-danger',  status: 'expired' },
              { label: 'Depleted', value: depleted, cls: 'text-warning', status: 'depleted' },
              { label: 'Disabled', value: disabled, cls: 'text-muted',   status: 'disabled' },
            ].map(s => (
              <span key={s.label}
                className={`badge px-2 py-1 ${s.cls} ${s.status && filterStatus === s.status ? 'badge--active' : ''}`}
                style={{
                  backgroundColor: filterStatus === s.status && s.status ? 'color-mix(in srgb, currentColor 18%, transparent)' : 'var(--bg-tertiary)',
                  fontWeight: 400, fontSize: '0.78rem',
                  cursor: s.status ? 'pointer' : 'default',
                  border: filterStatus === s.status && s.status ? '1px solid currentColor' : '1px solid transparent',
                }}
                title={s.status ? (filterStatus === s.status ? 'Click to clear filter' : `Click to filter by ${s.label}`) : undefined}
                onClick={() => s.status && setFilterStatus(prev => prev === s.status ? '' : s.status)}
              >
                {s.label}: <strong>{s.value}</strong>
              </span>
            ))}
          </div>
        );
      })()}

      {/* Pagination controls */}
      {filteredClients.length > pageSize && (
        <div className="pg-strip pg-strip--bar mb-2">
          <span className="pg-strip__info">
            Page {currentPage} of {Math.ceil(filteredClients.length / pageSize)}
            {' '}({(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, filteredClients.length)} of {filteredClients.length})
          </span>
          <div className="d-flex gap-1">
            <button className="btn btn-sm btn-neutral" disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}>«</button>
            <button className="btn btn-sm btn-neutral" disabled={currentPage <= 1} onClick={() => setCurrentPage(p => p - 1)}>‹</button>
            <button className="btn btn-sm btn-neutral" disabled={currentPage >= Math.ceil(filteredClients.length / pageSize)} onClick={() => setCurrentPage(p => p + 1)}>›</button>
            <button className="btn btn-sm btn-neutral" disabled={currentPage >= Math.ceil(filteredClients.length / pageSize)} onClick={() => setCurrentPage(Math.ceil(filteredClients.length / pageSize))}>»</button>
          </div>
          <button className="btn btn-sm btn-neutral" style={{ fontSize: '0.72rem' }}
            title="Add all clients on this page to selection"
            onClick={() => {
              const pageClients = filteredClients.slice((currentPage - 1) * pageSize, currentPage * pageSize);
              setSelectedClientKeys(prev => {
                const next = new Set(prev);
                pageClients.forEach(c => next.add(clientKey(c)));
                return next;
              });
            }}>
            ☑ Select page
          </button>
          <select className="form-select form-select-sm form-select-inline"
            value={currentPage} onChange={e => setCurrentPage(Number(e.target.value))}>
            {Array.from({ length: Math.ceil(filteredClients.length / pageSize) }, (_, i) => (
              <option key={i + 1} value={i + 1}>Page {i + 1}</option>
            ))}
          </select>
          <select className="form-select form-select-sm form-select-inline"
            value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(1); }}
            title="Rows per page">
            {[25, 50, 100, 200, 500].map(n => <option key={n} value={n}>{n} / page</option>)}
          </select>
        </div>
      )}

      {/* Client Table */}
      <div className="card p-3">
        {loading && filteredClients.length > 0 && (
          <div className="table-loading-bar mb-1" />
        )}
        {loading && filteredClients.length === 0 && (
          <div className="table-responsive">
            <table className="skeleton-table">
              <tbody>
                {Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td style={{ width: 36 }}><div className="skeleton-cell skeleton-cell--circle" /></td>
                    <td style={{ width: '28%' }}><div className="skeleton-cell skeleton-cell--xl" /></td>
                    <td style={{ width: '14%' }}><div className="skeleton-cell skeleton-cell--md" /></td>
                    <td style={{ width: '8%' }}><div className="skeleton-cell skeleton-cell--sm" /></td>
                    <td style={{ width: '10%' }}><div className="skeleton-cell skeleton-cell--badge" /></td>
                    <td style={{ width: '12%' }}><div className="skeleton-cell skeleton-cell--md" /></td>
                    <td style={{ width: '10%' }}><div className="skeleton-cell skeleton-cell--sm" /></td>
                    <td style={{ width: '12%' }}><div className="skeleton-cell skeleton-cell--md" /></td>
                    <td style={{ width: '6%' }}><div className="skeleton-cell skeleton-cell--xs" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!loading && trafficLoading && (
          <div className="d-flex align-items-center gap-2 py-1 px-1" style={{ color: 'var(--text-tertiary)', fontSize: '0.73rem' }}>
            <div className="spinner-border spinner-border-sm spinner-accent" style={{ width: '10px', height: '10px', borderWidth: '0.12em' }} />
            {t('clients.loadingTraffic')}
          </div>
        )}
        
        {!loading && filteredClients.length === 0 && clients.length === 0 && (
          <EmptyState
            icon="👤"
            title={t('clients.noClientsFound')}
            hint="Add clients to your inbounds on the Inbounds tab, or use Batch Add below."
            action={{ label: '+ Batch Add', onClick: () => setShowBatchModal(true) }}
          />
        )}
        {!loading && filteredClients.length === 0 && clients.length > 0 && (
          <EmptyState
            icon="⊘"
            title="No clients match your filters"
            hint="Try clearing the search or changing filter options."
          />
        )}
        
        {filteredClients.length > 0 && (
          <div className="table-responsive">
            <table className={`table table-hover${denseView ? ' table-sm' : ''}`} style={{ fontSize: denseView ? '0.8rem' : undefined }}>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      checked={
                        filteredClients.length > 0 &&
                        filteredClients.every((c) => selectedClientKeys.has(clientKey(c)))
                      }
                      onChange={toggleSelectAll}
                    />
                  </th>
                  <th>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" onClick={() => applySortFromHeader('email')}>
                      {t('clients.email')}{sortIndicator('email')}
                    </button>
                  </th>
                  <th>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" onClick={() => applySortFromHeader('node')}>
                      {t('traffic.node')}{sortIndicator('node')}
                    </button>
                  </th>
                  {!denseView && <th className="col-hide-mobile">{t('inbounds.protocol')}</th>}
                  <th>{t('common.status')}</th>
                  <th>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" onClick={() => applySortFromHeader('download')}>
                      {t('traffic.download')}{sortIndicator('download')}
                    </button>
                    {' / '}
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ fontSize: '0.72rem' }} onClick={() => applySortFromHeader('usedPct')}
                      title="Sort by % of traffic used">
                      %{sortIndicator('usedPct')}
                    </button>
                  </th>
                  <th className="col-hide-md">
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" onClick={() => applySortFromHeader('total')}>
                      {t('clients.totalLimit')}{sortIndicator('total')}
                    </button>
                  </th>
                  <th>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" onClick={() => applySortFromHeader('expiry')}>
                      {t('clients.expiryTime')}{sortIndicator('expiry')}
                    </button>
                  </th>
                  {!denseView && (
                    <th className="col-hide-md">
                      <button className="btn btn-link btn-sm p-0 text-decoration-none" onClick={() => applySortFromHeader('lastOnline')}>
                        Last Online{sortIndicator('lastOnline')}
                      </button>
                    </th>
                  )}
                  <th className="col-hide-md" style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('health')}
                      title="Sort by client health score">
                      Health{sortIndicator('health')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredClients.slice((currentPage - 1) * pageSize, currentPage * pageSize).map((client) => {
                  const trafficKey = client.node_id != null ? `${client.node_id}:${client.email}` : null;
                  const downloadBytes = getTrafficBytes(trafficKey, 'download', client.down);
                  const isExpired = client.expiryTime > 0 && client.expiryTime < Date.now();
                  const isDepleted = client.total > 0 && (client.up + client.down) >= client.total;
                  const now = Date.now();
                  const isExpiringSoon = !isExpired && client.expiryTime > 0 && client.expiryTime < now + expiringSoonDays * 86400_000;
                  const rowBg = isExpired ? 'color-mix(in srgb, var(--danger) 8%, transparent)'
                    : isDepleted ? 'color-mix(in srgb, var(--warning) 8%, transparent)'
                    : isExpiringSoon ? 'color-mix(in srgb, var(--warning) 5%, transparent)'
                    : !client.enable ? 'color-mix(in srgb, var(--bg-tertiary) 50%, transparent)'
                    : 'transparent';

                  return (
                    <React.Fragment key={clientKey(client)}>
                    <tr style={{ borderColor: 'var(--border-color)', backgroundColor: rowBg }}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedClientKeys.has(clientKey(client))}
                          onChange={() => toggleSelection(client)}
                        />
                      </td>
                      <td>
                        <div className="d-flex align-items-center gap-1">
                          {onlineEmails.has(client.email) && (
                            <span style={{ color: 'var(--success)', fontSize: '0.7rem' }} title="Online">●</span>
                          )}
                          <strong
                            style={{ color: 'var(--text-primary)', cursor: 'pointer' }}
                            title="Click to expand details | Double-click to copy email"
                            onClick={() => setExpandedKey(prev => prev === clientKey(client) ? null : clientKey(client))}
                            onDoubleClick={e => { e.stopPropagation(); navigator.clipboard.writeText(client.email).then(() => toast('Email copied', 'info')); }}
                          >
                            {expandedKey === clientKey(client) ? '▾' : '▸'} {client.email}
                          </strong>
                          {(client as any).subId && (
                            <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginLeft: '2px' }} title="Has subscription link">🔗</span>
                          )}
                          <button
                            className="btn btn-sm p-0 ms-1"
                            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', opacity: 0.6 }}
                            title="Copy subscription links"
                            onClick={async () => {
                              const { user, password } = getAuth();
                              try {
                                const res = await api.get(`/v1/clients/${encodeURIComponent(client.email)}/links`, { auth: { username: user, password } });
                                const links: string[] = res.data?.links || [];
                                if (links.length > 0) {
                                  await navigator.clipboard.writeText(links.join('\n'));
                                  toast(`Copied ${links.length} link(s)`, 'info');
                                } else {
                                  toast('No links available (requires v3 panel)', 'warning');
                                }
                              } catch (e) { console.error(e); }
                            }}
                          >
                            <UIIcon name="link" size={12} />
                          </button>
                          <button
                            className="btn btn-sm p-0 ms-1"
                            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', opacity: 0.6 }}
                            title="Show QR codes"
                            onClick={async () => {
                              const { user, password } = getAuth();
                              try {
                                const res = await api.get(`/v1/clients/${encodeURIComponent(client.email)}/links`, { auth: { username: user, password } });
                                const links: string[] = res.data?.links || [];
                                if (links.length > 0) {
                                  setQrLinks(links);
                                  setQrEmail(client.email);
                                  setShowQrModal(true);
                                } else {
                                  toast('No links available (requires v3 panel)', 'warning');
                                }
                              } catch (e) { console.error(e); }
                            }}
                          >
                            ▦
                          </button>
                        </div>
                      </td>
                      <td>
                        <span
                          className={`client-node-chip${filterNode === client.node_name ? ' is-active' : ''}`}
                          title={filterNode === client.node_name ? 'Click to clear node filter' : `Filter by ${client.node_name}`}
                          onClick={() => setFilterNode(prev => prev === client.node_name ? '' : client.node_name)}
                        >
                          {client.node_name}
                        </span>
                      </td>
                      {!denseView && (
                        <td className="col-hide-mobile">
                          <span
                            className={`client-node-chip client-node-chip--proto${filterProtocol === client.protocol ? ' is-active' : ''}`}
                            title={filterProtocol === client.protocol ? 'Click to clear protocol filter' : `Filter by ${client.protocol}`}
                            onClick={() => setFilterProtocol(prev => prev === client.protocol ? '' : client.protocol)}
                          >
                            {client.protocol.toUpperCase()}
                          </span>
                        </td>
                      )}
                      <td>
                        <button
                          className={`client-status-dot client-status-dot--${isExpired ? 'expired' : isDepleted ? 'depleted' : client.enable ? 'active' : 'disabled'}`}
                          title={`${isExpired ? 'Expired' : isDepleted ? 'Depleted' : client.enable ? 'Active — click to disable' : 'Disabled — click to enable'}`}
                          onClick={async () => {
                            const identifier = clientIdentifier(client);
                            if (!identifier) return;
                            try {
                              await api.put(`/v1/clients/${encodeURIComponent(identifier)}`, {
                                node_id: client.node_id,
                                inbound_id: client.inbound_id,
                                updates: { email: client.email, enable: !client.enable },
                              }, { auth: getAuth() });
                              setClients(prev => prev.map(c =>
                                clientKey(c) === clientKey(client) ? { ...c, enable: !c.enable } : c
                              ));
                            } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                          }}
                        >
                        
                        </button>
                      </td>
                      <td>
                        <div>
                          {formatBytes(downloadBytes)}
                          {client.total > 0 && (() => {
                            const used = client.up + client.down;
                            const pct = Math.min(100, (used / client.total) * 100);
                            const barColor = pct >= 90 ? 'var(--danger)' : pct >= 70 ? 'var(--warning)' : 'var(--success)';
                            return (
                              <>
                                <div className="progress mt-1" style={{ height: '3px', backgroundColor: 'var(--bg-tertiary)', minWidth: '60px' }}>
                                  <div className="progress-bar" style={{ width: `${pct}%`, backgroundColor: barColor }} />
                                </div>
                                <div style={{ fontSize: '0.65rem', color: barColor, marginTop: '1px' }}>
                                  {(used / 1073741824).toFixed(1)}/{(client.total / 1073741824).toFixed(1)} GB
                                </div>
                              </>
                            );
                          })()}
                        </div>
                      </td>
                      <td className="col-hide-md">
                        <span
                          style={{ cursor: 'pointer', color: client.total > 0 ? 'var(--text-primary)' : 'var(--text-secondary)' }}
                          title="Click to set traffic limit (GB)"
                          onClick={async () => {
                            const identifier = clientIdentifier(client);
                            if (!identifier) return;
                            const current = client.total > 0 ? (client.total / 1073741824).toFixed(1) : '0';
                            const input = window.prompt(`Set traffic limit (GB) for "${client.email}":\n0 = unlimited`, current);
                            if (input === null) return;
                            const gb = parseFloat(input);
                            if (isNaN(gb) || gb < 0) return;
                            try {
                              await api.put(`/v1/clients/${encodeURIComponent(identifier)}`, {
                                node_id: client.node_id, inbound_id: client.inbound_id,
                                updates: { email: client.email, totalGB: gb },
                              }, { auth: getAuth() });
                              toast(`Limit set: ${gb > 0 ? gb + ' GB' : 'unlimited'} → ${client.email}`, 'success');
                              loadClients(true);
                            } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                          }}
                        >
                          {client.total > 0 ? formatBytes(client.total) : '∞'}
                        </span>
                      </td>
                      <td>
                        <div
                          style={{ cursor: 'pointer' }}
                          title="Click to set expiry date"
                          onClick={async () => {
                            const identifier = clientIdentifier(client);
                            if (!identifier) return;
                            const current = client.expiryTime > 0 ? new Date(client.expiryTime).toISOString().slice(0,10) : '';
                            const input = window.prompt(`Set expiry date for "${client.email}" (YYYY-MM-DD, blank = never):`, current);
                            if (input === null) return;
                            const ts = input.trim() ? new Date(input.trim()).getTime() : 0;
                            if (input.trim() && isNaN(ts)) { toast('Invalid date format', 'warning'); return; }
                            try {
                              await api.put(`/v1/clients/${encodeURIComponent(identifier)}`, {
                                node_id: client.node_id, inbound_id: client.inbound_id,
                                updates: { email: client.email, expiryTime: ts },
                              }, { auth: getAuth() });
                              toast(`Expiry set → ${client.email}`, 'success');
                              loadClients(true);
                            } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                          }}
                        >
                          {client.expiryTime > 0 ? (() => {
                            const daysLeft = Math.ceil((client.expiryTime - Date.now()) / 86400000);
                            const urgency = isExpired ? 'expired' : daysLeft <= 3 ? 'urgent' : daysLeft <= 7 ? 'soon' : 'ok';
                            return (
                              <div className={`expiry-chip expiry-chip--${urgency}`}>
                                <span className="expiry-chip__date">{new Date(client.expiryTime).toLocaleDateString()}</span>
                                {!isExpired && <span className="expiry-chip__days">{daysLeft}d left</span>}
                              </div>
                            );
                          })() : (
                            <span className="expiry-chip expiry-chip--never">{t('clients.never')}</span>
                          )}
                        </div>
                      </td>
                      {!denseView && (
                        <td className="col-hide-md">
                          {lastOnlineMap[client.email] ? (
                            <small style={{ color: 'var(--text-secondary)' }}>
                              {new Date(lastOnlineMap[client.email]).toLocaleDateString()}
                            </small>
                          ) : (
                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>—</span>
                          )}
                        </td>
                      )}
                      <td className="col-hide-md">
                        {(() => {
                          const hs = getHealthScore(client);
                          const hColor = hs >= 70 ? 'var(--success)' : hs >= 35 ? 'var(--warning)' : 'var(--danger)';
                          const hLabel = hs >= 70 ? '●' : hs >= 35 ? '◑' : '○';
                          return (
                            <span title={`Health score: ${hs}/100`} style={{ color: hColor, fontWeight: 600, fontSize: '0.8rem', cursor: 'default' }}>
                              {hLabel} {hs}
                            </span>
                          );
                        })()}
                      </td>
                      <td>
                        <div className="d-inline-flex gap-1 align-items-center">
                          <button className="row-action-btn row-action-btn--accent"
                            onClick={() => handleClientEditClick(client)}
                            title={t('messages.editClient')}
                            aria-label={t('messages.editClient')}>
                            <UIIcon name="edit" size={13} />
                          </button>
                          <button className="row-action-btn row-action-btn--info"
                            onClick={() => handleResetTraffic(client)}
                            title={t('clients.resetTraffic')}
                            aria-label={t('clients.resetTraffic')}>
                            <UIIcon name="refresh" size={13} />
                          </button>
                          <button className="row-action-btn row-action-btn--success"
                            title="Renew: add days to expiry"
                            aria-label="Renew: add days to expiry"
                            onClick={async () => {
                              const identifier = clientIdentifier(client);
                              if (!identifier) return;
                              const daysStr = window.prompt(`Add days to "${client.email}" (current expiry: ${client.expiryTime > 0 ? new Date(client.expiryTime).toLocaleDateString() : 'never'}):`, '30');
                              const days = parseInt(daysStr || '');
                              if (!days || days <= 0) return;
                              const baseTime = client.expiryTime > 0 ? client.expiryTime : Date.now();
                              const newExpiry = baseTime + days * 86400000;
                              try {
                                await api.put(`/v1/clients/${encodeURIComponent(identifier)}`, {
                                  node_id: client.node_id, inbound_id: client.inbound_id,
                                  updates: { email: client.email, expiryTime: newExpiry, enable: true },
                                }, { auth: getAuth() });
                                toast(`+${days}d → ${client.email}`, 'success');
                                loadClients(true);
                              } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                            }}>
                            +d
                          </button>
                          <button className="row-action-btn row-action-btn--warning"
                            title="Freeze: set expiry to now"
                            aria-label="Freeze client"
                            onClick={async () => {
                              if (!window.confirm(`Freeze "${client.email}"? This sets expiry to now.`)) return;
                              const identifier = clientIdentifier(client);
                              if (!identifier) return;
                              try {
                                await api.put(`/v1/clients/${encodeURIComponent(identifier)}`, {
                                  node_id: client.node_id, inbound_id: client.inbound_id,
                                  updates: { email: client.email, expiryTime: Date.now(), enable: false },
                                }, { auth: getAuth() });
                                toast(`Frozen: ${client.email}`, 'warning');
                                loadClients(true);
                              } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                            }}>
                            <UIIcon name="snowflake" size={13} />
                          </button>
                          <button className="row-action-btn row-action-btn--info"
                            title="View active IPs"
                            aria-label="View active IPs"
                            onClick={async () => {
                              const { user, password } = getAuth();
                              try {
                                const res = await api.get(`/v1/clients/${encodeURIComponent(client.email)}/ips`, { auth: { username: user, password } });
                                const results = res.data?.results || [];
                                const all = results.flatMap((r: any) => (r.ips || []).map((ip: string) => `${r.node}: ${ip}`));
                                const lo = lastOnlineMap[client.email];
                                const loStr = lo ? `\nLast online: ${new Date(lo).toLocaleString()}` : '';
                                toast(all.length > 0 ? `IPs: ${all.join(', ')}${loStr}` : `No active IPs${loStr}`, 'info');
                              } catch (e) { console.error(e); }
                            }}>
                            IP
                          </button>
                          <button className="row-action-btn row-action-btn--warning"
                            title="Clear stored IPs"
                            aria-label="Clear stored IPs"
                            onClick={async () => {
                              if (!window.confirm(`Clear stored IPs for "${client.email}"?`)) return;
                              try {
                                await api.post(`/v1/clients/${encodeURIComponent(client.email)}/clear-ips`, {}, { auth: getAuth() });
                                toast('IPs cleared', 'success');
                              } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                            }}>
                            ✕IP
                          </button>
                          <button className="row-action-btn row-action-btn--info"
                            title="Attach/Detach inbounds"
                            aria-label="Attach or detach inbounds"
                            onClick={() => handleOpenAttach(client, 'attach')}>
                            <UIIcon name="attach" size={13} />
                          </button>
                          <button className="row-action-btn row-action-btn--accent"
                            title="Duplicate client"
                            aria-label="Duplicate client"
                            onClick={() => {
                              setBatchText(`${client.email}_copy`);
                              if (client.inbound_id) setBatchInboundId(client.inbound_id.toString());
                              setShowBatchModal(true);
                            }}>
                            <UIIcon name="duplicate" size={13} />
                          </button>
                          <button className={`row-action-btn ${clientNotes[clientKey(client)] ? 'row-action-btn--accent' : ''}`}
                            title={clientNotes[clientKey(client)] ? `Note: ${clientNotes[clientKey(client)]}` : 'Add note (local only)'}
                            aria-label={clientNotes[clientKey(client)] ? 'Edit note' : 'Add note'}
                            onClick={() => {
                              const key = clientKey(client);
                              const note = window.prompt('Client note (stored locally):', clientNotes[key] || '');
                              if (note !== null) saveClientNote(key, note);
                            }}>
                            <UIIcon name="note" size={13} />
                          </button>
                          <button className="row-action-btn row-action-btn--danger"
                            title={t('clients.deleteClient') || 'Delete client'}
                            aria-label={t('clients.deleteClient') || 'Delete client'}
                            onClick={async () => {
                              const identifier = clientIdentifier(client);
                              if (!identifier || !client.inbound_id) { toast('Cannot identify client', 'warning'); return; }
                              if (!window.confirm(`Delete client "${client.email}"?`)) return;
                              try {
                                await api.delete(`/v1/clients/${encodeURIComponent(identifier)}`, {
                                  auth: getAuth(),
                                  params: { node_id: client.node_id, inbound_id: client.inbound_id },
                                });
                                loadClients(true);
                              } catch (e: any) { toast(e.response?.data?.detail || 'Delete failed', 'error'); }
                            }}>
                            <UIIcon name="trash" size={13} />
                          </button>
                        </div>
                        {lastOnlineMap[client.email] && !onlineEmails.has(client.email) && (
                          <div className="small mt-1" style={{ color: 'var(--text-secondary)', fontSize: '0.68rem' }}>
                            {new Date(lastOnlineMap[client.email]).toLocaleDateString()}
                          </div>
                        )}
                      </td>
                    </tr>
                    {expandedKey === clientKey(client) && (
                      <tr className="row-detail row-detail--open" style={{ backgroundColor: 'color-mix(in srgb, var(--bg-tertiary) 40%, transparent)' }}>
                        <td colSpan={99} style={{ padding: '8px 16px', fontSize: '0.78rem' }}>
                          <div className="d-flex flex-wrap gap-3 align-items-start">
                            <div className="d-flex flex-wrap gap-3">
                                <span className="d-inline-flex align-items-center gap-1">
                                <strong>Email:</strong>
                                <span style={{ color: 'var(--text-primary)' }}>{client.email}</span>
                                <button className="row-action-btn"
                                  title="Copy email"
                                  aria-label="Copy email address"
                                  style={{ fontSize: '0.75rem' }}
                                  onClick={() => copyWithFeedback(client.email, `email-${clientKey(client)}`, 'Email copied')}>
                                  {copiedKey === `email-${clientKey(client)}` ? <UIIcon name="check" size={12} /> : <UIIcon name="copy" size={12} />}
                                </button>
                              </span>
                            {clientNotes[clientKey(client)] && (
                              <span className="d-inline-flex align-items-center gap-1 text-accent">
                                <strong>📝 Note:</strong>
                                <span>{clientNotes[clientKey(client)]}</span>
                                <button className="btn btn-sm p-0" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: '0.7rem' }}
                                  title="Clear note"
                                  onClick={() => saveClientNote(clientKey(client), '')}>✕</button>
                              </span>
                            )}
                            {client.inbound_id && <span><strong>Inbound:</strong> #{client.inbound_id}</span>}
                              {client.node_id && <span><strong>Node ID:</strong> {client.node_id}</span>}
                              {client.protocol && <span><strong>Protocol:</strong> {client.protocol}</span>}
                              {(client as any).id && (
                                <span className="d-inline-flex align-items-center gap-1">
                                  <strong>UUID:</strong>
                                  <code style={{ fontSize: '0.72rem' }}>{(client as any).id}</code>
                                  <button className="btn btn-sm p-0" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
                                    title="Copy UUID"
                                    onClick={() => navigator.clipboard.writeText((client as any).id).then(() => toast('UUID copied', 'info'))}>
                                    <UIIcon name="copy" size={12} />
                                  </button>
                                </span>
                              )}
                              {(client as any).subId && (
                                <span className="d-inline-flex align-items-center gap-1">
                                  <strong>Sub ID:</strong>
                                  <code style={{ fontSize: '0.72rem' }}>{(client as any).subId}</code>
                                  <button className="btn btn-sm p-0" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)' }}
                                    title="Copy subscription URL"
                                    onClick={() => {
                                      const url = `${window.location.origin}/sub/${(client as any).subId}`;
                                      navigator.clipboard.writeText(url).then(() => toast('Sub URL copied', 'info'));
                                    }}>
                                    🔗
                                  </button>
                                </span>
                              )}
                              {client.total > 0 && <span><strong>Limit:</strong> {(client.total / 1073741824).toFixed(1)} GB</span>}
                              {client.expiryTime > 0 && (() => {
                                const daysLeft = Math.ceil((client.expiryTime - Date.now()) / 86400000);
                                const color = daysLeft <= 0 ? 'var(--danger)' : daysLeft <= 3 ? 'var(--danger)' : daysLeft <= 7 ? 'var(--warning)' : 'var(--success)';
                                return (
                                  <span>
                                    <strong>Expires:</strong> {new Date(client.expiryTime).toLocaleDateString()}
                                    <span className="badge ms-1" style={{ backgroundColor: color, fontSize: '0.65rem' }}>
                                      {daysLeft <= 0 ? 'expired' : `${daysLeft}d`}
                                    </span>
                                  </span>
                                );
                              })()}
                              {(client as any).flow && <span><strong>Flow:</strong> {(client as any).flow}</span>}
                              {(client as any).tgId && <span><strong>Telegram:</strong> {(client as any).tgId}</span>}
                              {onlineEmails.has(client.email) && (
                                <span className="badge" style={{ backgroundColor: 'var(--success)', fontSize: '0.7rem' }}>● Online now</span>
                              )}
                              {lastOnlineMap[client.email] && !onlineEmails.has(client.email) && (
                                <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                                  Last seen: {new Date(lastOnlineMap[client.email]).toLocaleString()}
                                </span>
                              )}
                            </div>
                            {(client as any).subId && (
                              <img
                                src={`https://api.qrserver.com/v1/create-qr-code/?size=80x80&data=${encodeURIComponent(`${window.location.origin}/sub/${(client as any).subId}`)}`}
                                alt="QR"
                                style={{ width: 80, height: 80, borderRadius: 6, border: `1px solid ${'var(--border-color)'}` }}
                                title={`Subscription QR: ${(client as any).subId}`}
                              />
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        
        <div className="mt-2 small" style={{ color: 'var(--text-secondary)' }}>
          {t('clients.showingCount', { filtered: filteredClients.length, total: clients.length })}
        </div>
      </div>
      
      {/* Batch Add Modal */}
      {showBatchModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>{t('clients.batchAddTitle')}</h6>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => setShowBatchModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <div className="mb-3">
                  <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                    {t('clients.batchEmailsLabel')}
                  </label>
                  <textarea
                    className="form-control"
                    rows={8}
                    value={batchText}
                    onChange={(e) => setBatchText(e.target.value)}
                    placeholder="user1@example.com&#10;user2@example.com&#10;user3@example.com"
    
                  />
                </div>
                <div className="row g-2">
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                      {t('clients.inboundSelector')}
                    </label>
                    <ChoiceChips
                      options={[
                        { value: 'id', label: t('clients.inboundById') },
                        { value: 'remark', label: t('clients.inboundByRemark') },
                      ]}
                      value={batchInboundMode}
                      onChange={(value) => setBatchInboundMode(value)}
                      
                      size="md"
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                      {batchInboundMode === 'id' ? t('clients.inboundIdLabel') : t('clients.inboundRemarkLabel')}
                    </label>
                    {batchInboundMode === 'id' ? (
                      <input
                        type="number"
                        className="form-control"
                        value={batchInboundId}
                        onChange={(e) => setBatchInboundId(e.target.value)}
        
                      />
                    ) : (
                      <input
                        type="text"
                        className="form-control"
                        value={batchInboundRemark}
                        onChange={(e) => setBatchInboundRemark(e.target.value)}
                        placeholder={t('clients.inboundRemarkPlaceholder')}
        
                      />
                    )}
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
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
                      
                      size="md"
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                      {t('clients.totalGbOptional')}
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={batchTotalGB}
                      onChange={(e) => setBatchTotalGB(e.target.value)}
                      placeholder="50"
      
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                      {t('clients.expiryDaysOptional')}
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={batchExpiryDays}
                      onChange={(e) => setBatchExpiryDays(e.target.value)}
                      placeholder="30"
      
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
                      <label className="form-check-label small" htmlFor="batchEnableToggle" style={{ color: 'var(--text-secondary)' }}>
                        {t('clients.enableAfterAdd')}
                      </label>
                    </div>
                  </div>
                </div>
                {inboundOptions.length > 0 && (
                  <div className="mt-3 small" style={{ color: 'var(--text-secondary)', maxHeight: '120px', overflowY: 'auto' }}>
                    {t('clients.knownInbounds')}:
                    {inboundOptions.slice(0, 40).map((ib) => (
                      <div key={`${ib.node_name}:${ib.id}`}>
                        {ib.node_name} | id={ib.id} | {ib.protocol} | {ib.remark || '-'}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="modal-footer" style={{ borderColor: 'var(--border-color)' }}>
                <button
                  className="btn"
                  style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                  onClick={() => setShowBatchModal(false)}
                >
                  {t('common.cancel')}
                </button>
                <button
                  className="btn btn-accent"
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

      {/* Client Edit Modal */}
      {editingClient && (
        <ClientEditModal
          client={editingClient}
          onClose={() => setEditingClient(null)}
          onSaved={() => loadClients(true)}
        />
      )}

      {/* QR Code Modal */}
      {showQrModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }} onClick={(e) => { if (e.target === e.currentTarget) setShowQrModal(false); }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>▦ QR Codes — {qrEmail}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowQrModal(false)} />
              </div>
              <div className="modal-body">
                <div className="row g-3">
                  {qrLinks.map((link, idx) => {
                    const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=${encodeURIComponent(link)}`;
                    return (
                      <div key={idx} className="col-md-6 d-flex flex-column align-items-center gap-2">
                        <img src={qrUrl} alt={`QR ${idx + 1}`} width={220} height={220}
                          style={{ border: `2px solid ${'var(--border-color)'}`, borderRadius: '8px', backgroundColor: '#fff' }} />
                        <div className="d-flex gap-2 w-100">
                          <input readOnly className="form-control form-control-sm" value={link}
                            style={{ fontFamily: 'monospace', fontSize: '11px', backgroundColor: 'var(--bg-primary)', color: 'var(--text-secondary)', borderColor: 'var(--border-color)' }} />
                          <button className="btn btn-sm" style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14', whiteSpace: 'nowrap' }}
                            onClick={() => navigator.clipboard.writeText(link)}>Copy</button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Adjust Modal */}
      {showBulkAdjust && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }} onClick={(e) => { if (e.target === e.currentTarget) setShowBulkAdjust(false); }}>
          <div className="modal-dialog">
            <div className="modal-content" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>{t('messages.bulkAdjustTitle')}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowBulkAdjust(false)} />
              </div>
              <div className="modal-body">
                <p className="small mb-2" style={{ color: 'var(--text-secondary)' }}>Applies to all selected clients (or all visible if none selected).</p>
                <div className="d-flex gap-2 mb-3">
                  <button className="btn btn-sm" style={{ backgroundColor: bulkAdjustMode === 'add' ? 'var(--accent)' : 'var(--bg-tertiary)', borderColor: bulkAdjustMode === 'add' ? 'var(--accent)' : 'var(--border-color)', color: bulkAdjustMode === 'add' ? '#000f14' : 'var(--text-secondary)' }}
                    onClick={() => setBulkAdjustMode('add')}>+ Add Days / GB</button>
                  <button className="btn btn-sm" style={{ backgroundColor: bulkAdjustMode === 'set' ? 'var(--accent)' : 'var(--bg-tertiary)', borderColor: bulkAdjustMode === 'set' ? 'var(--accent)' : 'var(--border-color)', color: bulkAdjustMode === 'set' ? '#000f14' : 'var(--text-secondary)' }}
                    onClick={() => setBulkAdjustMode('set')}>📅 Set Exact Expiry</button>
                </div>
                {bulkAdjustMode === 'add' ? (
                  <>
                    <div className="mb-3">
                      <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>{t('messages.bulkAdjustAddDays')}</label>
                      <input type="number" className="form-control" value={bulkAdjustDays} onChange={(e) => setBulkAdjustDays(e.target.value)}
                        style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }} />
                    </div>
                    <div className="mb-3">
                      <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>{t('messages.bulkAdjustAddGB')}</label>
                      <input type="number" step="1" className="form-control" value={bulkAdjustGB} onChange={(e) => setBulkAdjustGB(e.target.value)}
                        style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }} />
                    </div>
                  </>
                ) : (
                  <div className="mb-3">
                    <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>Set expiry date for all selected clients:</label>
                    <input type="date" className="form-control" value={bulkSetExpiryDate} onChange={e => setBulkSetExpiryDate(e.target.value)}
                      style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }} />
                    <div className="small mt-1" style={{ color: 'var(--text-secondary)' }}>This sets the exact expiry date, overwriting existing dates.</div>
                  </div>
                )}
              </div>
              <div className="modal-footer" style={{ borderColor: 'var(--border-color)' }}>
                <button className="btn btn-sm" style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }} onClick={() => setShowBulkAdjust(false)}>{t('common.cancel')}</button>
                <button className="btn btn-sm btn-accent" onClick={handleBulkAdjust} disabled={bulkAdjustLoading}>{bulkAdjustLoading ? '...' : t('messages.bulkAdjustApply')}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Attach/Detach Inbounds Modal */}
      {showAttachModal && attachClient && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }} onClick={e => { if (e.target === e.currentTarget) setShowAttachModal(false); }}>
          <div className="modal-dialog">
            <div className="modal-content" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>⇄ Inbounds — {attachClient.email}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowAttachModal(false)} />
              </div>
              <div className="modal-body">
                <div className="d-flex gap-2 mb-3">
                  <button className="btn btn-sm" style={{ backgroundColor: attachMode === 'attach' ? 'var(--accent)' : 'var(--bg-tertiary)', borderColor: attachMode === 'attach' ? 'var(--accent)' : 'var(--border-color)', color: attachMode === 'attach' ? '#000f14' : 'var(--text-secondary)' }}
                    onClick={() => setAttachMode('attach')}>Attach</button>
                  <button className="btn btn-sm" style={{ backgroundColor: attachMode === 'detach' ? 'var(--danger)' : 'var(--bg-tertiary)', borderColor: attachMode === 'detach' ? 'var(--danger)' : 'var(--border-color)', color: attachMode === 'detach' ? '#fff' : 'var(--text-secondary)' }}
                    onClick={() => setAttachMode('detach')}>Detach</button>
                </div>
                <p className="small mb-2" style={{ color: 'var(--text-secondary)' }}>
                  Select inbounds to {attachMode} this client {attachMode === 'attach' ? 'to' : 'from'}:
                </p>
                {attachLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}
                {!attachLoading && attachInbounds.length === 0 && <p style={{ color: 'var(--text-secondary)' }}>No inbounds found for this node</p>}
                <div className="d-flex flex-column gap-1 mb-3">
                  {attachInbounds.map(ib => (
                    <label key={ib.id} className="d-flex align-items-center gap-2 p-2 rounded" style={{ backgroundColor: 'var(--bg-tertiary)', cursor: 'pointer' }}>
                      <input type="checkbox" checked={attachSelected.has(ib.id)}
                        onChange={e => {
                          setAttachSelected(prev => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(ib.id); else next.delete(ib.id);
                            return next;
                          });
                        }} />
                      <span style={{ color: 'var(--text-primary)' }}>{ib.remark || `#${ib.id}`}</span>
                      <span className="badge ms-auto" style={{ backgroundColor: 'var(--accent)' }}>{ib.protocol.toUpperCase()}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="modal-footer" style={{ borderColor: 'var(--border-color)' }}>
                <button className="btn btn-sm" style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                  onClick={() => setShowAttachModal(false)}>Cancel</button>
                <button className="btn btn-sm" style={{ backgroundColor: attachMode === 'attach' ? 'var(--accent)' : 'var(--danger)', color: '#fff' }}
                  onClick={handleAttachSubmit} disabled={attachSelected.size === 0}>
                  {attachMode === 'attach' ? 'Attach' : 'Detach'} ({attachSelected.size})
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Client Groups Modal */}
      {showGroupsModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }} onClick={(e) => { if (e.target === e.currentTarget) setShowGroupsModal(false); }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>🗂 Client Groups{groupsNodeName ? ` — ${groupsNodeName}` : ''}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowGroupsModal(false)} />
              </div>
              <div className="modal-body">
                {/* Node selector if no node chosen yet */}
                {!groupsNodeId && (
                  <div className="mb-3">
                    <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>Select node:</label>
                    <div className="d-flex flex-wrap gap-2">
                      {Array.from(new Map(clients.filter(c => c.node_id).map(c => [c.node_name, c.node_id!]))).map(([name, id]) => (
                        <button key={id} className="btn btn-sm" style={{ backgroundColor: 'var(--accent)', color: '#000f14' }}
                          onClick={() => handleOpenGroups(id, name)}>
                          {name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {groupsNodeId && (
                  <>
                    {groupsLoading && <div className="text-center py-2"><div className="spinner-border spinner-border-sm" /></div>}

                    {/* Create group */}
                    <div className="d-flex gap-2 mb-3">
                      <input className="form-control form-control-sm" placeholder="New group name" value={groupNewName}
                        onChange={e => setGroupNewName(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleCreateGroup(); }}
                        style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }} />
                      <button className="btn btn-sm" style={{ backgroundColor: 'var(--accent)', color: '#000f14', whiteSpace: 'nowrap' }}
                        onClick={handleCreateGroup} disabled={!groupNewName.trim()}>+ Create</button>
                    </div>

                    {/* Rename group */}
                    {groupRenameFrom && (
                      <div className="d-flex gap-2 mb-3 p-2 rounded" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
                        <span className="small" style={{ color: 'var(--text-secondary)', alignSelf: 'center' }}>Rename "{groupRenameFrom}":</span>
                        <input className="form-control form-control-sm" placeholder="New name" value={groupRenameTo}
                          onChange={e => setGroupRenameTo(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') handleRenameGroup(); }}
                          style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }} />
                        <button className="btn btn-sm" style={{ backgroundColor: 'var(--accent)', color: '#000f14' }}
                          onClick={handleRenameGroup} disabled={!groupRenameTo.trim()}>Save</button>
                        <button className="btn btn-sm" style={{ backgroundColor: 'transparent', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                          onClick={() => { setGroupRenameFrom(''); setGroupRenameTo(''); }}>✕</button>
                      </div>
                    )}

                    {/* Groups list */}
                    {!groupsLoading && groupsList.length === 0 && (
                      <p style={{ color: 'var(--text-secondary)' }}>No groups yet</p>
                    )}
                    <div className="d-flex flex-column gap-2">
                      {groupsList.map(group => (
                        <div key={group}>
                          <div className="d-flex align-items-center justify-content-between p-2 rounded" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
                            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{group}</span>
                            <div className="d-flex gap-1">
                              <button className="btn btn-sm" style={{ backgroundColor: 'transparent', borderColor: 'var(--border-color)', color: 'var(--text-secondary)', padding: '2px 8px', fontSize: '0.75rem' }}
                                onClick={() => handleViewGroupMembers(group)}>
                                {showGroupMembers === group ? 'Hide' : 'Members'}
                              </button>
                              <button className="btn btn-sm" style={{ backgroundColor: 'transparent', borderColor: 'var(--border-color)', color: 'var(--text-secondary)', padding: '2px 6px' }}
                                onClick={() => { setGroupRenameFrom(group); setGroupRenameTo(group); }} title="Rename">✎</button>
                              <button className="btn btn-sm btn-ghost-danger" style={{ padding: '2px 6px' }}
                                onClick={() => handleDeleteGroup(group)} title="Delete">✕</button>
                            </div>
                          </div>

                          {/* Members panel */}
                          {showGroupMembers === group && (
                            <div className="mt-1 ms-2 p-2 rounded" style={{ backgroundColor: 'var(--bg-primary)', border: `1px solid ${'var(--border-color)'}` }}>
                              {groupMembersLoading && <div className="spinner-border spinner-border-sm" />}
                              {!groupMembersLoading && groupMemberEmails.length === 0 && (
                                <p className="small mb-2" style={{ color: 'var(--text-secondary)' }}>No members</p>
                              )}
                              <div className="d-flex flex-wrap gap-1 mb-2">
                                {groupMemberEmails.map(email => (
                                  <span key={email} className="badge d-flex align-items-center gap-1" style={{ backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-primary)', fontWeight: 400 }}>
                                    {email}
                                    <button className="btn btn-sm p-0 ms-1" style={{ color: 'var(--danger)', lineHeight: 1, background: 'none', border: 'none' }}
                                      onClick={() => handleRemoveFromGroup(group, email)} title="Remove">✕</button>
                                  </span>
                                ))}
                              </div>
                              <div className="d-flex gap-2">
                                <input className="form-control form-control-sm" placeholder="email1, email2 (or newlines)"
                                  value={groupAddEmails} onChange={e => setGroupAddEmails(e.target.value)}
                                  style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }} />
                                <button className="btn btn-sm" style={{ backgroundColor: 'var(--accent)', color: '#000f14', whiteSpace: 'nowrap' }}
                                  onClick={() => handleAddToGroup(group)} disabled={!groupAddEmails.trim()}>+ Add</button>
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* IP Search Modal */}
      {showIpSearch && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }} onClick={e => { if (e.target === e.currentTarget) setShowIpSearch(false); }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>🔍 Find Clients by IP Address</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowIpSearch(false)} />
              </div>
              <div className="modal-body">
                <p className="small mb-2" style={{ color: 'var(--text-secondary)' }}>
                  Enter an IP address to find which clients have connected from it. Queries all nodes — may take a moment.
                </p>
                <div className="d-flex gap-2 mb-3">
                  <input
                    className="form-control"
                    placeholder="e.g. 1.2.3.4"
                    value={ipSearchValue}
                    onChange={e => setIpSearchValue(e.target.value)}
                    onKeyDown={async e => {
                      if (e.key !== 'Enter' || !ipSearchValue.trim()) return;
                      setIpSearchLoading(true);
                      setIpSearchResults([]);
                      try {
                        const res = await api.get('/v1/clients/find-by-ip', { params: { ip: ipSearchValue.trim() }, auth: getAuth() });
                        setIpSearchResults(res.data?.matches || []);
                      } catch (err: any) { toast(err.response?.data?.detail || 'Search failed', 'error'); }
                      finally { setIpSearchLoading(false); }
                    }}
    
                  />
                  <button
                    className="btn"
                    style={{ backgroundColor: 'var(--accent)', color: '#000f14', whiteSpace: 'nowrap' }}
                    disabled={!ipSearchValue.trim() || ipSearchLoading}
                    onClick={async () => {
                      setIpSearchLoading(true);
                      setIpSearchResults([]);
                      try {
                        const res = await api.get('/v1/clients/find-by-ip', { params: { ip: ipSearchValue.trim() }, auth: getAuth() });
                        setIpSearchResults(res.data?.matches || []);
                      } catch (err: any) { toast(err.response?.data?.detail || 'Search failed', 'error'); }
                      finally { setIpSearchLoading(false); }
                    }}
                  >
                    {ipSearchLoading ? '…' : 'Search'}
                  </button>
                </div>
                {ipSearchLoading && <div className="text-center py-3"><div className="spinner-border spinner-border-sm" /></div>}
                {!ipSearchLoading && ipSearchResults.length === 0 && ipSearchValue && (
                  <p style={{ color: 'var(--text-secondary)' }}>No clients found with IP {ipSearchValue}</p>
                )}
                {ipSearchResults.length > 0 && (
                  <div className="d-flex flex-column gap-2">
                    <div className="small mb-1 text-success">{ipSearchResults.length} match(es) found</div>
                    {ipSearchResults.map((r, i) => (
                      <div key={i} className="p-2 rounded" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
                        <div className="d-flex align-items-center gap-2">
                          <strong style={{ color: 'var(--text-primary)' }}>{r.email}</strong>
                          <span className="badge" style={{ backgroundColor: 'var(--accent)' }}>{r.node}</span>
                        </div>
                        <div className="small mt-1" style={{ color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                          {r.ips.join(', ')}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
