import api from './client';
import { getAuth } from '../auth';

export type ClientSourceFilter = 'all' | 'expired' | 'depleted';

export interface ClientIpDetail {
  ip: string;
  time?: number | string;
  node?: string;
}

export interface ClientIpHistoryEntry {
  node: string;
  ips: string[];
  /** Present for current 3x-ui DTOs; `ips` remains the stable legacy shape. */
  ip_details?: ClientIpDetail[];
}

export interface ClientIpHistoryResponse {
  email: string;
  results: ClientIpHistoryEntry[];
}

export interface ClientPresenceProjection {
  projection?: string;
  timestamp?: number | null;
  online_emails?: string[];
  online_by_node?: Record<string, string[]>;
  node_names?: Record<string, string>;
  last_seen?: Record<string, number | string>;
  last_seen_by_node?: Record<string, Record<string, number | string>>;
}

export interface ClientReadOptions {
  signal?: AbortSignal;
  force?: boolean;
  /**
   * Opt into the established same-origin browser session for a classified
   * browser read. The default deliberately retains the API/Basic contract
   * for callers that have not been reviewed for session-only auth.
   */
  sessionOnlyAuth?: boolean;
}

const endpointBySource: Record<ClientSourceFilter, string> = {
  all: '/v1/clients',
  expired: '/v1/clients/expired',
  depleted: '/v1/clients/depleted',
};

export async function listClientsBySource(
  source: ClientSourceFilter,
  options: ClientReadOptions = {},
): Promise<unknown> {
  const res = await api.get(endpointBySource[source], {
    ...(options.sessionOnlyAuth ? { sessionOnlyAuth: true } : { auth: getAuth() }),
    signal: options.signal,
    ...(options.force ? { force: true } : {}),
  });
  return res.data;
}

/** Snapshot-only presence read. It never starts a per-node 3x-ui scan. */
export async function getClientPresence(
  signal?: AbortSignal,
  options: Pick<ClientReadOptions, 'sessionOnlyAuth' | 'force'> = {},
): Promise<ClientPresenceProjection> {
  const res = await api.get('/v1/clients/presence', {
    ...(options.sessionOnlyAuth ? { sessionOnlyAuth: true } : { auth: getAuth() }),
    signal,
    ...(options.force ? { force: true } : {}),
  });
  return res.data || {};
}

export async function getClientIpHistory(email: string, nodeId?: number | null): Promise<ClientIpHistoryResponse> {
  const res = await api.get(`/v1/clients/${encodeURIComponent(email)}/ips`, {
    auth: getAuth(),
    params: nodeId != null ? { node_id: nodeId } : undefined,
  });
  return {
    email: String(res.data?.email ?? email),
    results: Array.isArray(res.data?.results) ? res.data.results : [],
  };
}

export async function clearClientIpHistory(email: string, nodeId?: number | null): Promise<boolean> {
  const res = await api.post(
    `/v1/clients/${encodeURIComponent(email)}/clear-ips`,
    nodeId != null ? { node_id: nodeId } : {},
    { auth: getAuth() },
  );
  return Boolean(res.data?.success);
}
