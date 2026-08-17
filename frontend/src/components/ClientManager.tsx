import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useToast } from './Toast';
import { useTranslation } from 'react-i18next';
import api from '../api';
import {
  clearClientIpHistory,
  getClientIpHistory,
  listClientsBySource,
  type ClientIpHistoryEntry,
  type ClientSourceFilter,
} from '../api/clients';
import { getInboundsHeaderSource } from '../api/dashboard';
import { listNodes } from '../api/nodes';
import { AddClientMultiServer } from './AddClientMultiServer';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';
import { readStaleCache, writeStaleCache } from '../services/staleCache';
import { useTrafficStatsSubscription, TrafficUpdate } from '../services/useTrafficStatsSubscription';
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
  encryption?: string;
  remark?: string;
  limitIp?: number;
  security?: string;
  network?: string;
  notes?: string;
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
  sourceFilter?: ClientSourceFilter;
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

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const inputClass = 'box-border min-w-0 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 font-mono text-xs font-light text-slate-100 outline-none transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10 disabled:cursor-not-allowed disabled:opacity-50 placeholder:text-slate-600';
const selectClass = `${inputClass} h-8 py-1 pr-8`;
const fieldLabelClass = 'mb-1 block text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500';
const checkboxClass = 'h-4 w-4 rounded border-cyan-500/20 bg-[#0a0e1a] text-cyan-300 accent-cyan-300';
const buttonBaseClass = 'inline-flex h-8 min-w-0 items-center justify-center gap-1 whitespace-nowrap rounded-md border border-transparent px-3 text-xs font-medium leading-none tracking-wide transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-45';
const buttonNeutralClass = `${buttonBaseClass} border-cyan-500/20 bg-[#0f1420] text-slate-200 hover:bg-[#0a0e1a]`;
const buttonAccentClass = `${buttonBaseClass} border-cyan-300/25 bg-cyan-400 text-[#06111f] hover:bg-cyan-300`;
const buttonSuccessClass = `${buttonBaseClass} border-emerald-300/20 bg-emerald-400/15 text-emerald-300 hover:bg-emerald-400/25`;
const buttonWarningClass = `${buttonBaseClass} border-amber-300/20 bg-amber-400/15 text-amber-300 hover:bg-amber-400/25`;
const buttonDangerClass = `${buttonBaseClass} border-rose-300/20 bg-rose-500/15 text-rose-300 hover:bg-rose-500/25`;
const buttonIconClass = 'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0f1420] text-slate-300 transition-colors hover:bg-[#0a0e1a] hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-45';
const sortButtonClass = 'inline-flex min-w-0 items-center gap-1 whitespace-nowrap text-left text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500 transition-colors hover:text-cyan-300';
const badgeBaseClass = 'inline-flex min-w-0 items-center justify-center whitespace-nowrap rounded-md border border-cyan-500/20 px-2 py-1 text-[11px] font-medium leading-none';
const modalBackdropClass = 'fixed inset-0 z-50 flex min-w-0 items-start justify-center overflow-y-auto bg-black/80 p-4';
const modalPanelClass = 'my-8 flex w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] text-slate-100 shadow-2xl ring-1 ring-cyan-500/10';
const modalHeaderClass = 'flex min-w-0 items-center justify-between gap-3 border-b border-cyan-500/20 px-4 py-3';
const modalBodyClass = 'min-w-0 overflow-y-auto p-4';
const modalFooterClass = 'flex min-w-0 flex-wrap items-center justify-end gap-2 border-t border-cyan-500/20 px-4 py-3';
const modalTitleClass = 'min-w-0 truncate text-sm font-medium uppercase tracking-wider text-slate-300';
const tableSkeletonLineClass = 'block animate-pulse rounded bg-[#182133]';
const tableStateChipClass = 'inline-flex min-w-0 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0f1420] px-3 py-2 font-mono text-[11px] font-light uppercase tracking-[0.14em] text-slate-400';
const tableErrorClass = 'mb-4 min-w-0 overflow-hidden rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 font-mono text-[11px] font-light text-rose-200/90 shadow-[inset_0_1px_0_rgba(251,113,133,0.08)]';
const tableLongEmailClass = 'block min-w-0 max-w-[120px] truncate text-left font-mono text-sm font-medium text-slate-100 hover:text-cyan-300 md:max-w-[200px] lg:max-w-xs';
const tableLongIdClass = 'mt-1 block min-w-0 max-w-[120px] truncate font-mono text-xs tabular-nums whitespace-nowrap text-slate-500 md:max-w-[200px] lg:max-w-xs';

const extractClientArray = (payload: unknown): unknown[] => {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    if (Array.isArray(record.clients)) return record.clients;
    if (Array.isArray(record.data)) return record.data;
  }
  return [];
};

const normalizeClientRows = (
  payload: unknown,
  nodeNameToId: Record<string, number> = {},
): Client[] => extractClientArray(payload).map((c: any) => ({
  ...c,
  id: c.id != null ? String(c.id) : null,
  total: Number(c.total ?? c.totalGB ?? 0) || 0,
  up: Number(c.up ?? c.traffic_up ?? 0) || 0,
  down: Number(c.down ?? c.traffic_down ?? 0) || 0,
  node_id: c.node_id ?? nodeNameToId[c.node_name] ?? null,
  node_name: c.node_name || '',
  notes: typeof c.notes === 'string' ? c.notes : '',
}));

