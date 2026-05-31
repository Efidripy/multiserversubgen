import React, { useRef, useState, useEffect } from 'react';
import { useToast } from './Toast';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';
import EmptyState from './EmptyState';
import { InboundEditModal } from './InboundEditModal';
import { readStaleCache, writeStaleCache } from '../services/staleCache';

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
  client_count?: number;
  streamSettings?: Record<string, any>;
  settings?: Record<string, any>;
}

interface NodeInfo {
  id: number;
  name: string;
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

export const InboundManager: React.FC<InboundManagerProps> = ({ onReload, onNavigateToClients, onAddClientToInbound }) => {
  const { toast } = useToast();
  const { t } = useTranslation();

  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [filteredInbounds, setFilteredInbounds] = useState<Inbound[]>([]);
  const [nodeNameToId, setNodeNameToId] = useState<Record<string, number>>({});
  const [allNodes, setAllNodes] = useState<NodeInfo[]>([]);

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

  // Inbound config viewer modal
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [configModalInbound, setConfigModalInbound] = useState<Inbound | null>(null);

  const [editingInbound, setEditingInbound] = useState<Inbound | null>(null);

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
  }, [inbounds, filterProtocol, filterSecurity, filterNode, sortField, sortDirection]);

  const loadInbounds = async (silent = false) => {
    if (!silent) setPageLoading(true);
    setError('');

    const requestId = Date.now();
    requestIdRef.current = requestId;

    try {
      // Single parallel fetch — backend returns from cache (30s fresh / 300s stale).
      const [nodesRes, inboundsRes] = await Promise.all([
        api.get('/v1/nodes', { auth: getAuth() }),
        api.get('/v1/inbounds', { auth: getAuth() }),
      ]);

      if (requestIdRef.current !== requestId) return;

      const nodes: NodeInfo[] = nodesRes.data || [];
      const nameMap: Record<string, number> = {};
      nodes.forEach((n) => { nameMap[n.name] = n.id; });

      setAllNodes(nodes);
      setNodeNameToId(nameMap);
      if (addTargetNodeIds.size === 0) {
        setAddTargetNodeIds(new Set(nodes.map((n) => n.id)));
      }

      const rawInbounds: any[] = inboundsRes.data?.inbounds || [];
      const normalized: Inbound[] = rawInbounds.map((ib: any) => {
        const streamSettings = parseMaybeJsonObject(ib.streamSettings);
        const settings = parseMaybeJsonObject(ib.settings);
        const security = ib.security || streamSettings.security || '';
        return {
          id: ib.id,
          node_name: ib.node_name || '',
          node_ip: ib.node_name || '',
          protocol: ib.protocol,
          port: Number(ib.port || 0),
          remark: ib.remark || '',
          enable: Boolean(ib.enable),
          security,
          is_reality: security === 'reality',
          settings: Object.keys(settings).length > 0 ? settings : undefined,
          streamSettings: Object.keys(streamSettings).length > 0 ? streamSettings : undefined,
        };
      });

      setInbounds(normalized);
      if (!silent) setPageLoading(false);

    } catch (err: any) {
      setError(err.response?.data?.detail || t('messages.operationFailed'));
      if (!silent) setPageLoading(false);
    }
  };

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
    sortField === field ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : '';

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
        throw new Error('Inbound config must be a JSON object');
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
        setError('Invalid JSON in inbound config');
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
      setImportError('Invalid JSON — must be an array of inbound objects');
      return;
    }
    if (parsed.length === 0) { setImportError('No inbounds to import'); return; }
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
    const resultMsg = `Import done: ${ok} added, ${fail} failed`;
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
    if (!window.confirm('Reset ALL client traffic on ALL nodes? This cannot be undone.')) return;
    try {
      const res = await api.post('/v1/automation/reset-all-traffic', {}, { auth: getAuth() });
      const total = res.data?.total_reset ?? res.data?.count ?? '?';
      toast(`Traffic reset for ${total} clients`, 'success');
      await loadInbounds();
    } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
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

  return (
    <div className="inbound-manager">
      <div className="card p-3 mb-4" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0 d-flex align-items-center gap-2" style={{ color: 'var(--accent)' }}>
            <UIIcon name="inbounds" size={16} />
            {t('inbounds.title')}
          </h5>
          {inbounds.length > 0 && (
            <div className="d-flex gap-2">
              {[
                { label: 'Inbounds', value: inbounds.length, color: 'var(--text-primary)' },
                { label: 'Active', value: inbounds.filter(ib => ib.enable).length, color: 'var(--success)' },
                { label: 'Clients', value: inbounds.reduce((s, ib) => s + (ib.client_count ?? 0), 0), color: 'var(--accent)' },
              ].map(s => (
                <span key={s.label} className="badge px-2 py-1" style={{ backgroundColor: 'var(--bg-tertiary)', color: s.color, fontWeight: 400, fontSize: '0.78rem' }}>
                  {s.label}: <strong>{s.value}</strong>
                </span>
              ))}
            </div>
          )}
        </div>

        {error && (
          <div className="alert alert-danger">
            {error}
          </div>
        )}

        <div className="panel-grid mb-3">
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('common.actions')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('inbounds.actionsHint')}
                </p>
              </div>
            </div>
            <div className="panel-inline-actions">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--success)', borderColor: 'var(--success)', color: '#ffffff' }}
                onClick={() => setShowAddModal(true)}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="plus" size={14} />
                  Add Inbound
                </span>
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                onClick={() => { void loadInbounds(); }}
                disabled={loading}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="refresh" size={14} />
                  {t('common.refresh')}
                </span>
              </button>
            </div>
          </div>

          <div className="panel-block panel-block--wide">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('common.filter')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('inbounds.filtersHint')}
                </p>
              </div>
            </div>
            <div className="panel-block__stack">
              <input
                type="text"
                className="form-control form-control-sm"
                placeholder="Search remark, port, node…"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)', maxWidth: '220px' }}
              />
              <ChoiceChips
                options={[{ value: '', label: t('inbounds.allProtocols') }, ...protocols.map((p) => ({ value: p, label: p.toUpperCase() }))]}
                value={filterProtocol}
                onChange={(value) => setFilterProtocol(value)}
                
              />
              <ChoiceChips
                options={[{ value: '', label: t('inbounds.allSecurity') }, ...securities.map((s) => ({ value: s, label: s || 'none' }))]}
                value={filterSecurity}
                onChange={(value) => setFilterSecurity(value)}
                
              />
              <ChoiceChips
                options={[{ value: '', label: t('inbounds.allNodes') }, ...nodes.map((n) => ({ value: n, label: n }))]}
                value={filterNode}
                onChange={(value) => setFilterNode(value)}
                
              />
              <ChoiceChips
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'enabled', label: '● Active' },
                  { value: 'disabled', label: '○ Disabled' },
                ]}
                value={filterEnabledStatus}
                onChange={(value) => setFilterEnabledStatus(value as 'all' | 'enabled' | 'disabled')}
                
              />
              <button
                className="btn btn-sm"
                style={{ backgroundColor: filterEmptyOnly ? 'var(--warning)' : 'var(--bg-tertiary)', borderColor: filterEmptyOnly ? 'var(--warning)' : 'var(--border-color)', color: filterEmptyOnly ? '#000' : 'var(--text-primary)' }}
                onClick={() => setFilterEmptyOnly(v => !v)}
                title="Show only inbounds with 0 clients"
              >
                ∅ Empty only
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: filterDuplicatesOnly ? 'var(--danger)' : 'var(--bg-tertiary)', borderColor: filterDuplicatesOnly ? 'var(--danger)' : 'var(--border-color)', color: filterDuplicatesOnly ? '#fff' : 'var(--text-primary)' }}
                onClick={() => setFilterDuplicatesOnly(v => !v)}
                title="Show only inbounds with duplicate ports on the same node"
              >
                ⚠ Duplicates
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
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

        </div>

        <div className="card p-2 mb-3" style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)' }}>
          <div className="row g-2 align-items-end">
            <div className="col-lg-3 col-md-6">
              <div className="small" style={{ color: 'var(--text-secondary)' }}>
                {t('inbounds.selectedCount', { count: selectedKeys.size })}
              </div>
              <div className="d-flex gap-2 mt-1">
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                  onClick={toggleSelectAllFiltered}
                >
                  {allFilteredSelected ? t('common.deselectAll') : t('common.selectAll')}
                </button>
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                  onClick={clearSelection}
                  disabled={selectedKeys.size === 0}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </div>

            <div className="col-lg-3 col-md-6">
              <label className="form-label small mb-1" style={{ color: 'var(--text-secondary)' }}>{t('inbounds.batchRemark')}</label>
              <input
                className="form-control form-control-sm"
                value={batchRemark}
                onChange={(e) => setBatchRemark(e.target.value)}
                placeholder={t('inbounds.batchRemarkPlaceholder')}
                style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
              />
            </div>

            <div className="col-lg-2 col-md-6">
              <label className="form-label small mb-1" style={{ color: 'var(--text-secondary)' }}>{t('inbounds.batchEnableMode')}</label>
              <ChoiceChips
                options={[
                  { value: 'none', label: t('common.no') },
                  { value: 'enable', label: t('inbounds.batchEnable') },
                  { value: 'disable', label: t('inbounds.batchDisable') },
                ]}
                value={batchEnableMode}
                onChange={(value) => setBatchEnableMode(value)}
                
              />
            </div>

            <div className="col-lg-4 col-md-12 d-flex gap-2 flex-wrap">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--success)', borderColor: 'var(--success)', color: '#ffffff' }}
                onClick={() => handleBatchEnable(true)}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchEnable')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--warning)', borderColor: 'var(--warning)', color: 'var(--text-primary)' }}
                onClick={() => handleBatchEnable(false)}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchDisable')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--info)', borderColor: 'var(--info)', color: '#ffffff' }}
                onClick={handleBatchUpdate}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchUpdate')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--danger)', borderColor: 'var(--danger)', color: '#ffffff' }}
                onClick={handleBatchDelete}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchDelete')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--warning)' + '22', borderColor: 'var(--warning)' + '66', color: 'var(--warning)' }}
                title="Reset traffic for selected inbounds"
                disabled={loading || selectedKeys.size === 0}
                onClick={async () => {
                  if (!window.confirm(`Reset traffic for ${selectedKeys.size} selected inbound(s)?`)) return;
                  let ok = 0; let fail = 0;
                  for (const ib of selectedInbounds) {
                    const nodeObj = allNodes.find(n => n.name === ib.node_name);
                    if (!nodeObj) { fail++; continue; }
                    try {
                      await api.post(`/v1/inbounds/${nodeObj.id}/${ib.id}/reset-traffic`, {}, { auth: getAuth() });
                      ok++;
                    } catch { fail++; }
                  }
                  toast(`Reset traffic: ${ok} done${fail ? `, ${fail} failed` : ''}`, ok > 0 ? 'success' : 'error');
                }}
              >
                ↺ Reset Selected
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--danger)' + '22', borderColor: 'var(--danger)' + '66', color: 'var(--danger)' }}
                title="Reset ALL client traffic on ALL nodes"
                onClick={handleResetAllTraffic}
              >
                ↺ Reset All Traffic
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                title="Import inbounds from JSON"
                onClick={() => { setImportJson(''); setImportTargetNodeIds(new Set()); setImportError(''); setImportResult(''); setShowImportModal(true); }}
              >
                ⬆ Import JSON
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                title="Export selected inbounds as JSON (all visible if none selected)"
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
                  toast(`Exported ${toExport.length} inbound(s)`, 'success');
                }}
              >
                ⬇ Export JSON
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                title="Export selected/visible inbounds as CSV"
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
                  toast(`Exported ${toExport.length} inbound(s) as CSV`, 'success');
                }}
              >
                ⬇ CSV
              </button>
            </div>
          </div>
        </div>

        {pageLoading && filteredInbounds.length > 0 && (
          <div className="table-loading-bar mb-1" />
        )}
        {pageLoading && filteredInbounds.length === 0 && (
          <div className="table-responsive">
            <table className="skeleton-table">
              <tbody>
                {Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td style={{ width: 36 }}><div className="skeleton-cell skeleton-cell--circle" /></td>
                    <td style={{ width: '22%' }}><div className="skeleton-cell skeleton-cell--lg" /></td>
                    <td style={{ width: '14%' }}><div className="skeleton-cell skeleton-cell--md" /></td>
                    <td style={{ width: '10%' }}><div className="skeleton-cell skeleton-cell--sm" /></td>
                    <td style={{ width: '8%' }}><div className="skeleton-cell skeleton-cell--sm" /></td>
                    <td style={{ width: '10%' }}><div className="skeleton-cell skeleton-cell--sm" /></td>
                    <td style={{ width: '8%' }}><div className="skeleton-cell skeleton-cell--xs" /></td>
                    <td style={{ width: '10%' }}><div className="skeleton-cell skeleton-cell--badge" /></td>
                    <td style={{ width: '14%' }}><div className="skeleton-cell skeleton-cell--md" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!pageLoading && filteredInbounds.length === 0 && inbounds.length === 0 && (
          <EmptyState icon="⇄" title="No inbounds yet" hint="Add a new inbound or clone one from an existing node." />
        )}
        {!pageLoading && filteredInbounds.length === 0 && inbounds.length > 0 && (
          <EmptyState icon="⊘" title="No inbounds match filters" hint="Clear the active filters to see all inbounds." />
        )}

        {inbounds.length > 0 && (() => {
          const enabled = inbounds.filter(ib => ib.enable).length;
          const totalClients = inbounds.reduce((s, ib) => s + (ib.client_count ?? 0), 0);
          const byProto = inbounds.reduce<Record<string, number>>((acc, ib) => { acc[ib.protocol] = (acc[ib.protocol] || 0) + 1; return acc; }, {});
          return (
            <div className="d-flex flex-wrap gap-2 mb-2">
              {[
                { label: 'Total', value: inbounds.length, color: 'var(--text-primary)' },
                { label: 'Enabled', value: enabled, color: 'var(--success)' },
                { label: 'Disabled', value: inbounds.length - enabled, color: 'var(--text-secondary)' },
                ...(totalClients > 0 ? [{ label: 'Clients', value: totalClients, color: 'var(--accent)' }] : []),
                ...Object.entries(byProto).map(([p, n]) => ({ label: p.toUpperCase(), value: n, color: 'var(--info)' })),
              ].map(s => (
                <span key={s.label} className="badge px-2 py-1" style={{ backgroundColor: 'var(--bg-tertiary)', color: s.color, fontWeight: 400, fontSize: '0.75rem' }}>
                  {s.label}: <strong>{s.value}</strong>
                </span>
              ))}
            </div>
          );
        })()}

        {filteredInbounds.length > ibPageSize && (
          <div className="d-flex align-items-center gap-2 mb-2 flex-wrap small" style={{ color: 'var(--text-secondary)' }}>
            <span>Page {ibPage}/{Math.ceil(filteredInbounds.length / ibPageSize)} ({(ibPage - 1) * ibPageSize + 1}–{Math.min(ibPage * ibPageSize, filteredInbounds.length)} of {filteredInbounds.length})</span>
            <div className="d-flex gap-1">
              <button className="btn btn-sm" style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)', padding: '1px 6px' }} disabled={ibPage <= 1} onClick={() => setIbPage(p => p - 1)}>‹</button>
              <button className="btn btn-sm" style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)', padding: '1px 6px' }} disabled={ibPage >= Math.ceil(filteredInbounds.length / ibPageSize)} onClick={() => setIbPage(p => p + 1)}>›</button>
            </div>
            <select className="form-select form-select-sm" style={{ width: 'auto', backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)', fontSize: '0.72rem' }}
              value={ibPageSize} onChange={e => { setIbPageSize(Number(e.target.value)); setIbPage(1); }}>
              {[25, 50, 100, 200].map(n => <option key={n} value={n}>{n}/page</option>)}
            </select>
          </div>
        )}

        {filteredInbounds.length > 0 && (
        <div className="table-responsive">
          <table className="table table-sm table-hover" style={{ color: 'var(--text-primary)' }}>
            <thead>
              <tr style={{ borderColor: 'var(--border-color)' }}>
                <th style={{ color: 'var(--text-secondary)', width: '40px' }}>
                  <input
                    type="checkbox"
                    checked={allFilteredSelected}
                    onChange={toggleSelectAllFiltered}
                    aria-label={t('common.selectAll')}
                  />
                </th>
                <th style={{ color: 'var(--text-secondary)' }}>
                  <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('node')}>
                    {t('common.name')}{sortIndicator('node')}
                  </button>
                </th>
                <th style={{ color: 'var(--text-secondary)' }}>
                  <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('name')}>
                    {t('inbounds.remark')}{sortIndicator('name')}
                  </button>
                </th>
                <th style={{ color: 'var(--text-secondary)' }}>
                  <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('protocol')}>
                    {t('inbounds.protocol')}{sortIndicator('protocol')}
                  </button>
                </th>
                <th style={{ color: 'var(--text-secondary)' }}>
                  <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('port')}>
                    {t('inbounds.port')}{sortIndicator('port')}
                  </button>
                </th>
                <th style={{ color: 'var(--text-secondary)' }}>{t('inbounds.security')}</th>
                <th style={{ color: 'var(--text-secondary)' }}>
                  <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('status')}>
                    {t('common.status')}{sortIndicator('status')}
                  </button>
                </th>
                <th style={{ color: 'var(--text-secondary)' }}>
                  <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }}
                    onClick={() => applySortFromHeader('clients')} title="Sort by client count">
                    Clients{sortField === 'clients' ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : ''}
                  </button>
                </th>
                <th style={{ color: 'var(--text-secondary)' }}>{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {filteredInbounds.slice((ibPage - 1) * ibPageSize, ibPage * ibPageSize).map((ib) => (
                <tr key={inboundKey(ib)} style={{ borderColor: 'var(--border-color)', backgroundColor: !ib.enable ? 'var(--bg-tertiary)' + '60' : 'transparent', opacity: !ib.enable ? 0.75 : 1 }}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedKeys.has(inboundKey(ib))}
                      onChange={() => toggleSelectOne(ib)}
                      aria-label={`Select ${ib.remark || ib.id}`}
                    />
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{ backgroundColor: filterNode === ib.node_name ? 'var(--accent)' : 'var(--bg-tertiary)', color: filterNode === ib.node_name ? '#000f14' : 'var(--text-primary)', cursor: 'pointer' }}
                      title={filterNode === ib.node_name ? 'Click to clear node filter' : `Click to filter by ${ib.node_name}`}
                      onClick={() => setFilterNode(prev => prev === ib.node_name ? '' : ib.node_name)}
                    >
                      {ib.node_name}
                    </span>
                  </td>
                  <td
                    title="Double-click to quick edit remark"
                    onDoubleClick={async () => {
                      const newRemark = window.prompt(`New remark for inbound #${ib.id} (${ib.node_name}):`, ib.remark || '');
                      if (newRemark === null || newRemark === ib.remark) return;
                      const nodeObj = allNodes.find(n => n.name === ib.node_name);
                      if (!nodeObj) return;
                      try {
                        await api.put(`/v1/inbounds/${nodeObj.id}/${ib.id}`, { remark: newRemark }, { auth: getAuth() });
                        setInbounds(prev => prev.map(x => inboundKey(x) === inboundKey(ib) ? { ...x, remark: newRemark } : x));
                        toast(`Remark updated: ${newRemark || '(empty)'}`, 'success');
                      } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                    }}
                  >
                    {ib.remark || <span style={{ color: 'var(--text-secondary)' }}>-</span>}
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{ backgroundColor: filterProtocol === ib.protocol ? 'var(--warning)' : 'var(--accent)', cursor: 'pointer' }}
                      title={filterProtocol === ib.protocol ? 'Click to clear protocol filter' : `Click to filter by ${ib.protocol}`}
                      onClick={() => setFilterProtocol(prev => prev === ib.protocol ? '' : ib.protocol)}
                    >
                      {ib.protocol.toUpperCase()}
                    </span>
                  </td>
                  <td className="text-monospace">
                    <span
                      style={isDuplicatePort(ib) ? { color: 'var(--warning)', fontWeight: 700 } : undefined}
                      title={isDuplicatePort(ib) ? `⚠ Port ${ib.port} is used by multiple inbounds on ${ib.node_name}` : undefined}
                    >
                      {ib.port}
                      {isDuplicatePort(ib) && <span className="ms-1" style={{ fontSize: '0.65rem' }}>⚠</span>}
                    </span>
                    <button className="btn btn-sm p-0 ms-1" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', opacity: 0.5, fontSize: '0.65rem' }}
                      title="Copy port number"
                      onClick={() => navigator.clipboard.writeText(String(ib.port))}>📋</button>
                  </td>
                  <td>
                    {ib.is_reality && (
                      <span className="badge" style={{ backgroundColor: filterSecurity === 'reality' ? 'var(--warning)' : 'var(--success)', cursor: 'pointer' }}
                        onClick={() => setFilterSecurity(prev => prev === 'reality' ? '' : 'reality')} title="Filter by Reality">
                        Reality
                      </span>
                    )}
                    {!ib.is_reality && ib.security && (
                      <span className="badge" style={{ backgroundColor: filterSecurity === ib.security ? 'var(--warning)' : 'var(--info)', cursor: 'pointer' }}
                        onClick={() => setFilterSecurity(prev => prev === (ib.security ?? '') ? '' : (ib.security ?? ''))}
                        title={`Filter by ${ib.security}`}>
                        {ib.security}
                      </span>
                    )}
                    {!ib.security && <span style={{ color: 'var(--text-secondary)' }}>-</span>}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm px-1 py-0"
                      style={{
                        background: 'none', border: 'none',
                        color: ib.enable ? 'var(--success)' : 'var(--text-secondary)',
                        fontSize: '0.85rem', cursor: 'pointer'
                      }}
                      title={ib.enable ? t('common.enabled') + ' — click to disable' : t('common.disabled') + ' — click to enable'}
                      onClick={async () => {
                        const nodeObj = allNodes.find(n => n.name === ib.node_name);
                        if (!nodeObj) return;
                        const { user, password } = getAuth();
                        try {
                          await api.post(`/v1/inbounds/${nodeObj.id}/${ib.id}/set-enable`, { enable: !ib.enable }, { auth: { username: user, password } });
                          setInbounds(prev => prev.map(x => inboundKey(x) === inboundKey(ib) ? { ...x, enable: !ib.enable } : x));
                          toast(`${ib.remark || `#${ib.id}`}: ${!ib.enable ? 'enabled' : 'disabled'}`, 'success');
                        } catch (e: any) { toast(e.response?.data?.detail || 'Failed', 'error'); }
                      }}
                    >
                      {ib.enable ? '● ' + t('common.enabled') : '○ ' + t('common.disabled')}
                    </button>
                  </td>
                  <td>
                    {ib.client_count !== undefined ? (
                      <span
                        className="badge"
                        style={{
                          backgroundColor: ib.client_count > 0 ? 'var(--accent)' : 'var(--bg-tertiary)',
                          color: ib.client_count > 0 ? '#000f14' : 'var(--text-secondary)',
                          cursor: ib.client_count > 0 && onNavigateToClients ? 'pointer' : 'default',
                        }}
                        title={ib.client_count > 0 && onNavigateToClients ? `View ${ib.client_count} clients in this inbound` : undefined}
                        onClick={() => ib.client_count && ib.client_count > 0 && onNavigateToClients && onNavigateToClients(ib.id, ib.remark || `#${ib.id}`)}
                      >
                        {ib.client_count}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-secondary)' }}>—</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                      onClick={() => handleEditClick(ib)}
                      title={t('inbounds.editInbound')}
                    >
                      <UIIcon name="edit" size={14} />
                    </button>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: 'var(--success)', borderColor: 'var(--success)', color: '#fff' }}
                      title="Add client to this inbound"
                      onClick={() => onAddClientToInbound && onAddClientToInbound(ib.id, ib.node_name)}
                      disabled={!onAddClientToInbound}
                    >
                      +
                    </button>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                      onClick={() => handleCloneClick(ib)}
                      title={t('inbounds.cloneInbound')}
                    >
                      <UIIcon name="copy" size={14} />
                    </button>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                      title="View full inbound config as JSON"
                      onClick={() => { setConfigModalInbound(ib); setShowConfigModal(true); }}
                    >
                      {'{}'}
                    </button>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                      title="Copy JSON config"
                      onClick={() => {
                        const config = {
                          protocol: ib.protocol,
                          port: ib.port,
                          remark: ib.remark,
                          settings: ib.settings || {},
                          streamSettings: ib.streamSettings || {},
                        };
                        navigator.clipboard.writeText(JSON.stringify(config, null, 2));
                        toast('Config copied', 'info');
                      }}
                    >
                      <UIIcon name="copy" size={14} />
                    </button>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: 'var(--warning)', borderColor: 'var(--warning)', color: '#000' }}
                      onClick={() => handleResetInboundTraffic(ib)}
                      title={t('inbounds.resetTraffic')}
                    >
                      <UIIcon name="refresh" size={14} />
                    </button>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--danger)' }}
                      onClick={() => handleDelAllClients(ib)}
                      title={t('inbounds.delAllClients')}
                    >
                      <UIIcon name="clients" size={14} />
                    </button>
                    <button
                      className="btn btn-sm"
                      style={{ backgroundColor: 'var(--danger)', borderColor: 'var(--danger)', color: '#ffffff' }}
                      onClick={() => handleDelete(ib)}
                      title={t('inbounds.deleteInbound')}
                    >
                      <UIIcon name="trash" size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}

        <div className="mt-2 small d-flex gap-3 align-items-center" style={{ color: 'var(--text-secondary)' }}>
          <span>{t('inbounds.showingCount', { filtered: filteredInbounds.length, total: inbounds.length })}</span>
          {filteredInbounds.some(ib => ib.client_count !== undefined) && (
            <span>
              Clients in view: {filteredInbounds.reduce((s, ib) => s + (ib.client_count ?? 0), 0)}
            </span>
          )}
          {selectedKeys.size > 0 && (
            <span style={{ color: 'var(--accent)' }}>
              {selectedKeys.size} selected
            </span>
          )}
          <button className="btn btn-sm py-0 px-1" style={{ backgroundColor: 'transparent', border: 'none', color: 'var(--text-secondary)', fontSize: '0.72rem' }}
            title="Copy all visible ports as comma-separated list"
            onClick={() => {
              const ports = filteredInbounds.slice(0, ibPage * ibPageSize).map(ib => ib.port).filter(Boolean).join(', ');
              navigator.clipboard.writeText(ports).then(() => toast(`Copied ${filteredInbounds.slice(0, ibPage * ibPageSize).length} ports`, 'info'));
            }}>
            📋 Copy ports
          </button>
          {(() => {
            const dupCount = inbounds.filter(ib => isDuplicatePort(ib)).length;
            return dupCount > 0 ? (
              <button
                className="btn btn-sm py-0 px-1"
                style={{ background: 'none', border: 'none', color: 'var(--warning)', fontSize: '0.72rem' }}
                title="Click to show only duplicate port conflicts"
                onClick={() => setFilterDuplicatesOnly(v => !v)}
              >
                ⚠ {dupCount} port conflict{dupCount !== 1 ? 's' : ''}
              </button>
            ) : null;
          })()}
        </div>
      </div>

      {showCloneModal && (
        <div className="drawer">
          <div className="drawer__backdrop" onClick={() => setShowCloneModal(false)} />
          <div className="drawer__panel">
            <div className="drawer__header">
              <div>
                <div className="drawer__title">{t('inbounds.cloneInbound')}</div>
                <div className="drawer__subtitle">{cloneSource?.remark || `#${cloneSource?.id}`}</div>
              </div>
              <button className="drawer__close" aria-label="Close" onClick={() => setShowCloneModal(false)}>✕</button>
            </div>
            <div className="drawer__body">
              <div className="mb-3">
                <label className="form-label small">{t('inbounds.newRemark')}</label>
                <input type="text" className="form-control" value={cloneRemark}
                  onChange={(e) => setCloneRemark(e.target.value)} />
              </div>
              <div className="mb-3">
                <label className="form-label small">{t('inbounds.newPortOptional')}</label>
                <input type="number" className="form-control" value={clonePort}
                  onChange={(e) => setClonePort(e.target.value)}
                  placeholder={t('inbounds.clonePortPlaceholder')} />
              </div>
              <div className="mb-3">
                <div className="d-flex justify-content-between align-items-center mb-2">
                  <label className="form-label small mb-0">{t('inbounds.targetNodes')}</label>
                  <div className="d-flex gap-1">
                    <button className="btn btn-sm btn-neutral" style={{ fontSize: '0.72rem' }}
                      onClick={() => setCloneTargetNodeIds(new Set(allNodes.map(n => n.id)))}>All</button>
                    <button className="btn btn-sm btn-neutral" style={{ fontSize: '0.72rem' }}
                      onClick={() => setCloneTargetNodeIds(new Set())}>None</button>
                  </div>
                </div>
                <div className="d-flex flex-wrap gap-2">
                  {allNodes.map((node) => (
                    <label key={node.id} className="d-inline-flex align-items-center gap-2 small">
                      <input type="checkbox" checked={cloneTargetNodeIds.has(node.id)}
                        onChange={() => {
                          const next = new Set(cloneTargetNodeIds);
                          if (next.has(node.id)) next.delete(node.id);
                          else next.add(node.id);
                          setCloneTargetNodeIds(next);
                        }} />
                      {node.name}
                    </label>
                  ))}
                </div>
                <p className="small mt-2" style={{ color: 'var(--text-secondary)' }}>You can clone into the same node too.</p>
              </div>
              <p className="small" style={{ color: 'var(--text-secondary)' }}>{t('inbounds.cloneHint')}</p>
            </div>
            <div className="drawer__footer">
              <button className="btn btn-ghost-accent" onClick={() => setShowCloneModal(false)} disabled={loading}>
                {t('common.cancel')}
              </button>
              <button className="btn btn-accent" onClick={handleCloneSubmit} disabled={loading}>
                {loading ? t('inbounds.cloning') : t('inbounds.cloneInbound')}
              </button>
            </div>
          </div>
        </div>
      )}

      {showAddModal && (
        <div className="drawer">
          <div className="drawer__backdrop" onClick={() => setShowAddModal(false)} />
          <div className="drawer__panel drawer__panel--wide">
            <div className="drawer__header">
              <div>
                <div className="drawer__title">Add Inbound</div>
                <div className="drawer__subtitle">Template + JSON config</div>
              </div>
              <button className="drawer__close" aria-label="Close" onClick={() => setShowAddModal(false)}>✕</button>
            </div>
            <div className="drawer__body">
              <div className="mb-3">
                <label className="form-label small">{t('inbounds.template')}</label>
                <ChoiceChips
                  options={[
                    { value: 'vless', label: 'VLESS' },
                    { value: 'vmess', label: 'VMESS' },
                    { value: 'trojan', label: 'TROJAN' },
                  ]}
                  value={addTemplateProtocol}
                  onChange={(value) => handleTemplateChange(value)}
                />
              </div>
              <div className="mb-3">
                <div className="d-flex justify-content-between align-items-center mb-2">
                  <label className="form-label small mb-0">{t('inbounds.targetNodes')}</label>
                  <div className="d-flex gap-1">
                    <button className="btn btn-sm btn-neutral" style={{ fontSize: '0.72rem' }}
                      onClick={() => setAddTargetNodeIds(new Set(allNodes.map(n => n.id)))}>All</button>
                    <button className="btn btn-sm btn-neutral" style={{ fontSize: '0.72rem' }}
                      onClick={() => setAddTargetNodeIds(new Set())}>None</button>
                  </div>
                </div>
                <div className="d-flex flex-wrap gap-2">
                  {allNodes.map((node) => (
                    <label key={node.id} className="d-inline-flex align-items-center gap-2 small">
                      <input type="checkbox" checked={addTargetNodeIds.has(node.id)}
                        onChange={() => toggleAddTarget(node.id)} />
                      {node.name}
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="form-label small">{t('inbounds.jsonConfigLabel')}</label>
                <textarea className="form-control" rows={16} value={addJsonConfig}
                  onChange={(e) => setAddJsonConfig(e.target.value)}
                  style={{ fontFamily: 'monospace', fontSize: '12px' }} />
                <p className="small mt-2" style={{ color: 'var(--text-secondary)' }}>{t('inbounds.jsonConfigHint')}</p>
              </div>
            </div>
            <div className="drawer__footer">
              <button className="btn btn-ghost-accent" onClick={() => setShowAddModal(false)} disabled={loading}>
                {t('common.cancel')}
              </button>
              <button className="btn btn-success-fill" onClick={handleAddInboundSubmit} disabled={loading}>
                {loading ? t('inbounds.adding') : t('inbounds.addInbound')}
              </button>
            </div>
          </div>
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
        <div className="drawer">
          <div className="drawer__backdrop" onClick={() => setShowImportModal(false)} />
          <div className="drawer__panel drawer__panel--wide">
            <div className="drawer__header">
              <div>
                <div className="drawer__title">Import Inbounds</div>
                <div className="drawer__subtitle">Paste JSON array — compatible with Export format</div>
              </div>
              <button className="drawer__close" aria-label="Close" onClick={() => setShowImportModal(false)}>✕</button>
            </div>
            <div className="drawer__body">
              <div className="mb-3">
                <label className="form-label small">Target nodes</label>
                <div className="d-flex flex-wrap gap-1">
                  {allNodes.map(n => (
                    <label key={n.id} className="d-flex align-items-center gap-1 px-2 py-1 rounded"
                      style={{ backgroundColor: 'var(--bg-tertiary)', cursor: 'pointer', fontSize: '0.8rem' }}>
                      <input type="checkbox" checked={importTargetNodeIds.has(n.id)}
                        onChange={e => {
                          setImportTargetNodeIds(prev => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(n.id); else next.delete(n.id);
                            return next;
                          });
                        }} />
                      {n.name}
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="form-label small">JSON config</label>
                <textarea className="form-control font-monospace" rows={12}
                  value={importJson} onChange={e => setImportJson(e.target.value)}
                  placeholder={'[\n  {\n    "protocol": "vless",\n    "port": 8443,\n    ...\n  }\n]'}
                  style={{ fontSize: '12px' }} />
              </div>
              {importError && <div className="alert alert-danger mt-2 py-1 small">{importError}</div>}
              {importResult && <div className="alert alert-success mt-2 py-1 small">{importResult}</div>}
            </div>
            <div className="drawer__footer">
              <button className="btn btn-ghost-accent" onClick={() => setShowImportModal(false)}>Cancel</button>
              <button className="btn btn-accent" onClick={handleImportSubmit}
                disabled={importLoading || !importJson.trim()}>
                {importLoading ? 'Importing…' : 'Import'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Inbound Config JSON Drawer */}
      {showConfigModal && configModalInbound && (
        <div className="drawer">
          <div className="drawer__backdrop" onClick={() => setShowConfigModal(false)} />
          <div className="drawer__panel drawer__panel--wide">
            <div className="drawer__header">
              <div>
                <div className="drawer__title">{'{ }'} {configModalInbound.remark || `#${configModalInbound.id}`}</div>
                <div className="drawer__subtitle">{configModalInbound.protocol.toUpperCase()} · {configModalInbound.node_name}</div>
              </div>
              <div className="d-flex gap-2 align-items-center">
                <button className="btn btn-sm btn-neutral"
                  onClick={() => { navigator.clipboard.writeText(JSON.stringify(configModalInbound, null, 2)); toast('Config copied', 'info'); }}>
                  📋 Copy
                </button>
                <button className="drawer__close" aria-label="Close" onClick={() => setShowConfigModal(false)}>✕</button>
              </div>
            </div>
            <div className="drawer__body">
              <pre style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '12px', margin: 0, fontSize: '12px', lineHeight: 1.5, overflowX: 'auto' }}>
                {JSON.stringify(configModalInbound, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
