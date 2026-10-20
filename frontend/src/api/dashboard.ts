import api from './client';
import { getAuth } from '../auth';

export interface DashboardTopClient {
  email: string;
  upload: number;
  download: number;
  total: number;
}

export type DashboardTrafficPeriod = 'day' | 'week' | 'month' | 'all_time';

export interface DashboardSummaryData {
  nodes_total: number;
  nodes_online: number;
  clients_total: number;
  online_clients_total: number;
  online_by_node: Record<string, number>;
  online_by_node_id: Record<string, number>;
  traffic: { upload: number; download: number; total: number };
  traffic_period: DashboardTrafficPeriod;
  traffic_note: string | null;
  top_clients: DashboardTopClient[];
}

/** Sanitized node telemetry returned by the single Dashboard aggregate route. */
export interface DashboardFleetNode {
  id: number;
  name: string;
  panel_url: string;
  ip: string;
  port: string;
  scheme: string;
  base_path: string;
  source_type: string;
  read_only: boolean;
  enabled: boolean;
  available: boolean | null;
  status?: string;
  reason?: string;
  error?: string;
  system?: any;
  xray?: any;
  network?: any;
  xray_running?: boolean;
  online_clients: number | null;
  traffic_total: number | null;
  inbounds_available: boolean | null;
  timestamp?: number;
  poll_ms?: number;
  tcp_rtt_ms?: number;
  panel_version?: string;
  api_version?: string;
  xray_compatibility?: XrayCompatibilitySummary;
}

export interface DashboardOverviewData {
  summary: DashboardSummaryData;
  fleet: DashboardFleetNode[];
  projection: 'dashboard-v1';
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
  panel_version?: string;
  api_version?: string;
  xray_compatibility?: XrayCompatibilitySummary;
  tcp_rtt_ms?: number;
}

export interface XrayCompatibilitySummary {
  status: 'ok' | 'warning' | 'unknown';
  checked_inbounds: number;
  findings: Array<{ code: string; severity: 'warning' | 'error' | 'critical'; count: number }>;
}

export interface DashboardServerDeck {
  servers: DashboardServerStatus[];
  nodeIdsByName: Record<string, number>;
  latencyByNode: Record<number, number>;
  updateAvailableNodeIds: number[];
}

const toFiniteNumber = (value: unknown): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const toOptionalFiniteNumber = (value: unknown): number | undefined => {
  if (value === undefined || value === null || value === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const toNullableFiniteNumber = (value: unknown): number | null => {
  if (value === undefined || value === null || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
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
  nodes_online: toFiniteNumber(raw?.nodes_online),
  clients_total: toFiniteNumber(raw?.clients_total),
  online_clients_total: toFiniteNumber(raw?.online_clients_total),
  online_by_node: normalizeNumberRecord(raw?.online_by_node),
  online_by_node_id: normalizeNumberRecord(raw?.online_by_node_id),
  traffic: {
    upload: toFiniteNumber(raw?.traffic?.upload),
    download: toFiniteNumber(raw?.traffic?.download),
    total: toFiniteNumber(raw?.traffic?.total),
  },
  traffic_period: raw?.traffic_period === 'day' || raw?.traffic_period === 'week' || raw?.traffic_period === 'month'
    ? raw.traffic_period
    : 'all_time',
  traffic_note: typeof raw?.traffic_note === 'string' && raw.traffic_note ? raw.traffic_note : null,
  top_clients: normalizeTopClients(raw?.top_clients),
});

export const normalizeDashboardFleet = (raw: unknown): DashboardFleetNode[] => {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item, index) => {
    const value = item && typeof item === 'object' ? item as Record<string, unknown> : null;
    const id = toFiniteNumber(value?.id);
    if (!value || id <= 0) return [];
    return [{
      id,
      name: typeof value.name === 'string' && value.name ? value.name : `node-${index + 1}`,
      panel_url: typeof value.panel_url === 'string' ? value.panel_url : '',
      ip: typeof value.ip === 'string' ? value.ip : '',
      port: typeof value.port === 'string' ? value.port : '',
      scheme: typeof value.scheme === 'string' ? value.scheme : 'https',
      base_path: typeof value.base_path === 'string' ? value.base_path : '',
      source_type: typeof value.source_type === 'string' ? value.source_type : 'xui',
      read_only: Boolean(value.read_only),
      enabled: value.enabled !== false,
      available: typeof value.available === 'boolean' ? value.available : null,
      status: typeof value.status === 'string' ? value.status : undefined,
      reason: typeof value.reason === 'string' ? value.reason : undefined,
      error: typeof value.error === 'string' ? value.error : undefined,
      system: value.system,
      xray: value.xray,
      network: value.network,
      xray_running: Boolean(value.xray_running),
      online_clients: toNullableFiniteNumber(value.online_clients),
      traffic_total: toNullableFiniteNumber(value.traffic_total),
      inbounds_available: typeof value.inbounds_available === 'boolean'
        ? value.inbounds_available
        : null,
      timestamp: toFiniteNumber(value.timestamp),
      poll_ms: toFiniteNumber(value.poll_ms),
      tcp_rtt_ms: toOptionalFiniteNumber(value.tcp_rtt_ms),
      panel_version: typeof value.panel_version === 'string' ? value.panel_version : '',
      api_version: typeof value.api_version === 'string' ? value.api_version : '',
      xray_compatibility: value.xray_compatibility as XrayCompatibilitySummary | undefined,
    }];
  });
};

