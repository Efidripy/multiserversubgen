import api from './client';
import { getAuth } from '../auth';
import {
  getNodePanelUpdateInfo,
  getNodeServerStatus,
  listNodes,
  type NodeRecord,
} from './nodes';

export interface DashboardTopClient {
  email: string;
  upload: number;
  download: number;
  total: number;
}

export interface DashboardSummaryData {
  nodes_total: number;
  clients_total: number;
  online_clients_total: number;
  online_by_node: Record<string, number>;
  traffic: { upload: number; download: number; total: number };
  top_clients: DashboardTopClient[];
}

export interface DashboardHeaderMetrics {
  registeredNodes: number;
  reachableNow: number;
  authIssues: number;
  offlineNodes: number;
  xrayRunning: number;
  onlineClients: number;
}

export interface DashboardServerStatus {
  nodeId?: number;
  node: string;
  available: boolean;
  loadingDetails?: boolean;
  status?: string;
  reason?: string;
  timestamp?: string;
  error?: string;
  system?: any;
  xray?: any;
  network?: any;
}

interface SnapshotNode {
  node_id?: number;
  name: string;
  available: boolean;
  status?: string;
  reason?: string;
  error?: string;
  xray_running?: boolean;
  timestamp?: number;
  online_clients?: number;
}

export interface DashboardServerDeck {
  servers: DashboardServerStatus[];
  nodeIdsByName: Record<string, number>;
  latencyByNode: Record<number, number>;
  updateAvailableNodeIds: number[];
}

export interface DashboardServerDeckOptions {
  includeLiveStatus?: boolean;
  includePanelUpdateChecks?: boolean;
}

const toFiniteNumber = (value: unknown): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const normalizeNumberRecord = (value: unknown): Record<string, number> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, raw]) => [key, toFiniteNumber(raw)]),
  );
};

const normalizeTopClients = (value: unknown): DashboardTopClient[] => {
  if (!Array.isArray(value)) return [];
  return value.map((client, index) => {
    const raw = client && typeof client === 'object' ? client as Record<string, unknown> : {};
    const upload = toFiniteNumber(raw.upload);
    const download = toFiniteNumber(raw.download);
    const total = toFiniteNumber(raw.total) || upload + download;
    return {
      email: typeof raw.email === 'string' && raw.email ? raw.email : `client-${index + 1}`,
      upload,
      download,
      total,
    };
  });
};

export const normalizeDashboardSummary = (raw: any): DashboardSummaryData => ({
  nodes_total: toFiniteNumber(raw?.nodes_total),
  clients_total: toFiniteNumber(raw?.clients_total),
  online_clients_total: toFiniteNumber(raw?.online_clients_total),
  online_by_node: normalizeNumberRecord(raw?.online_by_node),
  traffic: {
    upload: toFiniteNumber(raw?.traffic?.upload),
    download: toFiniteNumber(raw?.traffic?.download),
    total: toFiniteNumber(raw?.traffic?.total),
  },
  top_clients: normalizeTopClients(raw?.top_clients),
});

export async function getDashboardSummary(): Promise<DashboardSummaryData> {
  const res = await api.get('/v1/dashboard/summary', { auth: getAuth() });
  return normalizeDashboardSummary(res.data);
}

export async function getLatestSnapshotNodes(): Promise<SnapshotNode[]> {
  const res = await api.get('/v1/snapshots/latest', { auth: getAuth() });
  return Array.isArray(res.data?.nodes) ? res.data.nodes : [];
}

export async function getDashboardHeaderMetrics(): Promise<DashboardHeaderMetrics> {
  const [nodes, snapshotNodes] = await Promise.all([listNodes(), getLatestSnapshotNodes()]);
  return {
    registeredNodes: nodes.length || snapshotNodes.length || 0,
    reachableNow: snapshotNodes.filter((node) => node.available).length,
    authIssues: snapshotNodes.filter((node) => node.reason === 'auth_failed' || node.reason === 'two_factor_required').length,
    offlineNodes: snapshotNodes.filter((node) => !node.available).length,
    xrayRunning: snapshotNodes.filter((node) => node.xray_running).length,
    onlineClients: snapshotNodes.reduce((sum, node) => sum + (node.online_clients || 0), 0),
  };
}

export async function getInboundsHeaderSource(): Promise<any[]> {
  const res = await api.get('/v1/inbounds', { auth: getAuth() });
  return Array.isArray(res.data?.inbounds) ? res.data.inbounds
    : Array.isArray(res.data) ? res.data : [];
}

export async function getClientsHeaderSource(): Promise<{ clients: any[]; nodes: NodeRecord[] }> {
  const [clientsRes, nodes] = await Promise.all([
    api.get('/v1/clients', { auth: getAuth() }),
    listNodes(),
  ]);
  const data = clientsRes.data;
  return {
    clients: Array.isArray(data?.clients) ? data.clients
      : Array.isArray(data) ? data : [],
    nodes,
  };
}

export async function getTrafficHeaderSource(): Promise<{ onlineClients: any[]; stats: Record<string, any> }> {
  const [onlineRes, trafficRes] = await Promise.all([
    api.get('/v1/clients/online', { auth: getAuth() }),
    api.get('/v1/traffic/stats', { auth: getAuth(), params: { group_by: 'client' } }),
  ]);
  return {
    onlineClients: Array.isArray(onlineRes.data?.online_clients) ? onlineRes.data.online_clients : [],
    stats: trafficRes.data?.stats || {},
  };
}

