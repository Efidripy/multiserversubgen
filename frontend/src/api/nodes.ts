import api from './client';
import { getAuth } from '../auth';
import type { NodeFlag, NodeRecord, NodeSourceType } from './types';

export type { NodeFlag, NodeRecord, NodeSourceType } from './types';

export interface FleetNode extends NodeRecord {
  available: boolean | null;
  latency?: number;
  error?: string;
}

export type TelegramNodePolicy = {
  node_id: number;
  provisioning_enabled: boolean;
  total_bytes: number;
  validity_days: number;
  client_enabled: boolean;
  policy_version: number;
  updated_by: string;
};

interface FleetProbeResult {
  id: number;
  available: boolean;
  latency?: number;
  error?: string;
}

export type NodesChangedAction = 'create' | 'update' | 'delete';

export interface NodesChangedDetail {
  action: NodesChangedAction;
  nodeId?: number;
}

export const NODES_CHANGED_EVENT = 'sub-manager:nodes-changed';
const FLEET_PROBE_CONCURRENCY = 8;
export const NODE_BATCH_CREATE_CONCURRENCY = 4;

export const dispatchNodesChanged = (detail: NodesChangedDetail) => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<NodesChangedDetail>(NODES_CHANGED_EVENT, { detail }));
};

interface NodeMutationOptions {
  emitChange?: boolean;
}

const toOptionalString = (value: unknown): string | undefined => {
  if (typeof value === 'string' && value.length > 0) return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return undefined;
};

const toNodeFlag = (value: unknown, fallback: NodeFlag): NodeFlag => {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true') return true;
    if (normalized === 'false') return false;
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
};

const toFiniteId = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const toStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return [];
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item).trim()).filter(Boolean);
      }
    } catch {
      // Plain comma-separated strings are accepted for backward compatibility.
    }
    return trimmed.split(',').map((item) => item.trim()).filter(Boolean);
  }
  return [];
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
  const panelUrl = toOptionalString(record.panel_url) || toOptionalString(record.url) || '';

  return {
    id,
    name: toOptionalString(record.name) || `node-${id}`,
    panel_url: panelUrl,
    source_type: (toOptionalString(record.source_type) || 'xui') as NodeSourceType,
    verify_tls: toNodeFlag(record.verify_tls, true),
    enabled: toNodeFlag(record.enabled, true),
    ip: toOptionalString(record.ip),
    port: toOptionalString(record.port),
    url: panelUrl || toOptionalString(record.url),
    scheme: toOptionalString(record.scheme),
    base_path: toOptionalString(record.base_path),
    read_only: toNodeFlag(record.read_only, false),
    api_version: toOptionalString(record.api_version) || '',
    panel_version: toOptionalString(record.panel_version),
    user: toOptionalString(record.user),
    password: toOptionalString(record.password),
    bearer_token: toOptionalString(record.bearer_token),
    tags: toStringArray(record.tags),
  };
};

export async function listNodes(options: { signal?: AbortSignal } = {}): Promise<NodeRecord[]> {
  const res = await api.get('/v1/nodes', { auth: getAuth(), signal: options.signal });
  return extractNodeArray(res.data)
    .map(normalizeNodeRecord)
    .filter((node): node is NodeRecord => node !== null);
}

export async function getNodeServerStatus(nodeId: number, options: { signal?: AbortSignal } = {}): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/server-status`, { auth: getAuth(), signal: options.signal });
  return res.data || {};
}

export async function refreshNodesNow(): Promise<any> {
  const res = await api.post('/v1/nodes/refresh-now', {}, { auth: getAuth() });
  return res.data;
}

export async function getRegisteredFleetOverview(options: { signal?: AbortSignal } = {}): Promise<FleetNode[]> {
  const nodes = await listNodes({ signal: options.signal });
  const checks: Array<FleetProbeResult | undefined> = new Array(nodes.length);
  let nextIndex = 0;
  const probe = async () => {
    while (nextIndex < nodes.length) {
      if (options.signal?.aborted) return;
      const index = nextIndex++;
      const node = nodes[index];
      const started = performance.now();
      try {
        const status = await getNodeServerStatus(node.id, { signal: options.signal });
        checks[index] = {
          id: node.id,
          available: Boolean(status?.available),
          latency: Math.max(1, Math.round(performance.now() - started)),
          error: status?.error || status?.reason,
        };
      } catch (error: any) {
        if (options.signal?.aborted) return;
        checks[index] = {
          id: node.id,
          available: false,
          latency: undefined,
          error: error?.response?.data?.detail || error?.message || 'Connection failed',
        };
      }
    }
  };
  const concurrency = Math.min(FLEET_PROBE_CONCURRENCY, Math.max(1, nodes.length));
  await Promise.all(Array.from({ length: concurrency }, () => probe()));

  const byId = new Map(checks.filter((item): item is FleetProbeResult => Boolean(item)).map((item) => [item.id, item]));
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

export async function createNode(payload: unknown, options: NodeMutationOptions = {}): Promise<any> {
  const res = await api.post('/v1/nodes', payload, { auth: getAuth() });
  if (options.emitChange !== false) {
    dispatchNodesChanged({
      action: 'create',
      nodeId: toFiniteId(res.data?.id ?? res.data?.node?.id) ?? undefined,
    });
  }
  return res.data;
}

/**
 * Apply backpressure to the SQLite-backed node-creation route while retaining
 * the same ordered Promise.allSettled-style result for batch UI accounting.
 */
export async function createNodesBounded(
  payloads: unknown[],
  options: NodeMutationOptions = {},
): Promise<PromiseSettledResult<any>[]> {
  const results: PromiseSettledResult<any>[] = new Array(payloads.length);
  let nextIndex = 0;

  const worker = async () => {
    while (nextIndex < payloads.length) {
      const index = nextIndex++;
      try {
        results[index] = { status: 'fulfilled', value: await createNode(payloads[index], options) };
      } catch (reason) {
        results[index] = { status: 'rejected', reason };
      }
    }
  };

  const concurrency = Math.min(NODE_BATCH_CREATE_CONCURRENCY, payloads.length);
  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  return results;
}

export async function updateNode(nodeId: number, payload: unknown): Promise<any> {
  const res = await api.put(`/v1/nodes/${nodeId}`, payload, { auth: getAuth() });
  dispatchNodesChanged({ action: 'update', nodeId });
  return res.data;
}

export async function listTelegramNodePolicies(): Promise<TelegramNodePolicy[]> {
  const res = await api.get<{ items?: TelegramNodePolicy[] }>('/v1/telegram/node-policies', { auth: getAuth() });
  return Array.isArray(res.data?.items) ? res.data.items : [];
}

export async function updateTelegramNodePolicy(
  nodeId: number,
  payload: {
    provisioning_enabled: boolean;
    total_bytes: number;
    validity_days: number;
    client_enabled: boolean;
    expected_policy_version: number;
    idempotency_key: string;
  },
): Promise<TelegramNodePolicy> {
  const res = await api.put(`/v1/telegram/node-policies/${nodeId}`, payload, { auth: getAuth() });
  return res.data.policy as TelegramNodePolicy;
}

export async function deleteNode(nodeId: number): Promise<any> {
  const res = await api.delete(`/v1/nodes/${nodeId}`, { auth: getAuth() });
  dispatchNodesChanged({ action: 'delete', nodeId });
  return res.data;
}

export async function checkNodeConnection(payload: unknown): Promise<any> {
  const res = await api.post('/v1/nodes/check-connection', payload, {
    auth: getAuth(),
    skipCacheInvalidation: true,
  });
  return res.data;
}
