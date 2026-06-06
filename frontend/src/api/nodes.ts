import api from './client';
import { getAuth } from '../auth';

export interface NodeRecord {
  id: number;
  name: string;
  ip?: string;
  port?: string;
  url?: string;
  scheme?: string;
  base_path?: string;
  read_only?: boolean;
  api_version?: string;
  panel_version?: string;
  user?: string;
  password?: string;
  bearer_token?: string;
}

export interface FleetNode extends NodeRecord {
  available: boolean | null;
  latency?: number;
  error?: string;
}

export interface NodeDashboardOverview {
  nodes: NodeRecord[];
  statuses: Record<number, boolean | null>;
  clientCounts: Record<number, number>;
  inboundCounts: Record<number, number>;
}

export interface NodeDashboardOverviewOptions {
  includeCounts?: boolean;
}

const toOptionalString = (value: unknown): string | undefined => {
  if (typeof value === 'string' && value.length > 0) return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return undefined;
};

const toFiniteId = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const extractNodeArray = (payload: unknown): unknown[] => {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    if (Array.isArray(record.nodes)) return record.nodes;
    if (Array.isArray(record.data)) return record.data;
  }
  return [];
};

const normalizeNodeRecord = (raw: unknown): NodeRecord | null => {
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, unknown>;
  const id = toFiniteId(record.id);
  if (id === null) return null;

  return {
    id,
    name: toOptionalString(record.name) || `node-${id}`,
    ip: toOptionalString(record.ip),
    port: toOptionalString(record.port),
    url: toOptionalString(record.url),
    scheme: toOptionalString(record.scheme),
    base_path: toOptionalString(record.base_path),
    read_only: record.read_only == null ? undefined : Boolean(record.read_only),
    api_version: toOptionalString(record.api_version),
    panel_version: toOptionalString(record.panel_version),
    user: toOptionalString(record.user),
    password: toOptionalString(record.password),
    bearer_token: toOptionalString(record.bearer_token),
  };
};

export async function listNodes(): Promise<NodeRecord[]> {
  const res = await api.get('/v1/nodes', { auth: getAuth() });
  return extractNodeArray(res.data)
    .map(normalizeNodeRecord)
    .filter((node): node is NodeRecord => node !== null);
}

export async function getNodeServerStatus(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/server-status`, { auth: getAuth() });
  return res.data || {};
}

export async function getServerLiveStatus(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/servers/${nodeId}/status`, { auth: getAuth() });
  return res.data || {};
}

export async function getNodePanelUpdateInfo(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/panel-update-info`, { auth: getAuth() });
  return res.data || {};
}

export async function getClientsForNode(nodeId: number): Promise<any[]> {
  const res = await api.get('/v1/clients', { auth: getAuth(), params: { node_id: nodeId } });
  const payload = res.data?.clients ?? res.data;
  return Array.isArray(payload) ? payload : [];
}

export async function getNodeInbounds(nodeId: number): Promise<any[]> {
  const res = await api.get(`/v1/nodes/${nodeId}/inbounds`, { auth: getAuth() });
  const payload = res.data?.inbounds ?? res.data;
  return Array.isArray(payload) ? payload : [];
}

export async function getClientCountForNode(nodeId: number): Promise<number> {
  const res = await api.get('/v1/clients/count', { auth: getAuth(), params: { node_id: nodeId } });
  return Number(res.data?.count ?? 0);
}

export async function refreshNodesNow(): Promise<any> {
  const res = await api.post('/v1/nodes/refresh-now', {}, { auth: getAuth() });
  return res.data;
}

export async function getRegisteredFleetOverview(): Promise<FleetNode[]> {
  const nodes = await listNodes();
  const checks = await Promise.all(
    nodes.map(async (node) => {
      const started = performance.now();
      try {
        const status = await getNodeServerStatus(node.id);
        return {
          id: node.id,
          available: Boolean(status?.available),
          latency: Math.max(1, Math.round(performance.now() - started)),
          error: status?.error || status?.reason,
        };
      } catch (error: any) {
        return {
          id: node.id,
          available: false,
          latency: undefined,
          error: error?.response?.data?.detail || error?.message || 'Connection failed',
        };
      }
    }),
  );

  const byId = new Map(checks.map((item) => [item.id, item]));
  return nodes.map((node) => {
    const check = byId.get(node.id);
    return {
      ...node,
      available: check?.available ?? null,
      latency: check?.latency,
      error: check?.error,
    };
  });
}

export async function getNodeDashboardOverview(
  options: NodeDashboardOverviewOptions = {},
): Promise<NodeDashboardOverview> {
  const { includeCounts = true } = options;
  const nodes = await listNodes();
  const statuses: Record<number, boolean | null> = {};

  await Promise.all(
    nodes.map(async (node) => {
      try {
        const status = await getNodeServerStatus(node.id);
        statuses[node.id] = Boolean(status?.available);
      } catch {
        statuses[node.id] = false;
      }
    }),
  );

  const clientCounts: Record<number, number> = {};
  const inboundCounts: Record<number, number> = {};

  if (includeCounts) {
    await Promise.all(
      nodes.map(async (node) => {
        try {
          const [clients, inbounds] = await Promise.all([
            getClientsForNode(node.id),
            getNodeInbounds(node.id),
          ]);
          if (clients.length > 0) clientCounts[node.id] = clients.length;
          if (inbounds.length > 0) inboundCounts[node.id] = inbounds.length;
        } catch {
          // Counts are enrichment only.
        }
      }),
    );
  }

  return { nodes, statuses, clientCounts, inboundCounts };
}

export async function createNode(payload: unknown): Promise<any> {
  const res = await api.post('/v1/nodes', payload, { auth: getAuth() });
  return res.data;
}

export async function updateNode(nodeId: number, payload: unknown): Promise<any> {
  const res = await api.put(`/v1/nodes/${nodeId}`, payload, { auth: getAuth() });
  return res.data;
}

export async function deleteNode(nodeId: number): Promise<any> {
  const res = await api.delete(`/v1/nodes/${nodeId}`, { auth: getAuth() });
  return res.data;
}

export async function checkNodeConnection(payload: unknown): Promise<any> {
  const res = await api.post('/v1/nodes/check-connection', payload, { auth: getAuth() });
  return res.data;
}