export async function getMonitoringHeaderSource(): Promise<{ deps: any; overview: any; stack: any }> {
  const [depsRes, overviewRes, stackRes] = await Promise.allSettled([
    api.get('/v1/health/deps', { auth: getAuth() }),
    api.get('/v1/adguard/overview', { auth: getAuth() }),
    api.get('/v1/monitoring/stack', { auth: getAuth() }),
  ]);
  return {
    deps: depsRes.status === 'fulfilled' ? depsRes.value.data : null,
    overview: overviewRes.status === 'fulfilled' ? overviewRes.value.data : null,
    stack: stackRes.status === 'fulfilled' ? stackRes.value.data : null,
  };
}

export async function getBackupHeaderSource(): Promise<{ nodes: NodeRecord[] }> {
  return { nodes: await listNodes() };
}

export async function getSubscriptionsHeaderSource(): Promise<{ emails: string[]; stats: Record<string, any>; nodes: NodeRecord[] }> {
  const [emailsRes, nodes] = await Promise.all([
    api.get('/v1/emails', { auth: getAuth() }),
    listNodes(),
  ]);
  return {
    emails: Array.isArray(emailsRes.data?.emails) ? emailsRes.data.emails : [],
    stats: emailsRes.data?.stats || {},
    nodes,
  };
}

function buildBaseStatuses(nodes: NodeRecord[], snapshotNodes: SnapshotNode[]): DashboardServerStatus[] {
  const snapshotByNodeId = new Map<number, SnapshotNode>();
  const snapshotByName = new Map<string, SnapshotNode>();
  snapshotNodes.forEach((snapshot) => {
    if (typeof snapshot.node_id === 'number') snapshotByNodeId.set(snapshot.node_id, snapshot);
    snapshotByName.set(snapshot.name, snapshot);
  });

  return nodes.map((node) => {
    const snapshot = snapshotByNodeId.get(node.id) || snapshotByName.get(node.name);
    return {
      nodeId: node.id,
      node: node.name,
      available: Boolean(snapshot?.available),
      loadingDetails: Boolean(snapshot?.available),
      status: snapshot?.status || (snapshot?.available ? 'online' : 'offline'),
      reason: snapshot?.reason || (snapshot?.available ? 'ok' : 'unknown'),
      error: snapshot?.error || '',
      timestamp: snapshot?.timestamp ? new Date(snapshot.timestamp * 1000).toISOString() : undefined,
      xray: snapshot ? {
        state: snapshot.xray_running ? 'running' : 'stopped',
        running: Boolean(snapshot.xray_running),
        version: '',
        uptime: 0,
      } : undefined,
    };
  });
}

export async function getDashboardServerDeck(
  options: DashboardServerDeckOptions = {},
): Promise<DashboardServerDeck> {
  const { includeLiveStatus = true, includePanelUpdateChecks = false } = options;
  const [nodes, snapshotNodes] = await Promise.all([listNodes(), getLatestSnapshotNodes()]);
  const nodeIdsByName: Record<string, number> = {};
  nodes.forEach((node) => { nodeIdsByName[node.name] = node.id; });

  const baseStatuses = buildBaseStatuses(nodes, snapshotNodes);
  const latencyByNode: Record<number, number> = {};
  const updateAvailableNodeIds: number[] = [];

  let servers = baseStatuses;
  if (includeLiveStatus) {
    const liveResults = await Promise.all(
      nodes.map(async (node) => {
        const base = baseStatuses.find((server) => server.nodeId === node.id);
        if (!base?.available) return null;
        const started = Date.now();
        try {
          const live = await getNodeServerStatus(node.id);
          latencyByNode[node.id] = Date.now() - started;
          return {
            nodeId: node.id,
            live: live as DashboardServerStatus,
          };
        } catch {
          return {
            nodeId: node.id,
            live: null,
          };
        }
      }),
    );
    const liveByNodeId = new Map(liveResults.filter(Boolean).map((item) => [item!.nodeId, item!.live]));
    servers = baseStatuses.map((server) => {
      if (!server.nodeId) return server;
      const live = liveByNodeId.get(server.nodeId);
      if (!live) return { ...server, loadingDetails: false };
      return {
        ...server,
        ...live,
        nodeId: server.nodeId,
        node: live.node || server.node,
        available: true,
        loadingDetails: false,
        status: server.status,
        reason: server.reason,
        error: server.error,
      };
    });
  }

  if (includePanelUpdateChecks) {
    await Promise.all(
      nodes.map(async (node) => {
        const base = baseStatuses.find((server) => server.nodeId === node.id);
        if (!base?.available) return;
        try {
          const updateInfo = await getNodePanelUpdateInfo(node.id);
          if (updateInfo?.isUpdatable ?? updateInfo?.has_update ?? false) {
            updateAvailableNodeIds.push(node.id);
          }
        } catch {
          // Panel update badges are enrichment only.
        }
      }),
    );
  }

  return { servers, nodeIdsByName, latencyByNode, updateAvailableNodeIds };
}
