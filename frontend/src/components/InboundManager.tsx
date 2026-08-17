import React, { useCallback, useRef, useState, useEffect } from 'react';
import { useToast } from './Toast';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { getInboundsHeaderSource } from '../api/dashboard';
import { listNodes } from '../api/nodes';
import { UIIcon } from './UIIcon';
import { InboundEditModal } from './InboundEditModal';
import { readStaleCache, writeStaleCache } from '../services/staleCache';
import { useTrafficStatsSubscription, TrafficUpdate } from '../services/useTrafficStatsSubscription';

interface Inbound {
  id: number;
  node_id?: number | null;
  node_name: string;
  node_ip: string;
  protocol: string;
  port: number;
  remark: string;
  enable: boolean;
  security: string;
  is_reality: boolean;
  client_count?: number;
  streamSettings?: Record<string, any>;
  settings?: Record<string, any>;
}

interface NodeInfo {
  id: number;
  name: string;
}

interface InboundStats {
  total: number;
  enabled: number;
  disabled: number;
  by_protocol: Record<string, number>;
  by_security: Record<string, number>;
}

interface InboundTemplateMap {
  [key: string]: Record<string, any>;
}

interface InboundsPageCache {
  ts: number;
  inbounds: Inbound[];
  allNodes: NodeInfo[];
  nodeNameToId: Record<string, number>;
  filterProtocol: string;
  filterSecurity: string;
  filterNode: string;
  sortField: 'name' | 'node' | 'protocol' | 'port' | 'status' | 'clients';
  sortDirection: 'asc' | 'desc';
}

const parseMaybeJsonObject = (value: any): Record<string, any> => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value;
  }
  if (typeof value !== 'string' || value.trim() === '') {
    return {};
  }
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
};

const INBOUND_TEMPLATES: InboundTemplateMap = {
  vless: {
    port: 8443,
    protocol: 'vless',
    remark: 'vless-inbound',
    enable: true,
    expiryTime: 0,
    listen: '',
    total: 0,
    settings: JSON.stringify({
      clients: [],
      decryption: 'none',
      fallbacks: [],
    }),
    streamSettings: JSON.stringify({
      network: 'tcp',
      security: 'reality',
      realitySettings: {
        show: false,
        dest: 'www.cloudflare.com:443',
        xver: 0,
        serverNames: ['www.cloudflare.com'],
        privateKey: '',
        shortIds: [''],
        settings: {
          publicKey: '',
          fingerprint: 'chrome',
        },
      },
    }),
    sniffing: JSON.stringify({
      enabled: true,
      destOverride: ['http', 'tls'],
      metadataOnly: false,
    }),
  },
  vmess: {
    port: 20000,
    protocol: 'vmess',
    remark: 'vmess-inbound',
    enable: true,
    expiryTime: 0,
    listen: '',
    total: 0,
    settings: JSON.stringify({
      clients: [],
      disableInsecureEncryption: false,
    }),
    streamSettings: JSON.stringify({
      network: 'ws',
      security: 'tls',
      wsSettings: { path: '/vmess', headers: {} },
      tlsSettings: { serverName: '' },
    }),
    sniffing: JSON.stringify({
      enabled: true,
      destOverride: ['http', 'tls'],
      metadataOnly: false,
    }),
  },
  trojan: {
    port: 443,
    protocol: 'trojan',
    remark: 'trojan-inbound',
    enable: true,
    expiryTime: 0,
    listen: '',
    total: 0,
    settings: JSON.stringify({
      clients: [],
      fallbacks: [],
    }),
    streamSettings: JSON.stringify({
      network: 'tcp',
      security: 'tls',
      tlsSettings: { serverName: '' },
    }),
    sniffing: JSON.stringify({
      enabled: true,
      destOverride: ['http', 'tls'],
      metadataOnly: false,
    }),
  },
};

interface InboundManagerProps {
  onReload?: () => void;
  onNavigateToClients?: (inboundId: number, inboundRemark: string) => void;
  onAddClientToInbound?: (inboundId: number, nodeName: string) => void;
}

const inboundKey = (ib: Inbound) => `${ib.node_name}:${ib.id}`;
const INBOUNDS_PAGE_CACHE_KEY = 'sub_manager_inbounds_page_cache_v1';

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const extractInboundArray = (payload: unknown): unknown[] => {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    if (Array.isArray(record.inbounds)) return record.inbounds;
    if (Array.isArray(record.data)) return record.data;
  }
  return [];
};

const normalizeInboundRows = (
  payload: unknown,
  nodeNameToId: Record<string, number> = {},
): Inbound[] => extractInboundArray(payload).map((ib: any) => {
  const streamSettings = parseMaybeJsonObject(ib.streamSettings);
  const settings = parseMaybeJsonObject(ib.settings);
  const security = ib.security || streamSettings.security || '';
  const nodeName = ib.node_name || ib.node || '';
  return {
    id: Number(ib.id || 0),
    node_id: ib.node_id ?? nodeNameToId[nodeName] ?? null,
    node_name: nodeName,
    node_ip: ib.node_ip || nodeName,
    protocol: ib.protocol || '',
    port: Number(ib.port || 0),
    remark: ib.remark || '',
    enable: Boolean(ib.enable),
    security,
    is_reality: Boolean(ib.is_reality ?? security === 'reality'),
    client_count: Number.isFinite(Number(ib.client_count)) ? Number(ib.client_count) : undefined,
    settings: Object.keys(settings).length > 0 ? settings : undefined,
    streamSettings: Object.keys(streamSettings).length > 0 ? streamSettings : undefined,
  };
});

const normalizeInboundStats = (payload: any): InboundStats => ({
  total: Number(payload?.total || 0),
  enabled: Number(payload?.enabled || 0),
  disabled: Number(payload?.disabled || 0),
  by_protocol: payload?.by_protocol && typeof payload.by_protocol === 'object' ? payload.by_protocol : {},
  by_security: payload?.by_security && typeof payload.by_security === 'object' ? payload.by_security : {},
});

const panelTitleClass = 'text-xs font-medium uppercase tracking-[0.14em] text-cyan-300';
const panelHintClass = 'mt-1 text-xs font-light leading-5 text-slate-500';
const fieldLabelClass = 'mb-1 block text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500';
const inputClass = 'box-border min-w-0 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 font-mono text-xs font-light text-slate-100 outline-none transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10 disabled:cursor-not-allowed disabled:opacity-50 placeholder:text-slate-600';
const textareaClass = `${inputClass} w-full resize-y leading-relaxed`;
const checkboxClass = 'h-4 w-4 shrink-0 rounded bg-[#0a0e1a] accent-cyan-300';
const buttonBaseClass = 'inline-flex h-8 min-w-0 items-center justify-center gap-1 whitespace-nowrap rounded-md border border-transparent px-3 text-xs font-medium leading-none tracking-wide transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-45';
const buttonNeutralClass = `${buttonBaseClass} border-cyan-500/20 bg-[#0f1420] text-slate-200 hover:bg-[#0a0e1a]`;
const buttonAccentClass = `${buttonBaseClass} border-cyan-300/25 bg-cyan-400 text-[#06111f] hover:bg-cyan-300`;
const buttonSuccessClass = `${buttonBaseClass} bg-emerald-500 text-white hover:bg-emerald-400`;
const buttonWarningClass = `${buttonBaseClass} bg-amber-400 text-[#06111f] hover:bg-amber-300`;
const buttonDangerClass = `${buttonBaseClass} bg-rose-500 text-white hover:bg-rose-400`;
const buttonGhostClass = `${buttonBaseClass} border-cyan-300/20 bg-transparent text-cyan-300 hover:bg-cyan-400/10`;
const buttonIconClass = 'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0f1420] text-slate-300 transition-colors hover:bg-[#0a0e1a] hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-45';
const sortButtonClass = 'inline-flex items-center gap-1 whitespace-nowrap text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500 transition-colors hover:text-cyan-300';
const badgeBaseClass = 'inline-flex min-w-0 items-center justify-center whitespace-nowrap rounded-md border border-cyan-500/20 px-2 py-1 text-[11px] font-medium leading-none';
const drawerPanelClass = 'fixed inset-y-2 right-2 z-50 flex w-[calc(100%-1rem)] max-w-[520px] flex-col overflow-hidden rounded-lg border border-cyan-300/20 bg-[#0f1420] shadow-2xl ring-1 ring-cyan-300/10 sm:w-[min(92vw,520px)]';
const drawerPanelWideClass = 'fixed inset-y-2 right-2 z-50 flex w-[calc(100%-1rem)] max-w-[760px] flex-col overflow-hidden rounded-lg border border-cyan-300/20 bg-[#0f1420] shadow-2xl ring-1 ring-cyan-300/10 sm:w-[min(94vw,760px)]';
const drawerHeaderClass = 'flex min-w-0 items-start justify-between gap-4 border-b border-cyan-300/20 px-5 py-4';
const drawerBodyClass = 'min-w-0 flex-1 overflow-y-auto p-5';
const drawerFooterClass = 'flex flex-wrap justify-end gap-2 border-t border-cyan-300/20 px-5 py-4';
const drawerTitleClass = 'min-w-0 truncate text-sm font-medium uppercase tracking-[0.16em] text-cyan-300';
const drawerSubtitleClass = 'mt-1 min-w-0 truncate text-xs font-light text-slate-500';
const tableSkeletonLineClass = 'block animate-pulse rounded bg-[#182133]';
const tableStateChipClass = 'inline-flex min-w-0 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0f1420] px-3 py-2 font-mono text-[11px] font-light uppercase tracking-[0.14em] text-slate-400';
const tableErrorClass = 'mb-4 min-w-0 overflow-hidden rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 font-mono text-[11px] font-light text-rose-200/90 shadow-[inset_0_1px_0_rgba(251,113,133,0.08)]';
const inboundLongValueClass = 'block min-w-0 max-w-[150px] truncate md:max-w-[220px] lg:max-w-xs';

const segmentButtonClass = (active: boolean) =>
  cn(
    buttonBaseClass,
    'h-7 px-2 text-[11px]',
    active ? 'bg-cyan-400 text-[#06111f]' : 'bg-[#0a0e1a] text-slate-400 hover:bg-[#0f1420] hover:text-slate-100',
  );

const nodeCheckClass = (active: boolean) =>
  cn(
    'inline-flex min-w-0 cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-xs transition-colors',
    active ? 'bg-cyan-400/15 text-cyan-200' : 'bg-[#0a0e1a] text-slate-400 hover:bg-[#0f1420] hover:text-slate-100',
  );