export async function getDashboardOverview(
  period: DashboardTrafficPeriod = 'all_time',
  options: { signal?: AbortSignal } = {},
): Promise<DashboardOverviewData> {
  // A successful browser login issues an HttpOnly same-origin session cookie. Do
  // not explicitly pass the memory-only Basic credentials through the minute
  // polling path: an empty password still serializes as a Basic request in Axios
  // and needlessly re-enters the server's Basic/PAM authentication path.
  const res = await api.get('/v1/dashboard/overview', {
    params: { period },
    signal: options.signal,
    sessionOnlyAuth: true,
  });
  return {
    summary: normalizeDashboardSummary(res.data?.summary),
    fleet: normalizeDashboardFleet(res.data?.fleet),
    projection: 'dashboard-v1',
  };
}

export function dashboardFleetToServerDeck(fleet: DashboardFleetNode[]): DashboardServerDeck {
  const nodeIdsByName: Record<string, number> = {};
  const latencyByNode: Record<number, number> = {};
  const servers = fleet.map((node) => {
    nodeIdsByName[node.name] = node.id;
    if (node.poll_ms && node.poll_ms > 0) latencyByNode[node.id] = node.poll_ms;
    return {
      nodeId: node.id,
      node: node.name,
      available: node.available === true,
      status: node.status,
      reason: node.reason,
      error: node.error,
      timestamp: node.timestamp ? String(node.timestamp) : undefined,
      system: node.system,
      xray: node.xray,
      network: node.network,
      panel_version: node.panel_version,
      api_version: node.api_version,
      xray_compatibility: node.xray_compatibility,
      tcp_rtt_ms: node.tcp_rtt_ms,
    };
  });
  return { servers, nodeIdsByName, latencyByNode, updateAvailableNodeIds: [] };
}

export async function getInboundsHeaderSource(options: { signal?: AbortSignal } = {}): Promise<any[]> {
  const res = await api.get('/v1/inbounds', { sessionOnlyAuth: true, signal: options.signal });
  return Array.isArray(res.data?.inbounds) ? res.data.inbounds
    : Array.isArray(res.data) ? res.data : [];
}

export async function getMonitoringHeaderSource(options: { signal?: AbortSignal } = {}): Promise<{ deps: any; overview: any; stack: any }> {
  const [depsRes, overviewRes, stackRes] = await Promise.allSettled([
    api.get('/v1/health/deps', { auth: getAuth(), signal: options.signal }),
    api.get('/v1/adguard/overview', { auth: getAuth(), signal: options.signal }),
    api.get('/v1/monitoring/stack', { auth: getAuth(), signal: options.signal }),
  ]);
  return {
    deps: depsRes.status === 'fulfilled' ? depsRes.value.data : null,
    overview: overviewRes.status === 'fulfilled' ? overviewRes.value.data : null,
    stack: stackRes.status === 'fulfilled' ? stackRes.value.data : null,
  };
}