const ClientTableSkeleton = () => (
  <div className="min-w-0 overflow-hidden">
    <div className="grid min-w-0 grid-cols-1 gap-3 p-3 lg:hidden">
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="min-h-[148px] animate-pulse rounded-lg bg-[#0a0e1a] p-3 ring-1 ring-cyan-500/10">
          <div className="grid grid-cols-[20px_minmax(0,1fr)_72px] items-start gap-3">
            <span className={`${tableSkeletonLineClass} h-4 w-4`} />
            <div className="min-w-0 space-y-2">
              <span className={`${tableSkeletonLineClass} h-4 w-4/5`} />
              <span className={`${tableSkeletonLineClass} h-3 w-2/3`} />
            </div>
            <span className={`${tableSkeletonLineClass} h-7 w-full`} />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {Array.from({ length: 4 }).map((__, chipIndex) => (
              <span key={chipIndex} className={`${tableSkeletonLineClass} h-7 w-full`} />
            ))}
          </div>
          <div className="mt-3 grid grid-cols-5 gap-2">
            {Array.from({ length: 5 }).map((__, actionIndex) => (
              <span key={actionIndex} className={`${tableSkeletonLineClass} h-8 w-8`} />
            ))}
          </div>
        </div>
      ))}
    </div>
    <div className="hidden w-full min-w-0 overflow-x-auto lg:block">
      <table className="w-full table-fixed border-collapse text-left text-xs">
        <thead className="bg-[#0f1420]">
          <tr className="border-b border-cyan-500/20">
            {['w-10', 'w-[17%]', 'w-[9%]', 'w-[6%]', 'w-[8%]', 'w-[9%]', 'w-[8%]', 'w-[9%]', 'w-[7%]', 'w-[5%]', 'w-[184px]'].map((width, index) => (
              <th key={index} className={`${width} px-3 py-3`}>
                <span className={`${tableSkeletonLineClass} h-3 w-16`} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">
          {Array.from({ length: 8 }).map((_, rowIndex) => (
            <tr key={rowIndex}>
              {Array.from({ length: 11 }).map((__, cellIndex) => (
                <td key={cellIndex} className="px-3 py-3">
                  <span className={`${tableSkeletonLineClass} h-4 ${cellIndex === 1 ? 'w-full' : 'w-16'}`} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

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
  const clientsRef = useRef<Client[]>([]);
  const [clientSourceFilter, setClientSourceFilter] = useState<ClientSourceFilter>('all');
  const clientSourceFilterRef = useRef<ClientSourceFilter>('all');
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
  
  // Filters persisted in localStorage.
  const FILTER_STORAGE_KEY = 'sub_manager_client_filters_v1';
  const _savedFilters = (() => { try { return JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY) || '{}'); } catch { return {}; } })();
  const [searchTerm, setSearchTerm] = useState<string>(_savedFilters.searchTerm ?? '');
  const [filterNode, setFilterNode] = useState<string>(_savedFilters.filterNode ?? '');
  const [filterStatus, setFilterStatus] = useState<string>(_savedFilters.filterStatus ?? '');
  const [filterProtocol, setFilterProtocol] = useState<string>(_savedFilters.filterProtocol ?? '');
  const [filterInboundId, setFilterInboundId] = useState<number | null>(null);
  const [filterExpiringSoon, setFilterExpiringSoon] = useState<boolean>(_savedFilters.filterExpiringSoon ?? false);
  const [expiringSoonDays, setExpiringSoonDays] = useState<number>(_savedFilters.expiringSoonDays ?? 7);
  // Online clients map: email -> true.
  const [onlineEmails] = useState<Set<string>>(() => new Set());
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

  // Last online map: email -> ISO string.
  const [lastOnlineMap] = useState<Record<string, string>>(() => ({}));

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

  // IP Search modal
  const [showIpSearch, setShowIpSearch] = useState(false);
  const [ipSearchValue, setIpSearchValue] = useState('');
  const [ipSearchResults, setIpSearchResults] = useState<Array<{email: string; node: string; ips: string[]}>>([]);
  const [ipSearchLoading, setIpSearchLoading] = useState(false);

  // Per-client IP history modal
  const [ipHistoryClient, setIpHistoryClient] = useState<Client | null>(null);
  const [ipHistoryEntries, setIpHistoryEntries] = useState<ClientIpHistoryEntry[]>([]);
  const [ipHistoryLoading, setIpHistoryLoading] = useState(false);
  const [ipHistoryClearing, setIpHistoryClearing] = useState(false);
  const [ipHistoryError, setIpHistoryError] = useState('');

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

  useEffect(() => {
    clientsRef.current = clients;
  }, [clients]);

  useEffect(() => {
    clientSourceFilterRef.current = clientSourceFilter;
  }, [clientSourceFilter]);

  useEffect(() => {
    // Handle navigation from InboundManager: apply inbound filter if set.
    try {
      const nav = sessionStorage.getItem('sm_nav_inbound_filter');
      if (nav) {
        sessionStorage.removeItem('sm_nav_inbound_filter');
        const { id } = JSON.parse(nav);
        if (id) setFilterInboundId(Number(id));
      }
    } catch {}
    // Handle navigation from TrafficStats: apply email search filter if set.
    try {
      const emailNav = sessionStorage.getItem('sm_nav_client_search');
      if (emailNav) {
        sessionStorage.removeItem('sm_nav_client_search');
        setSearchTerm(emailNav);
      }
    } catch {}
    // Handle navigation from InboundManager "Add Client": open batch add with pre-filled inbound.
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
    if (cached.data && (cached.data.sourceFilter ?? 'all') === 'all') {
      if (Array.isArray(cached.data.clients)) setClients(cached.data.clients);
      if (cached.data.trafficCache && typeof cached.data.trafficCache === 'object') {
        setTrafficCache(cached.data.trafficCache);
      }
      if (cached.data.endpointMode) {
        trafficEndpointModeRef.current = cached.data.endpointMode;
      }
    }

    loadClients(cached.isFresh);

    // Live presence and last-online are fleet fan-out endpoints.  They are
    // intentionally not requested on mount: a viewer previously generated a
    // denied POST here, while every role paid for an extra cold fleet scan.

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
    if (!ENABLE_LIVE_CLIENT_TRAFFIC || !expandedKey || filteredClients.length === 0) return;

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
  }, [expandedKey, filteredClients, trafficCache]);
  
  const loadClients = async (silent = false, sourceFilter: ClientSourceFilter = clientSourceFilterRef.current) => {
    if (refreshInFlightRef.current) {
      clientsLoadAbortRef.current?.abort();
    }

    const controller = new AbortController();
    clientsLoadAbortRef.current = controller;

    refreshInFlightRef.current = true;
    if (!silent) setLoading(true);
    setError('');
    clientSourceFilterRef.current = sourceFilter;

    const requestId = Date.now();
    requestIdRef.current = requestId;

    try {
      // Fire both requests in parallel; backend serves from cache (20s fresh / 180s stale).
      const [nodeList, clientsPayload, rawInbounds] = await Promise.all([
        listNodes({ signal: controller.signal }),
        listClientsBySource(sourceFilter, controller.signal),
        getInboundsHeaderSource({ signal: controller.signal }),
      ]);

      if (requestIdRef.current !== requestId) return;

      const nodeNameToId: Record<string, number> = {};
      nodeList.forEach(n => { nodeNameToId[n.name] = n.id; });

      const mappedClients = normalizeClientRows(clientsPayload, nodeNameToId);

      const deduped = new Map<string, Client>();
      mappedClients.forEach(c => deduped.set(clientKey(c), c));
      const next = Array.from(deduped.values());

      setClients(next);
      writeStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, {
        ts: Date.now(),
        clients: next,
        trafficCache,
        endpointMode: trafficEndpointModeRef.current,
        sourceFilter,
      });

      const inboundList: InboundOption[] = rawInbounds.map((ib: any) => ({
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
      sourceFilter: clientSourceFilterRef.current,
    });
  };

  const handleRealtimeUpdate = useCallback(
    (update: TrafficUpdate) => {
      if (update.type !== 'client_update' && update.type !== 'traffic_update' && update.type !== 'server_status') {
        return;
      }
      if (update.data?.source === 'snapshot_collector') {
        if (update.type === 'client_update' && update.data?.has_table_payload && Array.isArray(update.data.clients)) {
          if (clientSourceFilterRef.current !== 'all') {
            loadClients(true);
            return;
          }
          const existingNotes = new Map(
            clientsRef.current.map((client) => [clientKey(client), client.notes || ''])
          );
          const incoming = normalizeClientRows(update.data.clients).map((client) => ({
            ...client,
            notes: client.notes || existingNotes.get(clientKey(client)) || '',
          }));
          const nodeId = update.data.node_id != null ? Number(update.data.node_id) : null;
          const nodeName = String(update.data.node || '');
          const retained = clientsRef.current.filter((client) => {
            if (nodeId !== null && client.node_id != null) {
              return Number(client.node_id) !== nodeId;
            }
            return client.node_name !== nodeName;
          });
          const deduped = new Map<string, Client>();
          [...retained, ...incoming].forEach((client) => deduped.set(clientKey(client), client));
          const nextClients = Array.from(deduped.values());
          clientsRef.current = nextClients;
          setClients(nextClients);

          setTrafficCache((prev) => {
            const nextTraffic = { ...prev };
            incoming.forEach((client) => {
              if (client.node_id == null) return;
              nextTraffic[`${client.node_id}:${client.email}`] = {
                upload: client.up,
                download: client.down,
                up: client.up,
                down: client.down,
                total: client.total,
                enable: client.enable,
                expiryTime: client.expiryTime,
              };
            });
            writeStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, {
              ts: Date.now(),
              clients: nextClients,
              trafficCache: nextTraffic,
              endpointMode: trafficEndpointModeRef.current,
              sourceFilter: clientSourceFilterRef.current,
            });
            return nextTraffic;
          });

          if (Array.isArray(update.data.inbounds)) {
            const incomingInbounds = update.data.inbounds.map((ib: any) => ({
              id: ib.id,
              node_name: ib.node_name,
              protocol: ib.protocol,
              remark: ib.remark || '',
            }));
            setInboundOptions((prev) => [
              ...prev.filter((ib) => ib.node_name !== nodeName),
              ...incomingInbounds,
            ]);
          }
        }
        return;
      }
      if (update.type === 'traffic_update' || update.type === 'server_status') {
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

  const saveClientNote = async (client: Client, note: string) => {
    const identifier = clientIdentifier(client);
    if (!identifier || client.node_id == null) {
      toast(t('clients.noteSaveFailed'), 'error');
      return;
    }

    const nextNote = note.trim();
    try {
      await api.put(`/v1/clients/${encodeURIComponent(identifier)}/notes`, {
        node_id: client.node_id,
        inbound_id: client.inbound_id ?? 0,
        email: client.email,
        notes: nextNote,
      }, { auth: getAuth() });

      const targetKey = clientKey(client);
      setClients(prev => {
        const nextClients = prev.map((item) => clientKey(item) === targetKey ? { ...item, notes: nextNote } : item);
        clientsRef.current = nextClients;
        writeStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, {
          ts: Date.now(),
          clients: nextClients,
          trafficCache,
          endpointMode: trafficEndpointModeRef.current,
          sourceFilter: clientSourceFilterRef.current,
        });
        return nextClients;
      });
      toast(t('clients.noteSaved'), 'success');
    } catch (e: any) {
      toast(e.response?.data?.detail || t('clients.noteSaveFailed'), 'error');
    }
  };

  const handleClientNoteClick = (client: Client) => {
    const note = window.prompt(t('clients.localNotePrompt'), client.notes || '');
    if (note !== null) {
      void saveClientNote(client, note);
    }
  };

  const handleClientSourceFilterChange = (value: ClientSourceFilter) => {
    if (value === clientSourceFilterRef.current) return;
    clientSourceFilterRef.current = value;
    setClientSourceFilter(value);
    setFilterStatus('');
    setSelectedClientKeys(new Set());
    setCurrentPage(1);
    void loadClients(false, value);
  };

  const handleOpenClientIpHistory = async (client: Client) => {
    setIpHistoryClient(client);
    setIpHistoryEntries([]);
    setIpHistoryError('');
    setIpHistoryLoading(true);
    try {
      const data = await getClientIpHistory(client.email, client.node_id);
      setIpHistoryEntries(
        data.results
          .map((entry) => ({
            node: entry.node,
            ips: Array.isArray(entry.ips) ? entry.ips.filter(Boolean) : [],
          }))
          .filter((entry) => entry.ips.length > 0),
      );
    } catch (err: any) {
      const message = err.response?.data?.detail || t('clients.ipHistoryLoadFailed');
      setIpHistoryError(message);
      toast(message, 'error');
    } finally {
      setIpHistoryLoading(false);
    }
  };

  const handleClearClientIpHistory = async () => {
    if (!ipHistoryClient) return;
    setIpHistoryClearing(true);
    try {
      await clearClientIpHistory(ipHistoryClient.email, ipHistoryClient.node_id);
      setIpHistoryEntries([]);
      toast(t('clients.ipHistoryCleared'), 'success');
    } catch (err: any) {
      toast(err.response?.data?.detail || t('clients.ipHistoryClearFailed'), 'error');
    } finally {
      setIpHistoryClearing(false);
    }
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
      toast(t(attachMode === 'attach' ? 'clients.attachedSuccess' : 'clients.detachedSuccess'), 'success');
      setShowAttachModal(false);
      loadClients(true);
    } catch (e: any) { toast(e.response?.data?.detail || t('common.failed'), 'error'); }
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
    sortField === field ? (sortDirection === 'asc' ? ' ^' : ' v') : '';
  
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
  const visibleClients = filteredClients.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const allFilteredSelected =
    filteredClients.length > 0 && filteredClients.every((c) => selectedClientKeys.has(clientKey(c)));
  const statusChipClass = (client: Client, isExpired: boolean, isDepleted: boolean) =>
    cn(
      'inline-flex h-7 items-center rounded-md border px-2 text-[11px] font-medium whitespace-nowrap',
      isExpired
        ? 'border-amber-300/25 bg-amber-400/10 text-amber-300'
        : isDepleted
          ? 'border-rose-400/25 bg-rose-500/10 text-rose-300'
          : client.enable
            ? 'border-emerald-300/25 bg-emerald-400/10 text-emerald-300'
            : 'border-cyan-500/20 bg-[#0f1420] text-slate-500'
    );
  
  return (
    <div data-client-manager-root className="min-h-screen min-w-0 overflow-hidden bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6">
      <div className="min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]">
        <div className="mb-4 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <h2 className="flex min-w-0 items-center gap-2 text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">
            <UIIcon name="clients" size={16} />
            {t('clients.title')}
          </h2>
          {clients.length > 0 && (() => {
            const now = Date.now();
            const active = clients.filter(c => c.enable && !(c.expiryTime > 0 && c.expiryTime < now) && !(c.total > 0 && c.up + c.down >= c.total)).length;
            const expired = clients.filter(c => c.expiryTime > 0 && c.expiryTime < now).length;
            const depleted = clients.filter(c => c.total > 0 && c.up + c.down >= c.total).length;
            const disabled = clients.filter(c => !c.enable).length;
            const online = onlineEmails.size;
            return (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 lg:flex lg:flex-wrap">
                {[
                  { label: 'Total', value: clients.length, className: 'text-slate-100', status: '' },
                  { label: 'Active', value: `${active} (${clients.length ? Math.round(active / clients.length * 100) : 0}%)`, className: 'text-emerald-300', status: 'active' },
                  { label: 'Online', value: `${online} (${active ? Math.round(online / active * 100) : 0}%)`, className: 'text-cyan-300', status: 'online' },
                  { label: 'Expired', value: expired, className: 'text-amber-300', status: 'expired' },
                  { label: 'Depleted', value: depleted, className: 'text-rose-300', status: 'depleted' },
                  { label: 'Disabled', value: disabled, className: 'text-slate-500', status: 'disabled' },
                ].map(s => (
                  <button
                    key={s.label}
                    type="button"
                    className={cn(
                      'min-w-0 rounded-md bg-[#0a0e1a] px-2 py-1 text-left text-[11px] text-slate-500 ring-1 transition-colors',
                      s.status ? 'cursor-pointer hover:ring-cyan-300/35' : 'cursor-default',
                      filterStatus === s.status && s.status ? 'ring-cyan-300/50' : 'ring-cyan-500/10'
                    )}
                    title={s.status ? (filterStatus === s.status ? 'Click to clear filter' : `Click to filter by ${s.label}`) : undefined}
                    onClick={() => s.status && setFilterStatus(prev => prev === s.status ? '' : s.status)}
                  >
                    <span className="block truncate uppercase tracking-wider">{s.label}</span>
                    <strong className={cn('mt-1 block font-mono text-sm tabular-nums whitespace-nowrap', s.className)}>{s.value}</strong>
                  </button>
                ))}
              </div>
            );
          })()}
        </div>
        {error && <div className={tableErrorClass}>{error}</div>}

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
                className={cn(showAddForm ? buttonNeutralClass : buttonAccentClass)}
                onClick={() => setShowAddForm(v => !v)}
                title={showAddForm ? 'Hide add form' : 'Add client to multiple servers'}
              >
                <span className="inline-flex items-center gap-1">
                  <UIIcon name={showAddForm ? 'x' : 'plus'} size={14} />
                  {showAddForm ? t('common.close') : t('common.add')}
                </span>
              </button>
              <button
                className={buttonNeutralClass}
                onClick={() => setShowBatchModal(true)}
              >
                <span className="inline-flex items-center gap-1"><UIIcon name="plus" size={14} />{t('clients.batchAdd')}</span>
              </button>
              <button
                className={buttonSuccessClass}
                onClick={exportToCSV}
              >
                <span className="inline-flex items-center gap-1"><UIIcon name="download" size={14} />{t('clients.exportCsv')}</span>
              </button>
              <label
                className={cn(buttonNeutralClass, 'mb-0')}
                title={t('clients.importCsvTitle')}
              >
                <span className="inline-flex items-center gap-1"><UIIcon name="upload" size={14} /> {t('clients.importCsv')}</span>
                <input type="file" accept=".csv,.txt" className="hidden"
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
                    if (emails.length === 0) { toast(t('clients.noEmailsInCsv'), 'error'); return; }
                    // Open batch modal with these emails pre-filled
                    const emailsStr = emails.join('\n');
                    setBatchText(emailsStr);
                    setShowBatchModal(true);
                    toast(t('clients.loadedEmailsFromCsv', { count: emails.length }), 'info');
                  }}
                />
              </label>
              <button
                className={buttonAccentClass}
                onClick={() => loadClients()}
                disabled={loading}
              >
                <span className="inline-flex items-center gap-1">
                  <UIIcon name={loading ? 'spinner' : 'refresh'} size={14} />
                  {t('common.refresh')}
                </span>
              </button>
              <button
                className={cn(autoRefresh ? buttonAccentClass : buttonNeutralClass)}
                onClick={() => setAutoRefresh(v => !v)}
                title={autoRefresh ? t('clients.autoRefreshEvery', { seconds: refreshInterval }) : t('clients.enableAutoRefresh')}
              >
                {t('clients.auto')}
              </button>
              {autoRefresh && (
                <select className={selectClass}
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
              <ChoiceChips
                options={[
                  { value: 'all', label: t('common.all'), title: 'API v1 clients' },
                  { value: 'expired', label: t('clients.expired'), title: 'API v1 clients (expired)' },
                  { value: 'depleted', label: t('clients.depleted'), title: 'API v1 clients (depleted)' },
                ]}
                value={clientSourceFilter}
                onChange={handleClientSourceFilterChange}
              />
              <input
                ref={searchInputRef}
                type="text"
                className={inputClass}
                placeholder={t('clients.searchPlaceholder') + ' (Ctrl+/) - space=AND, |=OR'}
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
                  className={selectClass}
                  value={filterInboundId ?? ''}
                  onChange={e => setFilterInboundId(e.target.value ? Number(e.target.value) : null)}
                  style={{ maxWidth: '180px', fontSize: '0.75rem' }}
                >
                  <option value="">{t('clients.allInbounds')}</option>
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
                  { value: 'online', label: 'Online' },
                  { value: 'offline', label: 'Offline' },
                ]}
                value={filterStatus}
                onChange={(value) => setFilterStatus(value)}
                
              />
              <div className="flex items-center gap-1">
                <button
                  className={cn(filterExpiringSoon ? buttonWarningClass : buttonNeutralClass)}
                  style={{ fontSize: '0.75rem' }}
                  onClick={() => setFilterExpiringSoon(v => !v)}
                >
                  Expiring {expiringSoonDays}d
                </button>
                <select
                  className={selectClass}
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
                className={cn(onlineFirst ? buttonAccentClass : buttonNeutralClass)}
                onClick={() => setOnlineFirst(v => !v)}
                title="Show online clients first"
              >
                {t('clients.onlineFirst')}
              </button>
              <button
                className={buttonNeutralClass}
                title={t('clients.duplicates')}
                onClick={() => {
                  const emailCount: Record<string, string[]> = {};
                  clients.forEach(c => {
                    if (!emailCount[c.email]) emailCount[c.email] = [];
                    emailCount[c.email].push(c.node_name || c.node_id?.toString() || '?');
                  });
                  const dupes = Object.entries(emailCount).filter(([, nodes]) => nodes.length > 1);
                  if (dupes.length === 0) { toast('No duplicate emails found', 'info'); return; }
                  setSearchTerm(dupes[0][0]);
                  toast(`${dupes.length} duplicate email(s) found - showing first: "${dupes[0][0]}" (${dupes[0][1].join(', ')})`, 'warning');
                }}
              >
                {t('clients.duplicates')}
              </button>
              {(clientSourceFilter !== 'all' || searchTerm || filterNode || filterProtocol || filterStatus || filterExpiringSoon || filterInboundId !== null) && (
                <button
                  className={buttonWarningClass}
                  onClick={() => {
                    handleClientSourceFilterChange('all');
                    setSearchTerm('');
                    setFilterNode('');
                    setFilterProtocol('');
                    setFilterStatus('');
                    setFilterExpiringSoon(false);
                    setFilterInboundId(null);
                  }}
                >
                  X {t('inbounds.clearFilters')}
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
                  <button className={buttonNeutralClass}
                    title={t('clients.copySelectedEmails')}
                    onClick={() => {
                      const emails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      navigator.clipboard.writeText(emails.join('\n')).then(() => toast(`Copied ${emails.length} email(s)`, 'info'));
                    }}>
                    <UIIcon name="copy" size={13} /> {t('clients.copyEmails')}
                  </button>
                  <button className={buttonDangerClass} onClick={() => handleBatchDelete('selected')}>
                    <span className="inline-flex items-center gap-1"><UIIcon name="trash" size={13} />{t('clients.deleteSelected')}</span>
                  </button>
                  <button className={buttonSuccessClass}
                    onClick={async () => {
                      const emails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      const { user, password } = getAuth();
                      try {
                        await api.post('/v1/clients/bulk-enable', { emails, enable: true }, { auth: { username: user, password } });
                        toast(`Enabled ${emails.length} clients`, 'success');
                        loadClients(true);
                      } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                    }}>
                    {t('common.enable')}
                  </button>
                  <button className={buttonNeutralClass}
                    onClick={async () => {
                      const emails = filteredClients.filter(c => selectedClientKeys.has(clientKey(c))).map(c => c.email);
                      const { user, password } = getAuth();
                      try {
                        await api.post('/v1/clients/bulk-enable', { emails, enable: false }, { auth: { username: user, password } });
                        toast(`Disabled ${emails.length} clients`, 'success');
                        loadClients(true);
                      } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                    }}>
                    {t('common.disable')}
                  </button>
                  <button className={buttonAccentClass}
                    onClick={() => { setBulkAdjustMode('add'); setShowBulkAdjust(true); }}>
                    {t('messages.bulkAdjustTitle')}
                  </button>
                  <button className={buttonNeutralClass}
                    title={t('clients.setExactLimitTitle')}
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
                    {t('clients.setLimit')}
                  </button>
                  <button className={buttonAccentClass}
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
                    {t('clients.resetTraffic')}
                  </button>
                  <button className={buttonWarningClass}
                    title={t('clients.freezeSelectedTitle')}
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
                    {t('clients.freezeSelected')}
                  </button>
                  <button className={buttonNeutralClass}
                    title={t('clients.exportCsv')}
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
                    <UIIcon name="download" size={13} /> {t('clients.exportCsv')}
                  </button>
                  <button className={buttonNeutralClass}
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
                    <UIIcon name="download" size={13} /> {t('clients.exportLinks')}
                  </button>
                  <button className={buttonNeutralClass}
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
                    <UIIcon name="group" size={13} /> {t('clients.addToGroup')}
                  </button>
                </div>
              )}
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500">{t('clients.quickSelect')}</span>
                <button className={buttonDangerClass} style={{ fontSize: '0.75rem' }}
                  onClick={() => selectAllBy(c => c.expiryTime > 0 && c.expiryTime < Date.now())}>
                  {t('clients.selectAllExpired')}
                </button>
                <button className={buttonWarningClass} style={{ fontSize: '0.75rem' }}
                  onClick={() => selectAllBy(c => c.total > 0 && c.up + c.down >= c.total)}>
                  {t('clients.selectAllDepleted')}
                </button>
                <button className={buttonNeutralClass} style={{ fontSize: '0.75rem' }}
                  onClick={() => selectAllBy(c => !c.enable)}>
                  {t('clients.selectAllDisabled')}
                </button>
                <button className={buttonNeutralClass} style={{ fontSize: '0.75rem' }}
                  onClick={() => setSelectedClientKeys(new Set())}>
                  {t('clients.clearSelection')}
                </button>
              </div>
              <div className="panel-inline-actions">
                <button
                  className={buttonWarningClass}
                  onClick={() => handleBatchDelete('expired')}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="trash" size={14} />{t('clients.deleteExpired')}</span>
                </button>
                <button
                  className={buttonWarningClass}
                  onClick={() => handleBatchDelete('depleted')}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="trash" size={14} />{t('clients.deleteDepleted')}</span>
                </button>
                <button
                  className={buttonAccentClass}
                  onClick={() => handleResetTraffic(null)}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="refresh" size={14} />{t('clients.resetAllTraffic')}</span>
                </button>
                <button
                  className={buttonDangerClass}
                  onClick={handleDelDepleted}
                  disabled={delDepletedLoading}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="trash" size={14} />{t('messages.delDepleted')}</span>
                </button>
                <button
                  className={buttonWarningClass}
                  title={t('clients.resetDepletedTitle')}
                  onClick={async () => {
                    const depleted = clients.filter(c => c.total > 0 && c.up + c.down >= c.total);
                    if (depleted.length === 0) { toast(t('clients.noDepletedClients'), 'info'); return; }
                    if (!window.confirm(t('clients.confirmResetDepleted', { count: depleted.length }))) return;
                    const { user, password } = getAuth();
                    try {
                      const res = await api.post('/v1/clients/bulk-reset-traffic', {
                        emails: depleted.map(c => c.email),
                      }, { auth: { username: user, password } });
                      toast(t('clients.resetDepletedResult', { count: res.data?.successful ?? depleted.length }), 'success');
                      loadClients(true);
                    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                  }}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="refresh" size={14} /> {t('clients.resetDepleted')}</span>
                </button>
                <button
                  className={buttonAccentClass}
                  title={t('clients.renewExpiredTitle')}
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
                  <span className="inline-flex items-center gap-1">{t('clients.renewExpired')}</span>
                </button>
                <button
                  className={buttonWarningClass}
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
                  {t('clients.extendExpiring')}
                </button>
                <button
                  className={buttonAccentClass}
                  onClick={() => setShowBulkAdjust(true)}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="edit" size={14} />{t('messages.bulkAdjustTitle')}</span>
                </button>
                <button
                  className={buttonNeutralClass}
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
                  <span className="inline-flex items-center gap-1"><UIIcon name="group" size={13} /> Groups</span>
                </button>
                <button
                  className={cn(denseView ? buttonAccentClass : buttonNeutralClass)}
                  title={t('clients.toggleDenseView')}
                  onClick={() => setDenseView(v => !v)}
                >
                  <span className="inline-flex items-center gap-1">Dense</span>
                </button>
                <button
                  className={buttonNeutralClass}
                  title={t('clients.findByIpTitle')}
                  onClick={() => { setIpSearchValue(''); setIpSearchResults([]); setShowIpSearch(true); }}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="search" size={13} /> {t('clients.findByIp')}</span>
                </button>
                <button
                  className={buttonNeutralClass}
                  title={t('clients.copyVisibleEmailsTitle')}
                  onClick={() => {
                    const emails = filteredClients.map(c => c.email).join('\n');
                    navigator.clipboard.writeText(emails).then(() => toast(t('clients.copiedEmailsCount', { count: filteredClients.length }), 'info'));
                  }}
                >
                  <span className="inline-flex items-center gap-1"><UIIcon name="copy" size={13} /> {t('clients.copyEmails')}</span>
                </button>
                <button
                  className={buttonNeutralClass}
                  title={t('clients.exportVisibleJsonTitle')}
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
                  <span className="inline-flex items-center gap-1"><UIIcon name="download" size={13} /> JSON</span>
                </button>
                <button
                  className={buttonNeutralClass}
                  title={t('clients.exportVisibleCsvTitle')}
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
                  <span className="inline-flex items-center gap-1"><UIIcon name="download" size={13} /> CSV</span>
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
          <div className="mb-2 flex flex-wrap gap-2">
            {[
              { label: 'Total',    value: clients.length, cls: '',          status: '' },
              { label: 'Active',   value: `${active} (${clients.length ? Math.round(active / clients.length * 100) : 0}%)`, cls: 'text-emerald-300', status: 'active' },
              { label: 'Online',   value: `${online} (${active ? Math.round(online / active * 100) : 0}%)`, cls: 'text-accent',  status: 'online' },
              { label: 'Expired',  value: expired,  cls: 'text-rose-300',  status: 'expired' },
              { label: 'Depleted', value: depleted, cls: 'text-amber-300', status: 'depleted' },
              { label: 'Disabled', value: disabled, cls: 'text-slate-500',   status: 'disabled' },
            ].map(s => (
              <span key={s.label}
                className={cn(
                  badgeBaseClass,
                  'bg-[#0f1420] font-mono tabular-nums whitespace-nowrap text-[0.78rem] font-normal',
                  s.cls,
                  s.status && filterStatus === s.status && 'border-current bg-cyan-400/10 ring-1 ring-cyan-300/50'
                )}
                style={{
                  cursor: s.status ? 'pointer' : 'default',
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
            {' '}({(currentPage - 1) * pageSize + 1}-{Math.min(currentPage * pageSize, filteredClients.length)} of {filteredClients.length})
          </span>
          <div className="flex gap-1">
            <button className={buttonNeutralClass} disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}>{"<<"}</button>
            <button className={buttonNeutralClass} disabled={currentPage <= 1} onClick={() => setCurrentPage(p => p - 1)}>{"<"}</button>
            <button className={buttonNeutralClass} disabled={currentPage >= Math.ceil(filteredClients.length / pageSize)} onClick={() => setCurrentPage(p => p + 1)}>{">"}</button>
            <button className={buttonNeutralClass} disabled={currentPage >= Math.ceil(filteredClients.length / pageSize)} onClick={() => setCurrentPage(Math.ceil(filteredClients.length / pageSize))}>{">>"}</button>
          </div>
          <button className={buttonNeutralClass} style={{ fontSize: '0.72rem' }}
            title={t('clients.selectPageTitle')}
            onClick={() => {
              const pageClients = filteredClients.slice((currentPage - 1) * pageSize, currentPage * pageSize);
              setSelectedClientKeys(prev => {
                const next = new Set(prev);
                pageClients.forEach(c => next.add(clientKey(c)));
                return next;
              });
            }}>
            {t('clients.selectPage')}
          </button>
          <select className={selectClass}
            value={currentPage} onChange={e => setCurrentPage(Number(e.target.value))}>
            {Array.from({ length: Math.ceil(filteredClients.length / pageSize) }, (_, i) => (
              <option key={i + 1} value={i + 1}>Page {i + 1}</option>
            ))}
          </select>
          <select className={selectClass}
            value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(1); }}
            title={t('clients.rowsPerPage')}>
            {[25, 50, 100, 200, 500].map(n => <option key={n} value={n}>{n} / page</option>)}
          </select>
        </div>
      )}

      {/* Client Database */}
      <section className="min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420]">
        {loading && filteredClients.length > 0 && <div className="h-1 overflow-hidden bg-[#0a0e1a]"><div className="h-full w-1/3 animate-pulse rounded-full bg-cyan-300" /></div>}
        {loading && filteredClients.length === 0 && <ClientTableSkeleton />}
        {!loading && trafficLoading && <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500"><UIIcon name="spinner" size={12} className="animate-spin text-cyan-300" /><span className="whitespace-nowrap">{t('clients.loadingTraffic')}</span></div>}
        {!loading && filteredClients.length === 0 && clients.length === 0 && (
          <div className="flex min-w-0 items-center justify-center px-4 py-10 text-center"><span className={tableStateChipClass}>{t('common.noRecordsFound')}</span></div>
        )}
        {!loading && filteredClients.length === 0 && clients.length > 0 && (
          <div className="flex min-w-0 items-center justify-center px-4 py-10 text-center"><span className={tableStateChipClass}>{t('common.noRecordsFound')}</span></div>
        )}
        {filteredClients.length > 0 && <>
          <div className="grid min-w-0 grid-cols-1 gap-3 p-3 lg:hidden">
            {visibleClients.map((client) => {
              const trafficKey = client.node_id != null ? `${client.node_id}:${client.email}` : null;
              const downloadBytes = getTrafficBytes(trafficKey, 'download', client.down);
              const isExpired = client.expiryTime > 0 && client.expiryTime < Date.now();
              const isDepleted = client.total > 0 && (client.up + client.down) >= client.total;
              const used = client.up + client.down;
              const pct = client.total > 0 ? Math.min(100, (used / client.total) * 100) : 0;
              return <article key={clientKey(client)} className="min-w-0 overflow-hidden rounded-lg bg-[#0a0e1a] p-3 ring-1 ring-cyan-500/10">
                <div className="flex min-w-0 items-start justify-between gap-3"><label className="flex min-w-0 items-start gap-2"><input className={checkboxClass} type="checkbox" checked={selectedClientKeys.has(clientKey(client))} onChange={() => toggleSelection(client)} /><span className="min-w-0"><button type="button" className={tableLongEmailClass} title={client.email} onClick={() => setExpandedKey(prev => prev === clientKey(client) ? null : clientKey(client))}>{client.email}</button><span className={tableLongIdClass} title={client.id || client.password || ''}>{client.id || client.password || '-'}</span></span></label><button type="button" className={statusChipClass(client, isExpired, isDepleted)} onClick={async () => { const identifier = clientIdentifier(client); if (!identifier) return; try { await api.put(`/v1/clients/${encodeURIComponent(identifier)}`, { node_id: client.node_id, inbound_id: client.inbound_id, updates: { email: client.email, enable: !client.enable } }, { auth: getAuth() }); setClients(prev => prev.map(c => clientKey(c) === clientKey(client) ? { ...c, enable: !c.enable } : c)); } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); } }}>{isExpired ? 'Expired' : isDepleted ? 'Depleted' : client.enable ? 'Active' : 'Disabled'}</button></div>
                <div className="mt-3 grid min-w-0 grid-cols-2 gap-2"><button type="button" className={cn(badgeBaseClass, 'justify-start bg-[#0f1420] text-slate-200')} onClick={() => setFilterNode(prev => prev === client.node_name ? '' : client.node_name)}><span className="truncate">{client.node_name}</span></button><button type="button" className={cn(badgeBaseClass, 'bg-cyan-400 text-[#06111f]')} onClick={() => setFilterProtocol(prev => prev === client.protocol ? '' : client.protocol)}>{client.protocol.toUpperCase()}</button><span className={cn(badgeBaseClass, 'justify-start bg-[#0f1420] font-mono text-slate-300 tabular-nums')}><span className="truncate whitespace-nowrap">{formatBytes(downloadBytes)}</span></span><span className={cn(badgeBaseClass, 'justify-start bg-[#0f1420] font-mono text-slate-300 tabular-nums')}><span className="truncate whitespace-nowrap">{client.total > 0 ? formatBytes(client.total) : 'unlimited'}</span></span></div>
                {client.total > 0 && <div className="mt-3"><div className="h-1 overflow-hidden rounded-full bg-[#0f1420]"><div className={cn('h-full rounded-full', pct >= 90 ? 'bg-rose-400' : pct >= 70 ? 'bg-amber-300' : 'bg-emerald-400')} style={{ width: `${pct}%` }} /></div><div className="mt-1 font-mono text-[11px] tabular-nums text-slate-500 whitespace-nowrap">{(used / 1073741824).toFixed(1)} / {(client.total / 1073741824).toFixed(1)} GB</div></div>}
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-500"><div className="min-w-0"><span className="block uppercase tracking-wider">{t('clients.expiryTime')}</span><span className="mt-1 block truncate font-mono tabular-nums text-slate-200 whitespace-nowrap">{client.expiryTime > 0 ? new Date(client.expiryTime).toLocaleDateString() : t('clients.never')}</span></div><div className="min-w-0 text-right"><span className="block uppercase tracking-wider">Last Online</span><span className="mt-1 block truncate font-mono tabular-nums text-slate-300 whitespace-nowrap">{lastOnlineMap[client.email] ? new Date(lastOnlineMap[client.email]).toLocaleDateString() : '-'}</span></div></div>
                <div className="mt-3 grid grid-cols-6 gap-2"><button type="button" className={buttonIconClass} onClick={() => handleClientEditClick(client)} title={t('messages.editClient')}><UIIcon name="edit" size={14} /></button><button type="button" className={buttonIconClass} onClick={() => handleResetTraffic(client)} title={t('clients.resetTraffic')}><UIIcon name="refresh" size={14} /></button><button type="button" className={buttonIconClass} onClick={() => handleOpenAttach(client, 'attach')} title={t('clients.attachDetachInbounds')}><UIIcon name="attach" size={14} /></button><button type="button" className={buttonIconClass} onClick={() => handleOpenClientIpHistory(client)} title={t('clients.ipHistoryTitle')}><UIIcon name="ip" size={14} /></button><button type="button" className={cn(buttonIconClass, client.notes && 'text-cyan-300')} onClick={() => handleClientNoteClick(client)} title={t('clients.noteTitle')}><UIIcon name="note" size={14} /></button><button type="button" className={cn(buttonIconClass, 'bg-rose-500 text-white hover:bg-rose-400')} onClick={async () => { const identifier = clientIdentifier(client); if (!identifier || !client.inbound_id) { toast('Cannot identify client', 'warning'); return; } if (!window.confirm(`Delete client "${client.email}"?`)) return; try { await api.delete(`/v1/clients/${encodeURIComponent(identifier)}`, { auth: getAuth(), params: { node_id: client.node_id, inbound_id: client.inbound_id } }); loadClients(true); } catch (e: any) { toast(e.response?.data?.detail || 'Delete failed', 'error'); } }} title={t('clients.deleteClient') || 'Delete client'}><UIIcon name="trash" size={14} /></button></div>
              </article>;
            })}
          </div>
          <div className="hidden w-full min-w-0 overflow-hidden bg-[#0a0e1a] lg:block"><div className="w-full min-w-0 overflow-x-auto"><table className="w-full table-fixed border-collapse text-left text-xs"><thead className="bg-[#0f1420] text-[10px] uppercase tracking-wider text-slate-500"><tr className="border-b border-cyan-500/20"><th className="w-10 px-3 py-3"><input className={checkboxClass} type="checkbox" checked={allFilteredSelected} onChange={toggleSelectAll} /></th><th className="w-[17%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('email')}>{t('clients.email')}{sortIndicator('email')}</button></th><th className="w-[9%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('node')}>{t('traffic.node')}{sortIndicator('node')}</button></th>{!denseView && <th className="w-[6%] px-3 py-3">{t('inbounds.protocol')}</th>}<th className="w-[8%] px-3 py-3">{t('common.status')}</th><th className="w-[9%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('download')}>{t('traffic.download')}{sortIndicator('download')}</button></th><th className="w-[8%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('total')}>{t('clients.totalLimit')}{sortIndicator('total')}</button></th><th className="w-[9%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('expiry')}>{t('clients.expiryTime')}{sortIndicator('expiry')}</button></th>{!denseView && <th className="w-[7%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('lastOnline')}>Last Online{sortIndicator('lastOnline')}</button></th>}<th className="w-[5%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('health')}>Health{sortIndicator('health')}</button></th><th className="w-[224px] px-3 py-3">{t('common.actions')}</th></tr></thead><tbody className="divide-y divide-slate-800/60 text-slate-200">
            {visibleClients.map((client) => { const trafficKey = client.node_id != null ? `${client.node_id}:${client.email}` : null; const downloadBytes = getTrafficBytes(trafficKey, 'download', client.down); const isExpired = client.expiryTime > 0 && client.expiryTime < Date.now(); const isDepleted = client.total > 0 && (client.up + client.down) >= client.total; const used = client.up + client.down; const pct = client.total > 0 ? Math.min(100, (used / client.total) * 100) : 0; const hs = getHealthScore(client); return <tr key={clientKey(client)} className={cn('transition-colors hover:bg-cyan-400/5', isExpired && 'bg-amber-400/5', isDepleted && 'bg-rose-500/5', !client.enable && 'bg-[#0f1420]/60 opacity-80')}><td className="px-3 py-3"><input className={checkboxClass} type="checkbox" checked={selectedClientKeys.has(clientKey(client))} onChange={() => toggleSelection(client)} /></td><td className="min-w-0 px-3 py-3"><button type="button" className={tableLongEmailClass} title={client.email} onClick={() => setExpandedKey(prev => prev === clientKey(client) ? null : clientKey(client))}>{client.email}</button><div className={tableLongIdClass} title={client.id || client.password || ''}>{client.id || client.password || '-'}</div></td><td className="px-3 py-3"><button type="button" className={cn(badgeBaseClass, 'max-w-full justify-start bg-[#0f1420] text-slate-200')} onClick={() => setFilterNode(prev => prev === client.node_name ? '' : client.node_name)}><span className="truncate">{client.node_name}</span></button></td>{!denseView && <td className="px-3 py-3"><button type="button" className={cn(badgeBaseClass, 'bg-cyan-400 text-[#06111f]')} onClick={() => setFilterProtocol(prev => prev === client.protocol ? '' : client.protocol)}>{client.protocol.toUpperCase()}</button></td>}<td className="px-3 py-3"><button type="button" className={statusChipClass(client, isExpired, isDepleted)} onClick={async () => { const identifier = clientIdentifier(client); if (!identifier) return; try { await api.put(`/v1/clients/${encodeURIComponent(identifier)}`, { node_id: client.node_id, inbound_id: client.inbound_id, updates: { email: client.email, enable: !client.enable } }, { auth: getAuth() }); setClients(prev => prev.map(c => clientKey(c) === clientKey(client) ? { ...c, enable: !c.enable } : c)); } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); } }}>{isExpired ? 'Expired' : isDepleted ? 'Depleted' : client.enable ? 'Active' : 'Disabled'}</button></td><td className="px-3 py-3"><div className="font-mono tabular-nums whitespace-nowrap">{formatBytes(downloadBytes)}</div>{client.total > 0 && <><div className="mt-1 h-1 min-w-[72px] overflow-hidden rounded-full bg-[#0f1420]"><div className={cn('h-full rounded-full', pct >= 90 ? 'bg-rose-400' : pct >= 70 ? 'bg-amber-300' : 'bg-emerald-400')} style={{ width: `${pct}%` }} /></div><div className="mt-1 font-mono text-[11px] tabular-nums text-slate-500 whitespace-nowrap">{(used / 1073741824).toFixed(1)} / {(client.total / 1073741824).toFixed(1)} GB</div></>}</td><td className="px-3 py-3 font-mono tabular-nums whitespace-nowrap">{client.total > 0 ? formatBytes(client.total) : 'unlimited'}</td><td className="px-3 py-3 font-mono tabular-nums whitespace-nowrap">{client.expiryTime > 0 ? new Date(client.expiryTime).toLocaleDateString() : t('clients.never')}</td>{!denseView && <td className="px-3 py-3 font-mono tabular-nums whitespace-nowrap text-slate-500">{lastOnlineMap[client.email] ? new Date(lastOnlineMap[client.email]).toLocaleDateString() : '-'}</td>}<td className={cn('px-3 py-3 font-mono tabular-nums font-medium whitespace-nowrap', hs >= 70 ? 'text-emerald-300' : hs >= 35 ? 'text-amber-300' : 'text-rose-300')}>{hs}</td><td className="px-3 py-3"><div className="flex flex-wrap justify-end gap-1"><button type="button" className={buttonIconClass} onClick={() => handleClientEditClick(client)} title={t('messages.editClient')}><UIIcon name="edit" size={14} /></button><button type="button" className={buttonIconClass} onClick={() => handleResetTraffic(client)} title={t('clients.resetTraffic')}><UIIcon name="refresh" size={14} /></button><button type="button" className={buttonIconClass} onClick={() => handleOpenAttach(client, 'attach')} title={t('clients.attachDetachInbounds')}><UIIcon name="attach" size={14} /></button><button type="button" className={buttonIconClass} onClick={() => handleOpenClientIpHistory(client)} title={t('clients.ipHistoryTitle')}><UIIcon name="ip" size={14} /></button><button type="button" className={cn(buttonIconClass, client.notes && 'text-cyan-300')} onClick={() => handleClientNoteClick(client)} title={t('clients.noteTitle')}><UIIcon name="note" size={14} /></button><button type="button" className={cn(buttonIconClass, 'bg-rose-500 text-white hover:bg-rose-400')} onClick={async () => { const identifier = clientIdentifier(client); if (!identifier || !client.inbound_id) { toast('Cannot identify client', 'warning'); return; } if (!window.confirm(`Delete client "${client.email}"?`)) return; try { await api.delete(`/v1/clients/${encodeURIComponent(identifier)}`, { auth: getAuth(), params: { node_id: client.node_id, inbound_id: client.inbound_id } }); loadClients(true); } catch (e: any) { toast(e.response?.data?.detail || 'Delete failed', 'error'); } }} title={t('clients.deleteClient') || 'Delete client'}><UIIcon name="trash" size={14} /></button></div></td></tr>; })}
          </tbody></table></div></div>
        </>}
        <div className="flex min-w-0 flex-wrap items-center gap-3 px-3 py-3 text-xs text-slate-500"><span className="whitespace-nowrap">{t('clients.showingCount', { filtered: filteredClients.length, total: clients.length })}</span>{selectedClientKeys.size > 0 && <span className="text-cyan-300 whitespace-nowrap">{t('clients.selectedCount', { count: selectedClientKeys.size })}</span>}</div>
      </section>
      {/* Batch Add Modal */}
      {showBatchModal && (
        <div className={modalBackdropClass}>
          <div className="my-8 w-full max-w-3xl">
            <div className={modalPanelClass}>
              <div className={modalHeaderClass}>
                <h6 className={modalTitleClass}>{t('clients.batchAddTitle')}</h6>
                <button
                  type="button"
                  className={buttonIconClass}
                  aria-label={t('common.close')}
                  onClick={() => setShowBatchModal(false)}
                >
                  X
                </button>
              </div>
              <div className={modalBodyClass}>
                <div className="mb-3">
                  <label className={fieldLabelClass}>
                    {t('clients.batchEmailsLabel')}
                  </label>
                  <textarea
                    className={inputClass}
                    rows={8}
                    value={batchText}
                    onChange={(e) => setBatchText(e.target.value)}
                    placeholder={t('clients.batchEmailsPlaceholder')}
    
                  />
                </div>
                <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-3">
                  <div className="min-w-0">
                    <label className={fieldLabelClass}>
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
                  <div className="min-w-0">
                    <label className={fieldLabelClass}>
                      {batchInboundMode === 'id' ? t('clients.inboundIdLabel') : t('clients.inboundRemarkLabel')}
                    </label>
                    {batchInboundMode === 'id' ? (
                      <input
                        type="number"
                        className={inputClass}
                        value={batchInboundId}
                        onChange={(e) => setBatchInboundId(e.target.value)}
        
                      />
                    ) : (
                      <input
                        type="text"
                        className={inputClass}
                        value={batchInboundRemark}
                        onChange={(e) => setBatchInboundRemark(e.target.value)}
                        placeholder={t('clients.inboundRemarkPlaceholder')}
        
                      />
                    )}
                  </div>
                  <div className="min-w-0">
                    <label className={fieldLabelClass}>
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
                  <div className="min-w-0">
                    <label className={fieldLabelClass}>
                      {t('clients.totalGbOptional')}
                    </label>
                    <input
                      type="number"
                      className={inputClass}
                      value={batchTotalGB}
                      onChange={(e) => setBatchTotalGB(e.target.value)}
                      placeholder="50"
      
                    />
                  </div>
                  <div className="min-w-0">
                    <label className={fieldLabelClass}>
                      {t('clients.expiryDaysOptional')}
                    </label>
                    <input
                      type="number"
                      className={inputClass}
                      value={batchExpiryDays}
                      onChange={(e) => setBatchExpiryDays(e.target.value)}
                      placeholder="30"
      
                    />
                  </div>
                  <div className="flex min-w-0 items-end">
                    <div className="flex items-center gap-2">
                      <input
                        className={checkboxClass}
                        type="checkbox"
                        id="batchEnableToggle"
                        checked={batchEnable}
                        onChange={(e) => setBatchEnable(e.target.checked)}
                      />
                      <label className="text-xs text-slate-500" htmlFor="batchEnableToggle">
                        {t('clients.enableAfterAdd')}
                      </label>
                    </div>
                  </div>
                </div>
                {inboundOptions.length > 0 && (
                  <div className="mt-3 max-h-[120px] overflow-y-auto font-mono text-xs text-slate-500">
                    {t('clients.knownInbounds')}:
                    {inboundOptions.slice(0, 40).map((ib) => (
                      <div key={`${ib.node_name}:${ib.id}`}>
                        {ib.node_name} | id={ib.id} | {ib.protocol} | {ib.remark || '-'}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className={modalFooterClass}>
                <button
                  className={buttonNeutralClass}
                  onClick={() => setShowBatchModal(false)}
                >
                  {t('common.cancel')}
                </button>
                <button
                  className={buttonAccentClass}
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

      {/* Add Client Modal */}
      {showAddForm && (
        <div className={modalBackdropClass}>
          <div className="my-8 w-full max-w-5xl">
            <div className={modalPanelClass}>
              <div className={modalHeaderClass}>
                <h6 className={modalTitleClass}>{t('common.add')}</h6>
                <button
                  type="button"
                  className={buttonIconClass}
                  aria-label={t('common.close')}
                  onClick={() => setShowAddForm(false)}
                >
                  X
                </button>
              </div>
              <div className={modalBodyClass}>
                <AddClientMultiServer />
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

      {/* Bulk Adjust Modal */}
      {showBulkAdjust && (
        <div className={modalBackdropClass} onClick={(e) => { if (e.target === e.currentTarget) setShowBulkAdjust(false); }}>
          <div className="my-8 w-full max-w-xl">
            <div className={modalPanelClass}>
              <div className={modalHeaderClass}>
                <h6 className={modalTitleClass}>{t('messages.bulkAdjustTitle')}</h6>
                <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowBulkAdjust(false)}>
                  X
                </button>
              </div>
              <div className={modalBodyClass}>
                <p className="mb-2 text-xs text-slate-500">{t('clients.bulkAdjustScopeHint')}</p>
                <div className="mb-3 flex gap-2">
                  <button className={bulkAdjustMode === 'add' ? buttonAccentClass : buttonNeutralClass}
                    onClick={() => setBulkAdjustMode('add')}>+ Add Days / GB</button>
                  <button className={bulkAdjustMode === 'set' ? buttonAccentClass : buttonNeutralClass}
                    onClick={() => setBulkAdjustMode('set')}>Set Exact Expiry</button>
                </div>
                {bulkAdjustMode === 'add' ? (
                  <>
                    <div className="mb-3">
                      <label className={fieldLabelClass}>{t('messages.bulkAdjustAddDays')}</label>
                      <input type="number" className={inputClass} value={bulkAdjustDays} onChange={(e) => setBulkAdjustDays(e.target.value)}
                         />
                    </div>
                    <div className="mb-3">
                      <label className={fieldLabelClass}>{t('messages.bulkAdjustAddGB')}</label>
                      <input type="number" step="1" className={inputClass} value={bulkAdjustGB} onChange={(e) => setBulkAdjustGB(e.target.value)}
                         />
                    </div>
                  </>
                ) : (
                  <div className="mb-3">
                    <label className={fieldLabelClass}>{t('clients.setExpiryForSelected')}</label>
                    <input type="date" className={inputClass} value={bulkSetExpiryDate} onChange={e => setBulkSetExpiryDate(e.target.value)}
                       />
                    <div className="mt-1 text-xs text-slate-500">{t('clients.setExpiryOverwriteHint')}</div>
                  </div>
                )}
              </div>
              <div className={modalFooterClass}>
                <button className={buttonNeutralClass} onClick={() => setShowBulkAdjust(false)}>{t('common.cancel')}</button>
                <button className={buttonAccentClass} onClick={handleBulkAdjust} disabled={bulkAdjustLoading}>{bulkAdjustLoading ? '...' : t('messages.bulkAdjustApply')}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Attach/Detach Inbounds Modal */}
      {showAttachModal && attachClient && (
        <div className={modalBackdropClass} onClick={e => { if (e.target === e.currentTarget) setShowAttachModal(false); }}>
          <div className="my-8 w-full max-w-xl">
            <div className={modalPanelClass}>
              <div className={modalHeaderClass}>
                <h6 className={modalTitleClass}>Inbounds - {attachClient.email}</h6>
                <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowAttachModal(false)}>
                  X
                </button>
              </div>
              <div className={modalBodyClass}>
                <div className="mb-3 flex gap-2">
                  <button className={attachMode === 'attach' ? buttonAccentClass : buttonNeutralClass}
                    onClick={() => setAttachMode('attach')}>Attach</button>
                  <button className={attachMode === 'detach' ? buttonDangerClass : buttonNeutralClass}
                    onClick={() => setAttachMode('detach')}>Detach</button>
                </div>
                <p className="mb-2 text-xs text-slate-500">
                  Select inbounds to {attachMode} this client {attachMode === 'attach' ? 'to' : 'from'}:
                </p>
                {attachLoading && <div className="py-2 text-center"><div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-500/20 border-t-cyan-300" /></div>}
                {!attachLoading && attachInbounds.length === 0 && <p className="text-sm text-slate-500">{t('clients.noInboundsForNode')}</p>}
                <div className="mb-3 flex flex-col gap-1">
                  {attachInbounds.map(ib => (
                    <label key={ib.id} className="flex cursor-pointer items-center gap-2 rounded-md bg-[#0a0e1a] p-2">
                      <input type="checkbox" checked={attachSelected.has(ib.id)}
                        onChange={e => {
                          setAttachSelected(prev => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(ib.id); else next.delete(ib.id);
                            return next;
                          });
                        }} />
                      <span className="min-w-0 truncate text-slate-100">{ib.remark || `#${ib.id}`}</span>
                      <span className={cn(badgeBaseClass, 'ml-auto bg-cyan-400 text-[#06111f]')}>{ib.protocol.toUpperCase()}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className={modalFooterClass}>
                <button className={buttonNeutralClass}
                  onClick={() => setShowAttachModal(false)}>Cancel</button>
                <button className={attachMode === 'attach' ? buttonAccentClass : buttonDangerClass}
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
        <div className={modalBackdropClass} onClick={(e) => { if (e.target === e.currentTarget) setShowGroupsModal(false); }}>
          <div className="my-8 w-full max-w-3xl">
            <div className={modalPanelClass}>
              <div className={modalHeaderClass}>
                <h6 className={modalTitleClass}>Client Groups{groupsNodeName ? ` - ${groupsNodeName}` : ''}</h6>
                <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowGroupsModal(false)}>
                  X
                </button>
              </div>
              <div className={modalBodyClass}>
                {/* Node selector if no node chosen yet */}
                {!groupsNodeId && (
                  <div className="mb-3">
                    <label className={fieldLabelClass}>{t('clients.selectNode')}</label>
                    <div className="flex flex-wrap gap-2">
                      {Array.from(new Map(clients.filter(c => c.node_id).map(c => [c.node_name, c.node_id!]))).map(([name, id]) => (
                        <button key={id} className={buttonAccentClass}
                          onClick={() => handleOpenGroups(id, name)}>
                          {name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {groupsNodeId && (
                  <>
                    {groupsLoading && <div className="py-2 text-center"><div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-500/20 border-t-cyan-300" /></div>}

                    {/* Create group */}
                    <div className="mb-3 flex gap-2">
                      <input className={inputClass} placeholder={t('clients.newGroupName')} value={groupNewName}
                        onChange={e => setGroupNewName(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleCreateGroup(); }}
                         />
                      <button className={buttonAccentClass}
                        onClick={handleCreateGroup} disabled={!groupNewName.trim()}>{t('clients.createWithPlus')}</button>
                    </div>

                    {/* Rename group */}
                    {groupRenameFrom && (
                      <div className="mb-3 flex gap-2 rounded-md bg-[#0a0e1a] p-2">
                        <span className="self-center text-xs text-slate-500">Rename "{groupRenameFrom}":</span>
                        <input className={inputClass} placeholder={t('common.name')} value={groupRenameTo}
                          onChange={e => setGroupRenameTo(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') handleRenameGroup(); }}
                           />
                        <button className={buttonAccentClass}
                          onClick={handleRenameGroup} disabled={!groupRenameTo.trim()}>Save</button>
                        <button className={buttonNeutralClass}
                          onClick={() => { setGroupRenameFrom(''); setGroupRenameTo(''); }}>Cancel</button>
                      </div>
                    )}

                    {/* Groups list */}
                    {!groupsLoading && groupsList.length === 0 && (
                      <p className="text-sm text-slate-500">{t('clients.noGroupsYet')}</p>
                    )}
                    <div className="flex flex-col gap-2">
                      {groupsList.map(group => (
                        <div key={group}>
                          <div className="flex items-center justify-between rounded-md bg-[#0a0e1a] p-2">
                            <span className="font-semibold text-slate-100">{group}</span>
                            <div className="flex gap-1">
                              <button className={cn(buttonNeutralClass, 'h-7 px-2 text-[11px]')}
                                onClick={() => handleViewGroupMembers(group)}>
                                {showGroupMembers === group ? 'Hide' : 'Members'}
                              </button>
                              <button className={cn(buttonNeutralClass, 'h-7 px-2 text-[11px]')}
                                onClick={() => { setGroupRenameFrom(group); setGroupRenameTo(group); }} title="Rename">Rename</button>
                              <button className={cn(buttonDangerClass, 'h-7 px-2 text-[11px]')}
                                onClick={() => handleDeleteGroup(group)} title="Delete">Delete</button>
                            </div>
                          </div>

                          {/* Members panel */}
                          {showGroupMembers === group && (
                            <div className="mt-1 ml-2 rounded border border-cyan-500/20 bg-[#0a0e1a] p-2">
                              {groupMembersLoading && <div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-500/20 border-t-cyan-300" />}
                              {!groupMembersLoading && groupMemberEmails.length === 0 && (
                                <p className="mb-2 text-xs text-slate-500">{t('clients.noMembers')}</p>
                              )}
                              <div className="mb-2 flex flex-wrap gap-1">
                                {groupMemberEmails.map(email => (
                                  <span key={email} className={cn(badgeBaseClass, 'gap-1 bg-[#0f1420] font-mono font-normal text-slate-200')}>
                                    {email}
                                    <button className={cn(buttonIconClass, 'h-6 w-6 bg-transparent text-rose-300')}
                                      onClick={() => handleRemoveFromGroup(group, email)} title="Remove">x</button>
                                  </span>
                                ))}
                              </div>
                              <div className="flex gap-2">
                                <input className={inputClass} placeholder={t('clients.groupEmailsPlaceholder')}
                                  value={groupAddEmails} onChange={e => setGroupAddEmails(e.target.value)}
                                   />
                                <button className={buttonAccentClass}
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

      {/* Client IP History Modal */}
      {ipHistoryClient && (
        <div className={modalBackdropClass} onClick={e => { if (e.target === e.currentTarget) setIpHistoryClient(null); }}>
          <div className="my-8 w-full max-w-xl">
            <div className={modalPanelClass}>
              <div className={modalHeaderClass}>
                <h6 className={modalTitleClass}>{t('clients.ipHistoryTitle')} - {ipHistoryClient.email}</h6>
                <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setIpHistoryClient(null)}>
                  <UIIcon name="x" size={14} />
                </button>
              </div>
              <div className={modalBodyClass}>
                <div className="mb-3 flex min-w-0 flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className={cn(badgeBaseClass, 'bg-[#0a0e1a] font-mono text-slate-300')}>{ipHistoryClient.node_name || '-'}</span>
                  {ipHistoryClient.node_id != null && <span className="font-mono">node_id={ipHistoryClient.node_id}</span>}
                </div>
                {ipHistoryLoading && (
                  <div className="flex items-center gap-2 py-3 text-sm text-slate-500">
                    <UIIcon name="spinner" size={14} className="animate-spin text-cyan-300" />
                    <span>{t('clients.ipHistoryLoading')}</span>
                  </div>
                )}
                {!ipHistoryLoading && ipHistoryError && <div className={tableErrorClass}>{ipHistoryError}</div>}
                {!ipHistoryLoading && !ipHistoryError && ipHistoryEntries.length === 0 && (
                  <p className="rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-3 text-sm text-slate-500">{t('clients.ipHistoryEmpty')}</p>
                )}
                {!ipHistoryLoading && ipHistoryEntries.length > 0 && (
                  <div className="flex flex-col gap-2">
                    {ipHistoryEntries.map((entry) => (
                      <div key={entry.node} className="rounded-md border border-cyan-500/20 bg-[#0a0e1a] p-3">
                        <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                          <strong className="min-w-0 truncate text-sm text-slate-100">{entry.node}</strong>
                          <span className={cn(badgeBaseClass, 'bg-cyan-400/10 text-cyan-200')}>{entry.ips.length}</span>
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {entry.ips.map((ip) => (
                            <span key={`${entry.node}:${ip}`} className={cn(badgeBaseClass, 'bg-[#0f1420] font-mono text-slate-300')}>{ip}</span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className={modalFooterClass}>
                <button className={buttonNeutralClass} onClick={() => setIpHistoryClient(null)}>{t('common.close')}</button>
                <button className={buttonDangerClass} onClick={handleClearClientIpHistory} disabled={ipHistoryLoading || ipHistoryClearing}>
                  <span className="inline-flex items-center gap-1"><UIIcon name={ipHistoryClearing ? 'spinner' : 'clear'} size={14} className={ipHistoryClearing ? 'animate-spin' : undefined} />{ipHistoryClearing ? '...' : t('clients.clearStoredIps')}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* IP Search Modal */}
      {showIpSearch && (
        <div className={modalBackdropClass} onClick={e => { if (e.target === e.currentTarget) setShowIpSearch(false); }}>
          <div className="my-8 w-full max-w-3xl">
            <div className={modalPanelClass}>
              <div className={modalHeaderClass}>
                <h6 className={modalTitleClass}>{t('clients.findByIpModalTitle')}</h6>
                <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowIpSearch(false)}>
                  X
                </button>
              </div>
              <div className={modalBodyClass}>
                <p className="mb-2 text-xs text-slate-500">
                  {t('clients.findByIpModalHint')}
                </p>
                <div className="mb-3 flex gap-2">
                  <input
                    className={inputClass}
                    placeholder={t('clients.ipPlaceholder')}
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
                    className={buttonAccentClass}
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
                    {ipSearchLoading ? '...' : 'Search'}
                  </button>
                </div>
                {ipSearchLoading && <div className="py-3 text-center"><div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-500/20 border-t-cyan-300" /></div>}
                {!ipSearchLoading && ipSearchResults.length === 0 && ipSearchValue && (
                  <p className="text-sm text-slate-500">No clients found with IP {ipSearchValue}</p>
                )}
                {ipSearchResults.length > 0 && (
                  <div className="flex flex-col gap-2">
                    <div className="mb-1 text-xs text-emerald-300">{ipSearchResults.length} match(es) found</div>
                    {ipSearchResults.map((r, i) => (
                      <div key={i} className="rounded bg-[#0a0e1a] p-2">
                        <div className="flex items-center gap-2">
                          <strong className="min-w-0 truncate font-mono text-slate-100">{r.email}</strong>
                          <span className={cn(badgeBaseClass, 'bg-cyan-400 text-[#06111f]')}>{r.node}</span>
                        </div>
                        <div className="mt-1 font-mono text-xs text-slate-500">
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