const InboundTableSkeleton = () => (
  <div className="min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a]">
    <div className="grid min-w-0 grid-cols-1 gap-3 p-3 lg:hidden">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="min-h-[128px] animate-pulse rounded-lg bg-[#0f1420] p-3 ring-1 ring-cyan-500/10">
          <div className="grid grid-cols-[20px_minmax(0,1fr)_68px] items-start gap-3">
            <span className={`${tableSkeletonLineClass} h-4 w-4`} />
            <div className="min-w-0 space-y-2">
              <span className={`${tableSkeletonLineClass} h-4 w-3/4`} />
              <span className={`${tableSkeletonLineClass} h-3 w-20`} />
            </div>
            <span className={`${tableSkeletonLineClass} h-7 w-full`} />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((__, chipIndex) => (
              <span key={chipIndex} className={`${tableSkeletonLineClass} h-7 w-full`} />
            ))}
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-8">
            {Array.from({ length: 8 }).map((__, actionIndex) => (
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
            {['w-10', 'w-[12%]', 'w-[18%]', 'w-[8%]', 'w-[8%]', 'w-[9%]', 'w-[10%]', 'w-[6%]', 'w-[156px]'].map((width, index) => (
              <th key={index} className={`${width} px-3 py-3`}>
                <span className={`${tableSkeletonLineClass} h-3 w-16`} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-900">
          {Array.from({ length: 8 }).map((_, rowIndex) => (
            <tr key={rowIndex}>
              {Array.from({ length: 9 }).map((__, cellIndex) => (
                <td key={cellIndex} className="px-3 py-3">
                  <span className={`${tableSkeletonLineClass} h-4 ${cellIndex === 2 ? 'w-full' : 'w-16'}`} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

export const InboundManager: React.FC<InboundManagerProps> = ({ onReload, onNavigateToClients, onAddClientToInbound }) => {
  const { toast } = useToast();
  const { t } = useTranslation();

  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const inboundsRef = useRef<Inbound[]>([]);
  const [filteredInbounds, setFilteredInbounds] = useState<Inbound[]>([]);
  const [nodeNameToId, setNodeNameToId] = useState<Record<string, number>>({});
  const [allNodes, setAllNodes] = useState<NodeInfo[]>([]);
  const [inboundStats, setInboundStats] = useState<InboundStats | null>(null);

  const [loading, setLoading] = useState(false);
  const [pageLoading, setPageLoading] = useState(false);
  const [error, setError] = useState('');

  const [ibPage, setIbPage] = useState(1);
  const [ibPageSize, setIbPageSize] = useState(50);
  const IB_FILTER_KEY = 'sub_manager_inbound_filters_v1';
  const _ibSaved = (() => { try { return JSON.parse(localStorage.getItem(IB_FILTER_KEY) || '{}'); } catch { return {}; } })();
  const [filterProtocol, setFilterProtocol] = useState<string>(_ibSaved.filterProtocol ?? '');
  const [filterSecurity, setFilterSecurity] = useState<string>(_ibSaved.filterSecurity ?? '');
  const [filterNode, setFilterNode] = useState<string>(_ibSaved.filterNode ?? '');
  const [filterEmptyOnly, setFilterEmptyOnly] = useState<boolean>(_ibSaved.filterEmptyOnly ?? false);
  const [filterEnabledStatus, setFilterEnabledStatus] = useState<'all' | 'enabled' | 'disabled'>(_ibSaved.filterEnabledStatus ?? 'all');
  const [filterDuplicatesOnly, setFilterDuplicatesOnly] = useState<boolean>(_ibSaved.filterDuplicatesOnly ?? false);
  const [searchTerm, setSearchTerm] = useState<string>(_ibSaved.searchTerm ?? '');
  const [sortField, setSortField] = useState<'name' | 'node' | 'protocol' | 'port' | 'status' | 'clients'>(_ibSaved.sortField ?? 'name');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>(_ibSaved.sortDirection ?? 'asc');

  const [showCloneModal, setShowCloneModal] = useState(false);
  const [cloneSource, setCloneSource] = useState<Inbound | null>(null);
  const [cloneRemark, setCloneRemark] = useState('');
  const [clonePort, setClonePort] = useState('');
  const [cloneTargetNodeIds, setCloneTargetNodeIds] = useState<Set<number>>(new Set());

  const [showAddModal, setShowAddModal] = useState(false);
  const [addTemplateProtocol, setAddTemplateProtocol] = useState<'vless' | 'vmess' | 'trojan'>('vless');
  const [addJsonConfig, setAddJsonConfig] = useState(JSON.stringify(INBOUND_TEMPLATES.vless, null, 2));
  const [addTargetNodeIds, setAddTargetNodeIds] = useState<Set<number>>(new Set());
  // Import JSON modal
  const [showImportModal, setShowImportModal] = useState(false);
  const [importJson, setImportJson] = useState('');
  const [importTargetNodeIds, setImportTargetNodeIds] = useState<Set<number>>(new Set());
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState('');
  const [importResult, setImportResult] = useState<string>('');

  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [batchRemark, setBatchRemark] = useState('');
  const [batchEnableMode, setBatchEnableMode] = useState<'none' | 'enable' | 'disable'>('none');
  const requestIdRef = useRef(0);
  const inboundsAbortRef = useRef<AbortController | null>(null);

  // Inbound config viewer modal
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [configModalInbound, setConfigModalInbound] = useState<Inbound | null>(null);

  const [editingInbound, setEditingInbound] = useState<Inbound | null>(null);

  useEffect(() => {
    inboundsRef.current = inbounds;
  }, [inbounds]);

  useEffect(() => {
    // Always show stale data instantly (stale-while-revalidate), then refresh in background.
    const cached = readStaleCache<InboundsPageCache>(INBOUNDS_PAGE_CACHE_KEY, Number.MAX_SAFE_INTEGER);
    if (cached.data) {
      const parsed = cached.data;
      if (Array.isArray(parsed.inbounds)) setInbounds(parsed.inbounds);
      if (Array.isArray(parsed.allNodes)) {
        setAllNodes(parsed.allNodes);
        if (addTargetNodeIds.size === 0) {
          setAddTargetNodeIds(new Set(parsed.allNodes.map((node) => node.id)));
        }
      }
      if (parsed.nodeNameToId && typeof parsed.nodeNameToId === 'object') {
        setNodeNameToId(parsed.nodeNameToId);
      }
      if (typeof parsed.filterProtocol === 'string') setFilterProtocol(parsed.filterProtocol);
      if (typeof parsed.filterSecurity === 'string') setFilterSecurity(parsed.filterSecurity);
      if (typeof parsed.filterNode === 'string') setFilterNode(parsed.filterNode);
      if (parsed.sortField) setSortField(parsed.sortField);
      if (parsed.sortDirection) setSortDirection(parsed.sortDirection);
    }

    // Refresh silently if cache is fresh enough, otherwise show spinner.
    loadInbounds(cached.isFresh ? true : false);
    return () => inboundsAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    writeStaleCache<InboundsPageCache>(INBOUNDS_PAGE_CACHE_KEY, {
      ts: Date.now(),
      inbounds,
      allNodes,
      nodeNameToId,
      filterProtocol,
      filterSecurity,
      filterNode,
      sortField,
      sortDirection,
    });
  }, [
    inbounds,
    allNodes,
    nodeNameToId,
    filterProtocol,
    filterSecurity,
    filterNode,
    filterEmptyOnly,
    searchTerm,
    sortField,
    sortDirection,
  ]);

  // Persist filter changes
  useEffect(() => {
    try { localStorage.setItem(IB_FILTER_KEY, JSON.stringify({ filterProtocol, filterSecurity, filterNode, filterEmptyOnly, filterEnabledStatus, filterDuplicatesOnly, searchTerm, sortField, sortDirection })); } catch {}
    setIbPage(1);
  }, [filterProtocol, filterSecurity, filterNode, filterEmptyOnly, filterEnabledStatus, filterDuplicatesOnly, searchTerm, sortField, sortDirection]);

  useEffect(() => {
    let filtered = inbounds;

    if (filterProtocol) {
      filtered = filtered.filter((ib) => ib.protocol === filterProtocol);
    }

    if (filterSecurity) {
      filtered = filtered.filter((ib) => ib.security === filterSecurity);
    }

    if (filterNode) {
      filtered = filtered.filter((ib) => ib.node_name === filterNode);
    }

    if (filterEmptyOnly) {
      filtered = filtered.filter((ib) => (ib.client_count ?? 0) === 0);
    }
    if (filterEnabledStatus === 'enabled') {
      filtered = filtered.filter(ib => ib.enable);
    } else if (filterEnabledStatus === 'disabled') {
      filtered = filtered.filter(ib => !ib.enable);
    }
    if (filterDuplicatesOnly) {
      filtered = filtered.filter(ib => isDuplicatePort(ib));
    }

    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      filtered = filtered.filter((ib) =>
        ib.remark.toLowerCase().includes(q) ||
        String(ib.port).includes(q) ||
        ib.node_name.toLowerCase().includes(q)
      );
    }

    const factor = sortDirection === 'asc' ? 1 : -1;
    const compareText = (a: string, b: string) =>
      a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });

    const sorted = [...filtered].sort((a, b) => {
      const aName = a.remark || '';
      const bName = b.remark || '';
      const byName = compareText(aName, bName);
      const byNode = compareText(a.node_name, b.node_name);
      const byProtocol = compareText(a.protocol, b.protocol);
      const byPort = a.port - b.port;
      const byStatus = Number(a.enable) - Number(b.enable);

      if (sortField === 'name') {
        if (byName !== 0) return byName * factor;
        if (byNode !== 0) return byNode * factor;
        return (a.id - b.id) * factor;
      }
      if (sortField === 'node') {
        if (byNode !== 0) return byNode * factor;
        if (byName !== 0) return byName * factor;
        return (a.id - b.id) * factor;
      }
      if (sortField === 'protocol') {
        if (byProtocol !== 0) return byProtocol * factor;
        if (byName !== 0) return byName;
        if (byNode !== 0) return byNode;
        return a.id - b.id;
      }
      if (sortField === 'port') {
        if (byPort !== 0) return byPort * factor;
        if (byName !== 0) return byName;
        if (byNode !== 0) return byNode;
        return a.id - b.id;
      }

      if (sortField === 'clients') {
        const byClients = (a.client_count ?? 0) - (b.client_count ?? 0);
        if (byClients !== 0) return byClients * factor;
        if (byName !== 0) return byName;
        return byNode;
      }

      if (byStatus !== 0) return byStatus * factor;
      if (byName !== 0) return byName;
      if (byNode !== 0) return byNode;
      return a.id - b.id;
    });

    setFilteredInbounds(sorted);
  }, [
    inbounds,
    filterProtocol,
    filterSecurity,
    filterNode,
    filterEmptyOnly,
    filterEnabledStatus,
    filterDuplicatesOnly,
    searchTerm,
    sortField,
    sortDirection,
  ]);

  const loadInbounds = async (silent = false) => {
    inboundsAbortRef.current?.abort();
    const controller = new AbortController();
    inboundsAbortRef.current = controller;
    if (!silent) setPageLoading(true);
    setError('');

    const requestId = Date.now();
    requestIdRef.current = requestId;

    try {
      // Single parallel fetch â€” backend returns from cache (30s fresh / 300s stale).
      const inboundStatsPromise = api
        .get('/v1/inbounds/stats', { auth: getAuth(), signal: controller.signal })
        .then((res) => normalizeInboundStats(res.data))
        .catch(() => null);

      const [nodes, rawInbounds, stats] = await Promise.all([
        listNodes({ signal: controller.signal }),
        getInboundsHeaderSource({ signal: controller.signal }),
        inboundStatsPromise,
      ]);

      if (requestIdRef.current !== requestId) return;

      const nameMap: Record<string, number> = {};
      nodes.forEach((n) => { nameMap[n.name] = n.id; });

      setAllNodes(nodes);
      setNodeNameToId(nameMap);
      setInboundStats(stats);
      if (addTargetNodeIds.size === 0) {
        setAddTargetNodeIds(new Set(nodes.map((n) => n.id)));
      }

      const normalized = normalizeInboundRows(rawInbounds, nameMap);

      setInbounds(normalized);
      if (!silent) setPageLoading(false);

    } catch (err: any) {
      if (controller.signal.aborted || err?.code === 'ERR_CANCELED') return;
      setError(err.response?.data?.detail || t('messages.operationFailed'));
      if (!silent) setPageLoading(false);
    }
  };

  const handleRealtimeUpdate = useCallback(
    (update: TrafficUpdate) => {
      if (update.type !== 'inbound_update') return;

      if (update.data?.source === 'snapshot_collector') {
        if (update.data?.has_table_payload && Array.isArray(update.data.inbounds)) {
          const incoming = normalizeInboundRows(update.data.inbounds, nodeNameToId);
          const nodeId = update.data.node_id != null ? Number(update.data.node_id) : null;
          const nodeName = String(update.data.node || update.data.node_name || '');
          const retained = inboundsRef.current.filter((ib) => {
            if (nodeId !== null && ib.node_id != null) {
              return Number(ib.node_id) !== nodeId;
            }
            return ib.node_name !== nodeName;
          });

          const deduped = new Map<string, Inbound>();
          [...retained, ...incoming].forEach((ib) => deduped.set(inboundKey(ib), ib));
          const nextInbounds = Array.from(deduped.values());
          inboundsRef.current = nextInbounds;
          setInbounds(nextInbounds);
          writeStaleCache<InboundsPageCache>(INBOUNDS_PAGE_CACHE_KEY, {
            ts: Date.now(),
            inbounds: nextInbounds,
            allNodes,
            nodeNameToId,
            filterProtocol,
            filterSecurity,
            filterNode,
            sortField,
            sortDirection,
          });
        }
        return;
      }

      void loadInbounds(true);
    },
    [allNodes, filterNode, filterProtocol, filterSecurity, loadInbounds, nodeNameToId, sortDirection, sortField],
  );

  useTrafficStatsSubscription({
    channels: ['inbounds'],
    onUpdate: handleRealtimeUpdate,
    onError: (err) => console.warn('[InboundManager] realtime error:', err),
    fallbackPollIntervalMs: 5 * 60 * 1000,
    fallbackRun: () => loadInbounds(true),
  });

  const selectedInbounds = inbounds.filter((ib) => selectedKeys.has(inboundKey(ib)));
  const selectedInboundIds = Array.from(new Set(selectedInbounds.map((ib) => ib.id)));
  const selectedNodeIds = Array.from(
    new Set(selectedInbounds.map((ib) => nodeNameToId[ib.node_name]).filter((id): id is number => Number.isInteger(id)))
  );

  const toggleSelectAllFiltered = () => {
    const next = new Set(selectedKeys);
    const filteredKeys = filteredInbounds.map((ib) => inboundKey(ib));
    const allSelected = filteredKeys.length > 0 && filteredKeys.every((k) => next.has(k));

    if (allSelected) {
      filteredKeys.forEach((k) => next.delete(k));
    } else {
      filteredKeys.forEach((k) => next.add(k));
    }

    setSelectedKeys(next);
  };

  const toggleSelectOne = (ib: Inbound) => {
    const key = inboundKey(ib);
    const next = new Set(selectedKeys);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setSelectedKeys(next);
  };

  const clearSelection = () => {
    setSelectedKeys(new Set());
  };

  const applySortFromHeader = (field: 'name' | 'node' | 'protocol' | 'port' | 'status' | 'clients') => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortField(field);
    setSortDirection('asc');
  };
  const sortIndicator = (field: 'name' | 'node' | 'protocol' | 'port' | 'status') =>
    sortField === field ? (sortDirection === 'asc' ? ' â–²' : ' â–¼') : '';

  const handleDelete = async (inbound: Inbound) => {
    if (!window.confirm(`${t('inbounds.confirmDeleteSingle')} \"${inbound.remark || inbound.id}\"?`)) return;

    const nodeId = nodeNameToId[inbound.node_name];
    if (!nodeId) {
      setError(t('inbounds.nodeResolveFailed'));
      return;
    }

    setLoading(true);
    try {
      await api.delete(`/v1/inbounds/${inbound.id}`, {
        params: { node_id: nodeId },
        auth: getAuth(),
      });

      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.deleteFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleCloneClick = (inbound: Inbound) => {
    setCloneSource(inbound);
    setCloneRemark(`${inbound.remark} (Clone)`);
    // Auto-suggest port + 1, but only if not already taken on the same node
    const usedPorts = new Set(inbounds.filter(ib => ib.node_name === inbound.node_name).map(ib => ib.port));
    let suggestedPort = inbound.port + 1;
    while (usedPorts.has(suggestedPort) && suggestedPort < 65535) suggestedPort++;
    setClonePort(String(suggestedPort));
    const sourceNodeId = nodeNameToId[inbound.node_name];
    if (sourceNodeId) {
      setCloneTargetNodeIds(new Set([sourceNodeId]));
    } else {
      setCloneTargetNodeIds(new Set());
    }
    setShowCloneModal(true);
  };

  const handleCloneSubmit = async () => {
    if (!cloneSource) return;

    const sourceNodeId = nodeNameToId[cloneSource.node_name];
    if (!sourceNodeId) {
      setError(t('inbounds.nodeResolveFailed'));
      return;
    }

    setLoading(true);
    setError('');

    try {
      const payload = {
        source_node_id: sourceNodeId,
        source_inbound_id: cloneSource.id,
        target_node_ids: cloneTargetNodeIds.size > 0 ? Array.from(cloneTargetNodeIds) : [sourceNodeId],
        modifications: {
          remark: cloneRemark,
          ...(clonePort.trim() ? { port: parseInt(clonePort, 10) || cloneSource.port } : {}),
        },
      };

      await api.post('/v1/inbounds/clone', payload, {
        auth: getAuth(),
      });

      setShowCloneModal(false);
      setCloneTargetNodeIds(new Set());
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.cloneFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleTemplateChange = (protocol: 'vless' | 'vmess' | 'trojan') => {
    setAddTemplateProtocol(protocol);
    setAddJsonConfig(JSON.stringify(INBOUND_TEMPLATES[protocol], null, 2));
  };

  const toggleAddTarget = (nodeId: number) => {
    const next = new Set(addTargetNodeIds);
    if (next.has(nodeId)) {
      next.delete(nodeId);
    } else {
      next.add(nodeId);
    }
    setAddTargetNodeIds(next);
  };

  const handleAddInboundSubmit = async () => {
    setLoading(true);
    setError('');
    try {
      const parsed = JSON.parse(addJsonConfig);
      if (!parsed || typeof parsed !== 'object') {
        throw new Error(t('inbounds.jsonObjectRequired'));
      }
      const payload: Record<string, any> = {
        ...parsed,
        node_ids: addTargetNodeIds.size > 0 ? Array.from(addTargetNodeIds) : null,
      };
      await api.post('/v1/inbounds', payload, { auth: getAuth() });
      setShowAddModal(false);
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      if (err instanceof SyntaxError) {
        setError(t('inbounds.invalidJsonConfig'));
      } else {
        setError(err.response?.data?.detail || err.message || t('messages.operationFailed'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleBatchEnable = async (enable: boolean) => {
    if (selectedInboundIds.length === 0 || selectedNodeIds.length === 0) return;

    setLoading(true);
    setError('');

    try {
      await api.post(
        '/v1/inbounds/batch-enable',
        {
          node_ids: selectedNodeIds,
          inbound_ids: selectedInboundIds,
          enable,
        },
        { auth: getAuth() }
      );

      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.batchEnableFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchUpdate = async () => {
    if (selectedInboundIds.length === 0 || selectedNodeIds.length === 0) return;

    const updates: Record<string, any> = {};
    if (batchRemark.trim()) updates.remark = batchRemark.trim();
    if (batchEnableMode === 'enable') updates.enable = true;
    if (batchEnableMode === 'disable') updates.enable = false;

    if (Object.keys(updates).length === 0) {
      setError(t('inbounds.batchUpdateEmpty'));
      return;
    }

    setLoading(true);
    setError('');

    try {
      await api.post(
        '/v1/inbounds/batch-update',
        {
          node_ids: selectedNodeIds,
          inbound_ids: selectedInboundIds,
          updates,
        },
        { auth: getAuth() }
      );

      setBatchRemark('');
      setBatchEnableMode('none');
      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.batchUpdateFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchDelete = async () => {
    if (selectedInboundIds.length === 0 || selectedNodeIds.length === 0) return;

    if (!window.confirm(t('inbounds.confirmBatchDelete', { count: selectedKeys.size }))) return;

    setLoading(true);
    setError('');

    try {
      await api.post(
        '/v1/inbounds/batch-delete',
        {
          node_ids: selectedNodeIds,
          inbound_ids: selectedInboundIds,
        },
        { auth: getAuth() }
      );

      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.batchDeleteFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleImportSubmit = async () => {
    setImportError('');
    setImportResult('');
    let parsed: any[];
    try {
      const raw = JSON.parse(importJson);
      parsed = Array.isArray(raw) ? raw : [raw];
    } catch {
      setImportError(t('inbounds.importInvalidJson'));
      return;
    }
    if (parsed.length === 0) { setImportError(t('inbounds.importNoItems')); return; }
    setImportLoading(true);
    let ok = 0, fail = 0;
    const nodeIds = importTargetNodeIds.size > 0 ? Array.from(importTargetNodeIds) : null;
    for (const ib of parsed) {
      try {
        await api.post('/v1/inbounds', { ...ib, node_ids: nodeIds }, { auth: getAuth() });
        ok++;
      } catch { fail++; }
    }
    setImportLoading(false);
    const resultMsg = t('inbounds.importDone', { ok, fail });
    setImportResult(resultMsg);
    toast(resultMsg, ok > 0 ? 'success' : 'error');
    if (ok > 0) { await loadInbounds(); onReload?.(); }
  };

  const handleEditClick = (ib: Inbound) => {
    setEditingInbound(ib);
  };

  const handleResetInboundTraffic = async (ib: Inbound) => {
    const nodeObj = allNodes.find(n => n.name === ib.node_name);
    if (!nodeObj) return;
    const { user, password } = getAuth();
    try {
      await api.post(`/v1/inbounds/${nodeObj.id}/${ib.id}/reset-traffic`, {}, { auth: { username: user, password } });
    } catch (e) { console.error(e); }
  };

  const handleDelAllClients = async (ib: Inbound) => {
    if (!window.confirm(t('inbounds.delAllClientsConfirm'))) return;
    const nodeObj = allNodes.find(n => n.name === ib.node_name);
    if (!nodeObj) return;
    const { user, password } = getAuth();
    try {
      const res = await api.post(`/v1/inbounds/${nodeObj.id}/${ib.id}/del-all-clients`, {}, { auth: { username: user, password } });
      toast(t('inbounds.delAllClientsDone', { count: res.data?.deleted ?? 0 }), 'success');
      onReload?.();
    } catch (e) { console.error(e); }
  };

  const handleResetAllTraffic = async () => {
    if (allNodes.length === 0) {
      toast(t('nodes.noNodesYet'), 'warning');
      return;
    }
    if (!window.confirm(t('inbounds.confirmResetAllTraffic'))) return;
    let ok = 0;
    let fail = 0;
    for (const node of allNodes) {
      try {
        const res = await api.post(`/v1/inbounds/${node.id}/reset-all-traffics`, {}, { auth: getAuth() });
        if (res.data?.success === false) {
          fail++;
        } else {
          ok++;
        }
      } catch {
        fail++;
      }
    }
    toast(t('inbounds.resetSelectedResult', { ok, fail }), ok > 0 ? 'success' : 'error');
    await loadInbounds();
    onReload?.();
  };

  const protocols = Array.from(new Set(inbounds.map((ib) => ib.protocol)));
  const securities = Array.from(new Set(inbounds.map((ib) => ib.security)));
  const nodes = Array.from(new Set(inbounds.map((ib) => ib.node_name)));

  // Build set of node+port combos that appear more than once (duplicate ports)
  const portCounts = new Map<string, number>();
  inbounds.forEach(ib => {
    const key = `${ib.node_name}:${ib.port}`;
    portCounts.set(key, (portCounts.get(key) || 0) + 1);
  });
  const isDuplicatePort = (ib: Inbound) => (portCounts.get(`${ib.node_name}:${ib.port}`) || 0) > 1;

  const allFilteredSelected =
    filteredInbounds.length > 0 && filteredInbounds.every((ib) => selectedKeys.has(inboundKey(ib)));
  const visibleInbounds = filteredInbounds.slice((ibPage - 1) * ibPageSize, ibPage * ibPageSize);

  return (
    <div data-inbound-manager-root className="min-h-screen min-w-0 overflow-hidden bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6">
      <div className="min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]">
        <div className="mb-4 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <h2 className="flex min-w-0 items-center gap-2 text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">
            <UIIcon name="inbounds" size={16} />
            {t('inbounds.title')}
          </h2>
          {inbounds.length > 0 && (
            <div className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap">
              {[
                { label: 'Inbounds', value: inbounds.length, className: 'text-slate-100' },
                { label: 'Active', value: inbounds.filter(ib => ib.enable).length, className: 'text-emerald-400' },
                { label: 'Clients', value: inbounds.reduce((s, ib) => s + (ib.client_count ?? 0), 0), className: 'text-cyan-300' },
              ].map(s => (
                <span key={s.label} className="min-w-0 rounded-md bg-[#0a0e1a] px-2 py-1 text-[11px] text-slate-500">
                  <span className="block truncate uppercase tracking-wider">{s.label}</span>
                  <strong className={cn('mt-1 block font-mono text-sm tabular-nums whitespace-nowrap', s.className)}>{s.value}</strong>
                </span>
              ))}
            </div>
          )}
        </div>

        {error && <div className={tableErrorClass}>{error}</div>}

        {inboundStats && (
          <div className="mb-4 min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
            <div className="grid min-w-0 grid-cols-3 gap-2 lg:grid-cols-[repeat(3,minmax(90px,120px))_minmax(0,1fr)_minmax(0,1fr)]">
              {[
                { label: t('common.total'), value: inboundStats.total, tone: 'text-slate-100' },
                { label: t('common.enabled'), value: inboundStats.enabled, tone: 'text-emerald-300' },
                { label: t('common.disabled'), value: inboundStats.disabled, tone: 'text-rose-300' },
              ].map((item) => (
                <div key={item.label} className="rounded-md border border-cyan-500/15 bg-[#0f1420] px-3 py-2">
                  <span className="block truncate text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{item.label}</span>
                  <strong className={cn('mt-1 block font-mono text-lg tabular-nums', item.tone)}>{item.value}</strong>
                </div>
              ))}
              <div className="col-span-3 min-w-0 rounded-md border border-cyan-500/15 bg-[#0f1420] px-3 py-2 lg:col-span-1">
                <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('inbounds.protocol')}</span>
                <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                  {Object.entries(inboundStats.by_protocol).map(([name, count]) => (
                    <span key={name} className={badgeBaseClass}>
                      <span className="truncate">{name || 'unknown'}</span>
                      <strong className="ml-1 font-mono tabular-nums text-cyan-200">{count}</strong>
                    </span>
                  ))}
                  {Object.keys(inboundStats.by_protocol).length === 0 && <span className="text-xs text-slate-500">-</span>}
                </div>
              </div>
              <div className="col-span-3 min-w-0 rounded-md border border-cyan-500/15 bg-[#0f1420] px-3 py-2 lg:col-span-1">
                <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('inbounds.security')}</span>
                <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                  {Object.entries(inboundStats.by_security).map(([name, count]) => (
                    <span key={name} className={badgeBaseClass}>
                      <span className="truncate">{name || 'none'}</span>
                      <strong className="ml-1 font-mono tabular-nums text-cyan-200">{count}</strong>
                    </span>
                  ))}
                  {Object.keys(inboundStats.by_security).length === 0 && <span className="text-xs text-slate-500">-</span>}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="mb-4 min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
          <div className="mb-3 flex min-w-0 flex-col gap-1">
            <h3 className={panelTitleClass}>{t('common.filter')}</h3>
            <p className={panelHintClass}>{t('inbounds.filtersHint')}</p>
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-[minmax(180px,260px)_minmax(0,1fr)]">
              <input
                type="text"
                className={cn(inputClass, 'w-full')}
                placeholder={t('inbounds.searchPlaceholder')}
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
              />
              <div className="min-w-0 overflow-hidden">
                <div className="flex min-w-0 flex-wrap gap-1">
                  {[{ value: '', label: t('inbounds.allProtocols') }, ...protocols.map((p) => ({ value: p, label: p.toUpperCase() }))].map((option) => (
                    <button
                      key={option.value || 'all-protocols'}
                      type="button"
                      className={segmentButtonClass(filterProtocol === option.value)}
                      onClick={() => setFilterProtocol(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="min-w-0 overflow-hidden">
                <div className="flex min-w-0 flex-wrap gap-1">
                  {[{ value: '', label: t('inbounds.allSecurity') }, ...securities.map((s) => ({ value: s, label: s || 'none' }))].map((option) => (
                    <button
                      key={option.value || 'all-security'}
                      type="button"
                      className={segmentButtonClass(filterSecurity === option.value)}
                      onClick={() => setFilterSecurity(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="min-w-0 overflow-hidden">
                <div className="flex min-w-0 flex-wrap gap-1">
                  {[{ value: '', label: t('inbounds.allNodes') }, ...nodes.map((n) => ({ value: n, label: n }))].map((option) => (
                    <button
                      key={option.value || 'all-nodes'}
                      type="button"
                      className={segmentButtonClass(filterNode === option.value)}
                      onClick={() => setFilterNode(option.value)}
                    >
                      <span className="max-w-[9rem] truncate">{option.label}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="min-w-0 overflow-hidden">
                <div className="flex min-w-0 flex-wrap gap-1">
                  {[
                  { value: 'all', label: t('common.all') },
                  { value: 'enabled', label: t('inbounds.active') },
                  { value: 'disabled', label: t('common.disabled') },
                  ].map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={segmentButtonClass(filterEnabledStatus === option.value)}
                      onClick={() => setFilterEnabledStatus(option.value as 'all' | 'enabled' | 'disabled')}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <button
                type="button"
                className={cn(buttonBaseClass, filterEmptyOnly ? 'bg-amber-400 text-[#06111f]' : 'bg-[#0f1420] text-slate-200 hover:bg-[#0a0e1a]')}
                onClick={() => setFilterEmptyOnly(v => !v)}
                title={t('inbounds.emptyOnlyTitle')}
              >
                <UIIcon name="clear" size={13} />
                {t('inbounds.emptyOnly')}
              </button>
              <button
                type="button"
                className={cn(buttonBaseClass, filterDuplicatesOnly ? 'bg-rose-500 text-white' : 'bg-[#0f1420] text-slate-200 hover:bg-[#0a0e1a]')}
                onClick={() => setFilterDuplicatesOnly(v => !v)}
                title={t('inbounds.duplicatesTitle')}
              >
                <UIIcon name="warning" size={13} />
                {t('inbounds.duplicates')}
              </button>
              <button
                type="button"
                className={buttonNeutralClass}
                onClick={() => {
                  setFilterProtocol('');
                  setFilterSecurity('');
                  setFilterNode('');
                  setFilterEmptyOnly(false);
                  setFilterEnabledStatus('all');
                  setFilterDuplicatesOnly(false);
                  setSearchTerm('');
                }}
              >
                {t('inbounds.clearFilters')}
              </button>
          </div>
        </div>

        <div className="mb-4 min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
          <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[minmax(180px,240px)_minmax(220px,280px)_minmax(180px,240px)_minmax(0,1fr)]">
            <div className="min-w-0">
              <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
                {t('inbounds.selectedCount', { count: selectedKeys.size })}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  className={buttonNeutralClass}
                  onClick={toggleSelectAllFiltered}
                >
                  {allFilteredSelected ? t('common.deselectAll') : t('common.selectAll')}
                </button>
                <button
                  type="button"
                  className={buttonNeutralClass}
                  onClick={clearSelection}
                  disabled={selectedKeys.size === 0}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </div>

            <div className="min-w-0">
              <div className={panelTitleClass}>{t('common.actions')}</div>
              <div className={panelHintClass}>{t('inbounds.actionsHint')}</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  className={buttonSuccessClass}
                  onClick={() => setShowAddModal(true)}
                >
                  <UIIcon name="plus" size={14} />
                  {t('inbounds.addInbound')}
                </button>
                <button
                  type="button"
                  className={buttonAccentClass}
                  onClick={() => { void loadInbounds(); }}
                  disabled={loading}
                >
                  <UIIcon name="refresh" size={14} />
                  {t('common.refresh')}
                </button>
              </div>
            </div>

            <div className="min-w-0">
              <label className={fieldLabelClass}>{t('inbounds.batchRemark')}</label>
              <input
                className={cn(inputClass, 'w-full')}
                value={batchRemark}
                onChange={(e) => setBatchRemark(e.target.value)}
                placeholder={t('inbounds.batchRemarkPlaceholder')}
              />
            </div>

            <div className="min-w-0">
              <label className={fieldLabelClass}>{t('inbounds.batchEnableMode')}</label>
              <div className="flex min-w-0 flex-wrap gap-1">
                {[
                  { value: 'none', label: t('common.no') },
                  { value: 'enable', label: t('inbounds.batchEnable') },
                  { value: 'disable', label: t('inbounds.batchDisable') },
                ].map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={segmentButtonClass(batchEnableMode === option.value)}
                    onClick={() => setBatchEnableMode(option.value as 'none' | 'enable' | 'disable')}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="min-w-0 md:col-span-2 xl:col-span-4">
              <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-[repeat(9,max-content)]">
              <button
                type="button"
                className={buttonSuccessClass}
                onClick={() => handleBatchEnable(true)}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchEnable')}
              </button>
              <button
                type="button"
                className={buttonWarningClass}
                onClick={() => handleBatchEnable(false)}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchDisable')}
              </button>
              <button
                type="button"
                className={buttonAccentClass}
                onClick={handleBatchUpdate}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchUpdate')}
              </button>
              <button
                type="button"
                className={buttonDangerClass}
                onClick={handleBatchDelete}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchDelete')}
              </button>
              <button
                type="button"
                className={`${buttonBaseClass} bg-amber-400/10 text-amber-300 hover:bg-amber-400/15`}
                title={t('inbounds.resetSelectedTitle')}
                disabled={loading || selectedKeys.size === 0}
                onClick={async () => {
                  if (!window.confirm(t('inbounds.confirmResetSelected', { count: selectedKeys.size }))) return;
                  let ok = 0; let fail = 0;
                  for (const ib of selectedInbounds) {
                    const nodeObj = allNodes.find(n => n.name === ib.node_name);
                    if (!nodeObj) { fail++; continue; }
                    try {
                      await api.post(`/v1/inbounds/${nodeObj.id}/${ib.id}/reset-traffic`, {}, { auth: getAuth() });
                      ok++;
                    } catch { fail++; }
                  }
                  toast(t('inbounds.resetSelectedResult', { ok, fail }), ok > 0 ? 'success' : 'error');
                }}
              >
                <UIIcon name="refresh" size={13} />
                {t('inbounds.resetSelected')}
              </button>
              <button
                type="button"
                className={`${buttonBaseClass} bg-rose-500/10 text-rose-300 hover:bg-rose-500/15`}
                title={t('inbounds.resetAllTitle')}
                onClick={handleResetAllTraffic}
              >
                <UIIcon name="refresh" size={13} />
                {t('inbounds.resetAllTraffic')}
              </button>
              <button
                type="button"
                className={buttonNeutralClass}
                title={t('inbounds.importJsonTitle')}
                onClick={() => { setImportJson(''); setImportTargetNodeIds(new Set()); setImportError(''); setImportResult(''); setShowImportModal(true); }}
              >
                <UIIcon name="upload" size={13} />
                {t('inbounds.importJson')}
              </button>
              <button
                type="button"
                className={buttonNeutralClass}
                title={t('inbounds.exportJsonTitle')}
                onClick={() => {
                  const toExport = selectedKeys.size > 0 ? selectedInbounds : filteredInbounds;
                  const data = toExport.map(ib => ({
                    protocol: ib.protocol,
                    port: ib.port,
                    remark: ib.remark,
                    enable: ib.enable,
                    settings: ib.settings || {},
                    streamSettings: ib.streamSettings || {},
                  }));
                  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `inbounds_export_${new Date().toISOString().slice(0,10)}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                  toast(t('inbounds.exportedJson', { count: toExport.length }), 'success');
                }}
              >
                <UIIcon name="download" size={13} />
                {t('inbounds.exportJson')}
              </button>
              <button
                type="button"
                className={buttonNeutralClass}
                title={t('inbounds.exportCsvTitle')}
                onClick={() => {
                  const toExport = selectedKeys.size > 0 ? selectedInbounds : filteredInbounds;
                  const headers = ['Node', 'Remark', 'Protocol', 'Port', 'Enable', 'Security', 'Clients'];
                  const rows = toExport.map(ib => [
                    ib.node_name, ib.remark || '', ib.protocol, ib.port,
                    ib.enable ? 'yes' : 'no', ib.security || '', ib.client_count ?? '',
                  ]);
                  const csv = [headers, ...rows].map(r => r.join(',')).join('\n');
                  const blob = new Blob([csv], { type: 'text/csv' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `inbounds_${new Date().toISOString().slice(0,10)}.csv`;
                  a.click();
                  URL.revokeObjectURL(url);
                  toast(t('inbounds.exportedCsv', { count: toExport.length }), 'success');
                }}
              >
                <UIIcon name="download" size={13} />
                {t('inbounds.csv')}
              </button>
            </div>
          </div>
        </div>
        </div>

        {pageLoading && filteredInbounds.length > 0 && (
          <div className="mb-3 h-1 overflow-hidden rounded-full bg-[#0f1420]">
            <div className="h-full w-1/3 animate-pulse rounded-full bg-cyan-300" />
          </div>
        )}
        {pageLoading && filteredInbounds.length === 0 && <InboundTableSkeleton />}

        {!pageLoading && filteredInbounds.length === 0 && inbounds.length === 0 && (
          <div className="mb-3 flex min-w-0 items-center justify-center overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-10 text-center">
            <span className={tableStateChipClass}>{t('common.noRecordsFound')}</span>
          </div>
        )}
        {!pageLoading && filteredInbounds.length === 0 && inbounds.length > 0 && (
          <div className="mb-3 flex min-w-0 items-center justify-center overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-10 text-center">
            <span className={tableStateChipClass}>{t('common.noRecordsFound')}</span>
          </div>
        )}

        {inbounds.length > 0 && (() => {
          const enabled = inbounds.filter(ib => ib.enable).length;
          const totalClients = inbounds.reduce((s, ib) => s + (ib.client_count ?? 0), 0);
          const byProto = inbounds.reduce<Record<string, number>>((acc, ib) => { acc[ib.protocol] = (acc[ib.protocol] || 0) + 1; return acc; }, {});
          return (
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:flex lg:flex-wrap">
              {[
                { label: t('common.total'), value: inbounds.length, className: 'text-slate-100' },
                { label: t('common.enabled'), value: enabled, className: 'text-emerald-400' },
                { label: t('common.disabled'), value: inbounds.length - enabled, className: 'text-slate-500' },
                ...(totalClients > 0 ? [{ label: t('inbounds.clients'), value: totalClients, className: 'text-cyan-300' }] : []),
                ...Object.entries(byProto).map(([p, n]) => ({ label: p.toUpperCase(), value: n, className: 'text-sky-300' })),
              ].map(s => (
                <span key={s.label} className="min-w-0 rounded-md bg-[#0a0e1a] px-2 py-1 text-[11px] text-slate-500">
                  <span className="truncate uppercase tracking-wider">{s.label}</span>: <strong className={cn('font-mono tabular-nums whitespace-nowrap', s.className)}>{s.value}</strong>
                </span>
              ))}
            </div>
          );
        })()}

        {filteredInbounds.length > ibPageSize && (
          <div className="mb-3 flex min-w-0 flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="whitespace-nowrap">{t('inbounds.pageStatus', { page: ibPage, pages: Math.ceil(filteredInbounds.length / ibPageSize), from: (ibPage - 1) * ibPageSize + 1, to: Math.min(ibPage * ibPageSize, filteredInbounds.length), total: filteredInbounds.length })}</span>
            <div className="flex gap-1">
              <button type="button" className={buttonIconClass} disabled={ibPage <= 1} onClick={() => setIbPage(p => p - 1)}>&lt;</button>
              <button type="button" className={buttonIconClass} disabled={ibPage >= Math.ceil(filteredInbounds.length / ibPageSize)} onClick={() => setIbPage(p => p + 1)}>&gt;</button>
            </div>
            <select className={cn(inputClass, 'h-8 w-auto py-1 text-[11px] text-slate-400')}
              value={ibPageSize} onChange={e => { setIbPageSize(Number(e.target.value)); setIbPage(1); }}>
              {[25, 50, 100, 200].map(n => <option key={n} value={n}>{t('inbounds.rowsPerPageOption', { count: n })}</option>)}
            </select>
          </div>
        )}

        {filteredInbounds.length > 0 && (
          <>
            <div className="grid min-w-0 grid-cols-1 gap-3 lg:hidden">
              {visibleInbounds.map((ib) => (
                <article
                  key={inboundKey(ib)}
                  className={cn('min-w-0 overflow-hidden rounded-lg bg-[#0a0e1a] p-3', !ib.enable && 'opacity-70')}
                >
                  <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3">
                    <input
                      className={checkboxClass}
                      type="checkbox"
                      checked={selectedKeys.has(inboundKey(ib))}
                      onChange={() => toggleSelectOne(ib)}
                      aria-label={t('inbounds.selectInbound', { name: ib.remark || ib.id })}
                    />
                    <div className="min-w-0">
                      <button
                        type="button"
                        className="max-w-full truncate text-left text-sm font-medium text-slate-100 hover:text-cyan-300"
                        title={t('inbounds.quickEditRemarkTitle')}
                        onDoubleClick={async () => {
                          const newRemark = window.prompt(t('inbounds.newRemarkPrompt', { id: ib.id, node: ib.node_name }), ib.remark || '');
                          if (newRemark === null || newRemark === ib.remark) return;
                          const nodeObj = allNodes.find(n => n.name === ib.node_name);
                          if (!nodeObj) return;
                          try {
                            await api.put('/v1/inbounds/' + nodeObj.id + '/' + ib.id, { remark: newRemark }, { auth: getAuth() });
                            setInbounds(prev => prev.map(x => inboundKey(x) === inboundKey(ib) ? { ...x, remark: newRemark } : x));
                            toast(t('inbounds.remarkUpdated', { remark: newRemark || t('inbounds.emptyRemark') }), 'success');
                          } catch (e: any) { toast(e.response?.data?.detail || t('common.failed'), 'error'); }
                        }}
                      >
                        {ib.remark || <span className="text-slate-600">-</span>}
                      </button>
                      <div className="mt-1 truncate font-mono text-[11px] tabular-nums whitespace-nowrap text-slate-500">#{ib.id}</div>
                    </div>
                    <button
                      type="button"
                      className={cn('inline-flex h-7 items-center rounded-md border px-2 text-[11px] font-medium whitespace-nowrap', ib.enable ? 'border-emerald-300/25 bg-emerald-400/10 text-emerald-300' : 'border-cyan-500/20 bg-[#0f1420] text-slate-500')}
                      title={ib.enable ? t('inbounds.clickToDisable') : t('inbounds.clickToEnable')}
                      onClick={async () => {
                        const nodeObj = allNodes.find(n => n.name === ib.node_name);
                        if (!nodeObj) return;
                        const { user, password } = getAuth();
                        try {
                          await api.post('/v1/inbounds/' + nodeObj.id + '/' + ib.id + '/set-enable', { enable: !ib.enable }, { auth: { username: user, password } });
                          setInbounds(prev => prev.map(x => inboundKey(x) === inboundKey(ib) ? { ...x, enable: !ib.enable } : x));
                          toast(t('inbounds.enableToggled', { name: ib.remark || '#' + ib.id, status: !ib.enable ? t('common.enabled') : t('common.disabled') }), 'success');
                        } catch (e: any) { toast(e.response?.data?.detail || t('common.failed'), 'error'); }
                      }}
                    >
                      {ib.enable ? t('common.enabled') : t('common.disabled')}
                    </button>
                  </div>

                  <div className="mt-3 grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4">
                    <button
                      type="button"
                      className={cn(badgeBaseClass, 'justify-start bg-[#0f1420] text-slate-200')}
                      title={filterNode === ib.node_name ? t('inbounds.clearNodeFilter') : t('inbounds.filterByNodeName', { node: ib.node_name })}
                      onClick={() => setFilterNode(prev => prev === ib.node_name ? '' : ib.node_name)}
                    >
                      <span className="truncate">{ib.node_name}</span>
                    </button>
                    <button
                      type="button"
                      className={cn(badgeBaseClass, 'bg-cyan-400 text-[#06111f]')}
                      title={filterProtocol === ib.protocol ? t('inbounds.clearProtocolFilter') : t('inbounds.filterByProtocolName', { protocol: ib.protocol })}
                      onClick={() => setFilterProtocol(prev => prev === ib.protocol ? '' : ib.protocol)}
                    >
                      {ib.protocol.toUpperCase()}
                    </button>
                    <button
                      type="button"
                      className={cn(badgeBaseClass, 'justify-start bg-[#0f1420]', isDuplicatePort(ib) ? 'text-amber-300' : 'text-slate-300')}
                      title={isDuplicatePort(ib) ? t('inbounds.duplicatePortTitle', { port: ib.port, node: ib.node_name }) : t('inbounds.copyPortNumber')}
                      onClick={() => navigator.clipboard.writeText(String(ib.port))}
                    >
                      <span className="font-mono tabular-nums whitespace-nowrap">{ib.port}</span>
                      {isDuplicatePort(ib) && <UIIcon name="warning" size={12} />}
                    </button>
                    {ib.client_count !== undefined ? (
                      <button
                        type="button"
                        className={cn(badgeBaseClass, ib.client_count > 0 ? 'bg-cyan-400 text-[#06111f]' : 'bg-[#0f1420] text-slate-500')}
                        title={ib.client_count > 0 && onNavigateToClients ? t('inbounds.viewClientsTitle', { count: ib.client_count }) : undefined}
                        onClick={() => ib.client_count && ib.client_count > 0 && onNavigateToClients && onNavigateToClients(ib.id, ib.remark || '#' + ib.id)}
                      >
                        <span className="font-mono tabular-nums whitespace-nowrap">{ib.client_count}</span>
                      </button>
                    ) : (
                      <span className={cn(badgeBaseClass, 'bg-[#0f1420] text-slate-600')}>-</span>
                    )}
                  </div>

                  <div className="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-8">
                    <button type="button" className={buttonIconClass} onClick={() => handleEditClick(ib)} title={t('inbounds.editInbound')} aria-label={t('inbounds.editInbound')}><UIIcon name="edit" size={14} /></button>
                    <button type="button" className={buttonIconClass} title={t('inbounds.addClientTitle')} onClick={() => onAddClientToInbound && onAddClientToInbound(ib.id, ib.node_name)} disabled={!onAddClientToInbound} aria-label={t('inbounds.addClientTitle')}><UIIcon name="plus" size={14} /></button>
                    <button type="button" className={buttonIconClass} onClick={() => handleCloneClick(ib)} title={t('inbounds.cloneInbound')} aria-label={t('inbounds.cloneInbound')}><UIIcon name="copy" size={14} /></button>
                    <button type="button" className={buttonIconClass} title={t('inbounds.viewConfigTitle')} onClick={() => { setConfigModalInbound(ib); setShowConfigModal(true); }} aria-label={t('inbounds.viewConfigTitle')}>{'{}'}</button>
                    <button
                      type="button"
                      className={buttonIconClass}
                      title={t('inbounds.copyJsonConfig')}
                      onClick={() => {
                        const config = { protocol: ib.protocol, port: ib.port, remark: ib.remark, settings: ib.settings || {}, streamSettings: ib.streamSettings || {} };
                        navigator.clipboard.writeText(JSON.stringify(config, null, 2));
                        toast(t('inbounds.configCopied'), 'info');
                      }}
                      aria-label={t('inbounds.copyJsonConfig')}
                    ><UIIcon name="copy" size={14} /></button>
                    <button type="button" className={buttonIconClass} onClick={() => handleResetInboundTraffic(ib)} title={t('inbounds.resetTraffic')} aria-label={t('inbounds.resetTraffic')}><UIIcon name="refresh" size={14} /></button>
                    <button type="button" className={cn(buttonIconClass, 'text-rose-300')} onClick={() => handleDelAllClients(ib)} title={t('inbounds.delAllClients')} aria-label={t('inbounds.delAllClients')}><UIIcon name="clients" size={14} /></button>
                    <button type="button" className={cn(buttonIconClass, 'bg-rose-500 text-white hover:bg-rose-400 hover:text-white')} onClick={() => handleDelete(ib)} title={t('inbounds.deleteInbound')} aria-label={t('inbounds.deleteInbound')}><UIIcon name="trash" size={14} /></button>
                  </div>
                </article>
              ))}
            </div>

            <div className="hidden w-full min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0a0e1a] lg:block">
              <div className="w-full min-w-0 overflow-x-auto">
                <table className="w-full table-fixed border-collapse text-left text-xs">
                  <thead className="bg-[#0f1420] text-[10px] uppercase tracking-wider text-slate-500">
                    <tr>
                      <th className="w-10 px-3 py-3"><input className={checkboxClass} type="checkbox" checked={allFilteredSelected} onChange={toggleSelectAllFiltered} aria-label={t('common.selectAll')} /></th>
                      <th className="w-[12%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('node')}>{t('common.name')}{sortIndicator('node')}</button></th>
                      <th className="w-[18%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('name')}>{t('inbounds.remark')}{sortIndicator('name')}</button></th>
                      <th className="w-[8%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('protocol')}>{t('inbounds.protocol')}{sortIndicator('protocol')}</button></th>
                      <th className="w-[8%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('port')}>{t('inbounds.port')}{sortIndicator('port')}</button></th>
                      <th className="w-[9%] px-3 py-3">{t('inbounds.security')}</th>
                      <th className="w-[10%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('status')}>{t('common.status')}{sortIndicator('status')}</button></th>
                      <th className="w-[6%] px-3 py-3"><button type="button" className={sortButtonClass} onClick={() => applySortFromHeader('clients')} title={t('inbounds.sortByClientCount')}>{t('inbounds.clients')}{sortField === 'clients' ? (sortDirection === 'asc' ? ' ^' : ' v') : ''}</button></th>
                      <th className="w-[156px] px-3 py-3">{t('common.actions')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-900 text-slate-200">
                    {visibleInbounds.map((ib) => (
                      <tr key={inboundKey(ib)} className={cn('transition-colors hover:bg-cyan-400/5', !ib.enable && 'bg-[#0f1420]/60 opacity-75')}>
                        <td className="px-3 py-3 align-middle"><input className={checkboxClass} type="checkbox" checked={selectedKeys.has(inboundKey(ib))} onChange={() => toggleSelectOne(ib)} aria-label={t('inbounds.selectInbound', { name: ib.remark || ib.id })} /></td>
                        <td className="px-3 py-3 align-middle"><button type="button" className={cn(badgeBaseClass, 'max-w-full justify-start overflow-hidden bg-[#0f1420] text-slate-200')} title={ib.node_name} onClick={() => setFilterNode(prev => prev === ib.node_name ? '' : ib.node_name)}><span className={inboundLongValueClass}>{ib.node_name}</span></button></td>
                        <td className="min-w-0 px-3 py-3 align-middle" title={t('inbounds.quickEditRemarkTitle')} onDoubleClick={async () => {
                          const newRemark = window.prompt(t('inbounds.newRemarkPrompt', { id: ib.id, node: ib.node_name }), ib.remark || '');
                          if (newRemark === null || newRemark === ib.remark) return;
                          const nodeObj = allNodes.find(n => n.name === ib.node_name);
                          if (!nodeObj) return;
                          try {
                            await api.put('/v1/inbounds/' + nodeObj.id + '/' + ib.id, { remark: newRemark }, { auth: getAuth() });
                            setInbounds(prev => prev.map(x => inboundKey(x) === inboundKey(ib) ? { ...x, remark: newRemark } : x));
                            toast(t('inbounds.remarkUpdated', { remark: newRemark || t('inbounds.emptyRemark') }), 'success');
                          } catch (e: any) { toast(e.response?.data?.detail || t('common.failed'), 'error'); }
                        }}><span className={inboundLongValueClass} title={ib.remark || `#${ib.id}`}>{ib.remark || <span className="text-slate-600">-</span>}</span></td>
                        <td className="px-3 py-3 align-middle"><button type="button" className={cn(badgeBaseClass, 'bg-cyan-400 text-[#06111f]')} title={filterProtocol === ib.protocol ? t('inbounds.clearProtocolFilter') : t('inbounds.filterByProtocolName', { protocol: ib.protocol })} onClick={() => setFilterProtocol(prev => prev === ib.protocol ? '' : ib.protocol)}>{ib.protocol.toUpperCase()}</button></td>
                        <td className="px-3 py-3 align-middle"><button type="button" className={cn('inline-flex items-center gap-1 font-mono text-xs tabular-nums whitespace-nowrap', isDuplicatePort(ib) ? 'font-bold text-amber-300' : 'text-slate-300')} title={isDuplicatePort(ib) ? t('inbounds.duplicatePortTitle', { port: ib.port, node: ib.node_name }) : t('inbounds.copyPortNumber')} onClick={() => navigator.clipboard.writeText(String(ib.port))}>{ib.port}{isDuplicatePort(ib) && <UIIcon name="warning" size={12} />}</button></td>
                        <td className="px-3 py-3 align-middle">
                          {ib.is_reality && <button type="button" className={cn(badgeBaseClass, filterSecurity === 'reality' ? 'bg-amber-400 text-[#06111f]' : 'bg-emerald-400/15 text-emerald-300')} onClick={() => setFilterSecurity(prev => prev === 'reality' ? '' : 'reality')} title={t('inbounds.filterByReality')}>{t('inbounds.reality')}</button>}
                          {!ib.is_reality && ib.security && <button type="button" className={cn(badgeBaseClass, 'max-w-full overflow-hidden', filterSecurity === ib.security ? 'bg-amber-400 text-[#06111f]' : 'bg-sky-400/15 text-sky-300')} onClick={() => setFilterSecurity(prev => prev === (ib.security ?? '') ? '' : (ib.security ?? ''))} title={ib.security}><span className="truncate">{ib.security}</span></button>}
                          {!ib.security && <span className="text-slate-600">-</span>}
                        </td>
                        <td className="px-3 py-3 align-middle"><button type="button" className={cn('inline-flex h-7 items-center rounded-md border px-2 text-[11px] font-medium whitespace-nowrap', ib.enable ? 'border-emerald-300/25 bg-emerald-400/10 text-emerald-300' : 'border-cyan-500/20 bg-[#0f1420] text-slate-500')} title={ib.enable ? t('inbounds.clickToDisable') : t('inbounds.clickToEnable')} onClick={async () => {
                          const nodeObj = allNodes.find(n => n.name === ib.node_name);
                          if (!nodeObj) return;
                          const { user, password } = getAuth();
                          try {
                            await api.post('/v1/inbounds/' + nodeObj.id + '/' + ib.id + '/set-enable', { enable: !ib.enable }, { auth: { username: user, password } });
                            setInbounds(prev => prev.map(x => inboundKey(x) === inboundKey(ib) ? { ...x, enable: !ib.enable } : x));
                            toast(t('inbounds.enableToggled', { name: ib.remark || '#' + ib.id, status: !ib.enable ? t('common.enabled') : t('common.disabled') }), 'success');
                          } catch (e: any) { toast(e.response?.data?.detail || t('common.failed'), 'error'); }
                        }}>{ib.enable ? t('common.enabled') : t('common.disabled')}</button></td>
                        <td className="px-3 py-3 align-middle">
                          {ib.client_count !== undefined ? <button type="button" className={cn(badgeBaseClass, ib.client_count > 0 ? 'bg-cyan-400 text-[#06111f]' : 'bg-[#0f1420] text-slate-500')} title={ib.client_count > 0 && onNavigateToClients ? t('inbounds.viewClientsTitle', { count: ib.client_count }) : undefined} onClick={() => ib.client_count && ib.client_count > 0 && onNavigateToClients && onNavigateToClients(ib.id, ib.remark || '#' + ib.id)}><span className="font-mono tabular-nums whitespace-nowrap">{ib.client_count}</span></button> : <span className="text-slate-600">-</span>}
                        </td>
                        <td className="px-3 py-3 align-middle"><div className="flex min-w-0 flex-wrap justify-end gap-1">
                          <button type="button" className={buttonIconClass} onClick={() => handleEditClick(ib)} title={t('inbounds.editInbound')} aria-label={t('inbounds.editInbound')}><UIIcon name="edit" size={14} /></button>
                          <button type="button" className={buttonIconClass} title={t('inbounds.addClientTitle')} onClick={() => onAddClientToInbound && onAddClientToInbound(ib.id, ib.node_name)} disabled={!onAddClientToInbound} aria-label={t('inbounds.addClientTitle')}><UIIcon name="plus" size={14} /></button>
                          <button type="button" className={buttonIconClass} onClick={() => handleCloneClick(ib)} title={t('inbounds.cloneInbound')} aria-label={t('inbounds.cloneInbound')}><UIIcon name="copy" size={14} /></button>
                          <button type="button" className={buttonIconClass} title={t('inbounds.viewConfigTitle')} onClick={() => { setConfigModalInbound(ib); setShowConfigModal(true); }} aria-label={t('inbounds.viewConfigTitle')}>{'{}'}</button>
                          <button type="button" className={buttonIconClass} title={t('inbounds.copyJsonConfig')} onClick={() => { const config = { protocol: ib.protocol, port: ib.port, remark: ib.remark, settings: ib.settings || {}, streamSettings: ib.streamSettings || {} }; navigator.clipboard.writeText(JSON.stringify(config, null, 2)); toast(t('inbounds.configCopied'), 'info'); }} aria-label={t('inbounds.copyJsonConfig')}><UIIcon name="copy" size={14} /></button>
                          <button type="button" className={buttonIconClass} onClick={() => handleResetInboundTraffic(ib)} title={t('inbounds.resetTraffic')} aria-label={t('inbounds.resetTraffic')}><UIIcon name="refresh" size={14} /></button>
                          <button type="button" className={cn(buttonIconClass, 'text-rose-300')} onClick={() => handleDelAllClients(ib)} title={t('inbounds.delAllClients')} aria-label={t('inbounds.delAllClients')}><UIIcon name="clients" size={14} /></button>
                          <button type="button" className={cn(buttonIconClass, 'bg-rose-500 text-white hover:bg-rose-400 hover:text-white')} onClick={() => handleDelete(ib)} title={t('inbounds.deleteInbound')} aria-label={t('inbounds.deleteInbound')}><UIIcon name="trash" size={14} /></button>
                        </div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
        <div className="mt-4 flex min-w-0 flex-wrap items-center gap-3 text-xs text-slate-500">
          <span className="whitespace-nowrap">{t('inbounds.showingCount', { filtered: filteredInbounds.length, total: inbounds.length })}</span>
          {filteredInbounds.some(ib => ib.client_count !== undefined) && (
            <span className="whitespace-nowrap">
              {t('inbounds.clientsInView', { count: filteredInbounds.reduce((s, ib) => s + (ib.client_count ?? 0), 0) })}
            </span>
          )}
          {selectedKeys.size > 0 && (
            <span className="text-cyan-300 whitespace-nowrap">
              {t('inbounds.selectedInline', { count: selectedKeys.size })}
            </span>
          )}
          <button
            type="button"
            className="inline-flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-cyan-300 whitespace-nowrap"
            title={t('inbounds.copyVisiblePortsTitle')}
            onClick={() => {
              const ports = filteredInbounds.slice(0, ibPage * ibPageSize).map(ib => ib.port).filter(Boolean).join(', ');
              navigator.clipboard.writeText(ports).then(() => toast(t('inbounds.copiedPorts', { count: filteredInbounds.slice(0, ibPage * ibPageSize).length }), 'info'));
            }}
          >
            <UIIcon name="copy" size={12} />
            {t('inbounds.copyPorts')}
          </button>
          {(() => {
            const dupCount = inbounds.filter(ib => isDuplicatePort(ib)).length;
            return dupCount > 0 ? (
              <button
                type="button"
                className="inline-flex items-center gap-1 text-[11px] text-amber-300 transition-colors hover:text-amber-200 whitespace-nowrap"
                title={t('inbounds.showDuplicateConflictsTitle')}
                onClick={() => setFilterDuplicatesOnly(v => !v)}
              >
                <UIIcon name="warning" size={12} />
                {t('inbounds.portConflicts', { count: dupCount })}
              </button>
            ) : null;
          })()}
        </div>
      </div>

      {showCloneModal && (
        <div className="fixed inset-0 z-50">
          <button type="button" className="absolute inset-0 h-full w-full bg-black/60 backdrop-blur-sm" aria-label={t('common.close')} onClick={() => setShowCloneModal(false)} />
          <aside className={drawerPanelClass} role="dialog" aria-modal="true">
            <div className={drawerHeaderClass}>
              <div className="min-w-0">
                <div className={drawerTitleClass}>{t('inbounds.cloneInbound')}</div>
                <div className={drawerSubtitleClass}>{cloneSource?.remark || '#' + cloneSource?.id}</div>
              </div>
              <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowCloneModal(false)}><UIIcon name="x" size={14} /></button>
            </div>
            <div className={drawerBodyClass}>
              <div className="grid min-w-0 grid-cols-1 gap-4">
                <div className="min-w-0">
                  <label className={fieldLabelClass}>{t('inbounds.newRemark')}</label>
                  <input type="text" className={cn(inputClass, 'w-full')} value={cloneRemark} onChange={(e) => setCloneRemark(e.target.value)} />
                </div>
                <div className="min-w-0">
                  <label className={fieldLabelClass}>{t('inbounds.newPortOptional')}</label>
                  <input type="number" className={cn(inputClass, 'w-full tabular-nums')} value={clonePort} onChange={(e) => setClonePort(e.target.value)} placeholder={t('inbounds.clonePortPlaceholder')} />
                </div>
                <div className="min-w-0">
                  <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                    <label className={fieldLabelClass}>{t('inbounds.targetNodes')}</label>
                    <div className="flex gap-1">
                      <button type="button" className={segmentButtonClass(false)} onClick={() => setCloneTargetNodeIds(new Set(allNodes.map(n => n.id)))}>{t('common.all')}</button>
                      <button type="button" className={segmentButtonClass(false)} onClick={() => setCloneTargetNodeIds(new Set())}>{t('common.none')}</button>
                    </div>
                  </div>
                  <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
                    {allNodes.map((node) => (
                      <label key={node.id} className={nodeCheckClass(cloneTargetNodeIds.has(node.id))}>
                        <input className={checkboxClass} type="checkbox" checked={cloneTargetNodeIds.has(node.id)} onChange={() => {
                          const next = new Set(cloneTargetNodeIds);
                          if (next.has(node.id)) next.delete(node.id);
                          else next.add(node.id);
                          setCloneTargetNodeIds(next);
                        }} />
                        <span className="truncate">{node.name}</span>
                      </label>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{t('inbounds.cloneSameNodeHint')}</p>
                </div>
                <p className="text-xs text-slate-500">{t('inbounds.cloneHint')}</p>
              </div>
            </div>
            <div className={drawerFooterClass}>
              <button type="button" className={buttonGhostClass} onClick={() => setShowCloneModal(false)} disabled={loading}>{t('common.cancel')}</button>
              <button type="button" className={buttonAccentClass} onClick={handleCloneSubmit} disabled={loading}>{loading ? t('inbounds.cloning') : t('inbounds.cloneInbound')}</button>
            </div>
          </aside>
        </div>
      )}

      {showAddModal && (
        <div className="fixed inset-0 z-50">
          <button type="button" className="absolute inset-0 h-full w-full bg-black/60 backdrop-blur-sm" aria-label={t('common.close')} onClick={() => setShowAddModal(false)} />
          <aside className={drawerPanelWideClass} role="dialog" aria-modal="true">
            <div className={drawerHeaderClass}>
              <div className="min-w-0">
                <div className={drawerTitleClass}>{t('inbounds.addInbound')}</div>
                <div className={drawerSubtitleClass}>{t('inbounds.addSubtitle')}</div>
              </div>
              <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowAddModal(false)}><UIIcon name="x" size={14} /></button>
            </div>
            <div className={drawerBodyClass}>
              <div className="grid min-w-0 grid-cols-1 gap-4">
                <div className="min-w-0">
                  <label className={fieldLabelClass}>{t('inbounds.template')}</label>
                  <div className="flex flex-wrap gap-1">
                    {[
                      { value: 'vless', label: 'VLESS' },
                      { value: 'vmess', label: 'VMESS' },
                      { value: 'trojan', label: 'TROJAN' },
                    ].map((option) => (
                      <button key={option.value} type="button" className={segmentButtonClass(addTemplateProtocol === option.value)} onClick={() => handleTemplateChange(option.value as 'vless' | 'vmess' | 'trojan')}>
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                    <label className={fieldLabelClass}>{t('inbounds.targetNodes')}</label>
                    <div className="flex gap-1">
                      <button type="button" className={segmentButtonClass(false)} onClick={() => setAddTargetNodeIds(new Set(allNodes.map(n => n.id)))}>{t('common.all')}</button>
                      <button type="button" className={segmentButtonClass(false)} onClick={() => setAddTargetNodeIds(new Set())}>{t('common.none')}</button>
                    </div>
                  </div>
                  <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {allNodes.map((node) => (
                      <label key={node.id} className={nodeCheckClass(addTargetNodeIds.has(node.id))}>
                        <input className={checkboxClass} type="checkbox" checked={addTargetNodeIds.has(node.id)} onChange={() => toggleAddTarget(node.id)} />
                        <span className="truncate">{node.name}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="min-w-0">
                  <label className={fieldLabelClass}>{t('inbounds.jsonConfigLabel')}</label>
                  <textarea className={cn(textareaClass, 'min-h-[360px] text-[12px]')} rows={16} value={addJsonConfig} onChange={(e) => setAddJsonConfig(e.target.value)} />
                  <p className="mt-2 text-xs text-slate-500">{t('inbounds.jsonConfigHint')}</p>
                </div>
              </div>
            </div>
            <div className={drawerFooterClass}>
              <button type="button" className={buttonGhostClass} onClick={() => setShowAddModal(false)} disabled={loading}>{t('common.cancel')}</button>
              <button type="button" className={buttonSuccessClass} onClick={handleAddInboundSubmit} disabled={loading}>{loading ? t('inbounds.adding') : t('inbounds.addInbound')}</button>
            </div>
          </aside>
        </div>
      )}
      {editingInbound && (() => {
        const nodeObj = allNodes.find(n => n.name === editingInbound.node_name);
        const nodeId = nodeObj?.id;
        if (!nodeId) return null;
        return (
          <InboundEditModal
            inbound={editingInbound}
            nodeId={nodeId}
            onClose={() => setEditingInbound(null)}
            onSaved={() => { loadInbounds(); onReload?.(); }}
          />
        );
      })()}

      {/* Import JSON Drawer */}
      {showImportModal && (
        <div className="fixed inset-0 z-50">
          <button type="button" className="absolute inset-0 h-full w-full bg-black/60 backdrop-blur-sm" aria-label={t('common.close')} onClick={() => setShowImportModal(false)} />
          <aside className={drawerPanelWideClass} role="dialog" aria-modal="true">
            <div className={drawerHeaderClass}>
              <div className="min-w-0">
                <div className={drawerTitleClass}>{t('inbounds.importInbounds')}</div>
                <div className={drawerSubtitleClass}>{t('inbounds.importSubtitle')}</div>
              </div>
              <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowImportModal(false)}><UIIcon name="x" size={14} /></button>
            </div>
            <div className={drawerBodyClass}>
              <div className="grid min-w-0 grid-cols-1 gap-4">
                <div className="min-w-0">
                  <label className={fieldLabelClass}>{t('inbounds.targetNodes')}</label>
                  <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {allNodes.map(n => (
                      <label key={n.id} className={nodeCheckClass(importTargetNodeIds.has(n.id))}>
                        <input
                          className={checkboxClass}
                          type="checkbox"
                          checked={importTargetNodeIds.has(n.id)}
                          onChange={e => {
                            setImportTargetNodeIds(prev => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(n.id); else next.delete(n.id);
                              return next;
                            });
                          }}
                        />
                        <span className="truncate">{n.name}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="min-w-0">
                  <label className={fieldLabelClass}>{t('inbounds.jsonConfig')}</label>
                  <textarea
                    className={cn(textareaClass, 'min-h-[280px] text-[12px]')}
                    rows={12}
                    value={importJson}
                    onChange={e => setImportJson(e.target.value)}
                    placeholder={'[\n  {\n    "protocol": "vless",\n    "port": 8443,\n    ...\n  }\n]'}
                  />
                </div>
                {importError && <div className="rounded-md bg-rose-500/10 px-3 py-2 text-xs text-rose-300 ring-1 ring-rose-400/25">{importError}</div>}
                {importResult && <div className="rounded-md bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300 ring-1 ring-emerald-400/25">{importResult}</div>}
              </div>
            </div>
            <div className={drawerFooterClass}>
              <button type="button" className={buttonGhostClass} onClick={() => setShowImportModal(false)}>{t('common.cancel')}</button>
              <button type="button" className={buttonAccentClass} onClick={handleImportSubmit} disabled={importLoading || !importJson.trim()}>{importLoading ? t('inbounds.importing') : t('common.import')}</button>
            </div>
          </aside>
        </div>
      )}

      {/* Inbound Config JSON Drawer */}
      {showConfigModal && configModalInbound && (
        <div className="fixed inset-0 z-50">
          <button type="button" className="absolute inset-0 h-full w-full bg-black/60 backdrop-blur-sm" aria-label={t('common.close')} onClick={() => setShowConfigModal(false)} />
          <aside className={drawerPanelWideClass} role="dialog" aria-modal="true">
            <div className={drawerHeaderClass}>
              <div className="min-w-0">
                <div className={drawerTitleClass}>{'{ }'} {configModalInbound.remark || '#' + configModalInbound.id}</div>
                <div className={drawerSubtitleClass}>{configModalInbound.protocol.toUpperCase()} - {configModalInbound.node_name}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  className={buttonNeutralClass}
                  onClick={() => { navigator.clipboard.writeText(JSON.stringify(configModalInbound, null, 2)); toast(t('inbounds.configCopied'), 'info'); }}
                >
                  <UIIcon name="copy" size={14} />
                  {t('common.copy')}
                </button>
                <button type="button" className={buttonIconClass} aria-label={t('common.close')} onClick={() => setShowConfigModal(false)}><UIIcon name="x" size={14} /></button>
              </div>
            </div>
            <div className={drawerBodyClass}>
              <pre className="m-0 min-w-0 overflow-x-auto rounded-lg bg-[#0a0e1a] p-4 text-xs leading-relaxed text-slate-200 ring-1 ring-cyan-500/10">
                {JSON.stringify(configModalInbound, null, 2)}
              </pre>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
};
