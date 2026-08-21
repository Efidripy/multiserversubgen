import api from './client';
import { getAuth } from '../auth';

export type NodeLogKind = 'panel' | 'xray';
export type ServerHistoryMetric = 'cpu' | 'mem' | 'netUp' | 'netDown' | 'online' | 'load1' | 'load5' | 'load15';
export type ServerHistoryBucket = 2 | 30 | 60 | 180 | 360 | 720 | 1440 | 2880 | 10080;

export interface X25519KeyPair {
  privateKey?: string;
  publicKey?: string;
}

export interface Mldsa65KeyPair {
  privateKey?: string;
  publicKey?: string;
  [key: string]: unknown;
}

export interface VlessEncryptionAuth {
  id?: string | number;
  label?: string;
  encryption?: string;
  decryption?: string;
  [key: string]: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function assertGeneratorPayload<T>(payload: T): T {
  if (isRecord(payload) && payload.error) {
    throw new Error(String(payload.error));
  }
  return payload;
}

export async function restartXray(nodeId: number): Promise<any> {
  const res = await api.post(`/v1/servers/${nodeId}/restart-xray`, {}, { auth: getAuth() });
  return res.data;
}

export async function generateNodeUuid(nodeId: number): Promise<string> {
  const res = await api.get(`/v1/nodes/${nodeId}/generate-uuid`, { auth: getAuth() });
  const payload = assertGeneratorPayload(res.data || {});
  const uuid = String(payload.uuid || '').trim();
  if (!uuid) {
    throw new Error('UUID generator returned an empty value');
  }
  return uuid;
}

export async function generateNodeX25519(nodeId: number): Promise<X25519KeyPair> {
  const res = await api.get(`/v1/nodes/${nodeId}/generate-x25519`, { auth: getAuth() });
  const payload = assertGeneratorPayload<X25519KeyPair & { error?: unknown }>(res.data || {});
  if (!payload.privateKey && !payload.publicKey) {
    throw new Error('X25519 generator returned an empty keypair');
  }
  return payload;
}

export async function generateNodeMldsa65(nodeId: number): Promise<Mldsa65KeyPair> {
  const res = await api.get(`/v1/nodes/${nodeId}/generate-mldsa65`, { auth: getAuth() });
  const payload = assertGeneratorPayload<Mldsa65KeyPair & { error?: unknown }>(res.data || {});
  if (!payload.privateKey && !payload.publicKey) {
    throw new Error('ML-DSA-65 generator returned an empty keypair');
  }
  return payload;
}

export async function generateNodeVlessEncryption(nodeId: number): Promise<VlessEncryptionAuth[]> {
  const res = await api.get(`/v1/nodes/${nodeId}/generate-vless-enc`, { auth: getAuth() });
  const payload = assertGeneratorPayload<unknown>(res.data || {});
  const rawAuths = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.auths)
      ? payload.auths
      : isRecord(payload) && Array.isArray(payload.obj)
        ? payload.obj
        : isRecord(payload)
          ? [payload]
          : [];
  const auths = rawAuths
    .map((item): VlessEncryptionAuth | null => {
      if (!isRecord(item)) {
        const value = String(item || '').trim();
        return value ? { label: value, encryption: value, decryption: value } : null;
      }
      return {
        ...item,
        id: item.id as string | number | undefined,
        label: String(item.label || item.id || '').trim(),
        encryption: String(item.encryption || '').trim(),
        decryption: String(item.decryption || '').trim(),
      };
    })
    .filter((item): item is VlessEncryptionAuth => item !== null);
  if (!auths.length) {
    throw new Error('VLESS encryption generator returned an empty payload');
  }
  return auths;
}

export async function getNodeLogs(
  nodeId: number,
  kind: NodeLogKind,
  options: { count?: number; level?: string } = {},
): Promise<string[]> {
  const endpoint = kind === 'xray'
    ? `/v1/nodes/${nodeId}/xray-logs`
    : `/v1/nodes/${nodeId}/server-logs`;
  const res = await api.get(endpoint, {
    params: { count: options.count ?? 200, level: options.level },
    auth: getAuth(),
  });
  const payload = res.data || {};
  if (payload.error) throw new Error(String(payload.error));
  return Array.isArray(payload.logs) ? payload.logs : [];
}

export async function getXrayVersions(nodeId: number): Promise<string[]> {
  const res = await api.get(`/v1/nodes/${nodeId}/xray-versions`, { auth: getAuth() });
  return res.data?.versions || [];
}

export async function installXray(nodeId: number, version: string): Promise<any> {
  const res = await api.post(`/v1/nodes/${nodeId}/install-xray/${version}`, {}, { auth: getAuth() });
  return res.data;
}

export async function stopXray(nodeId: number): Promise<any> {
  const res = await api.post(`/v1/nodes/${nodeId}/stop-xray`, {}, { auth: getAuth() });
  return res.data;
}

export async function updatePanel(nodeId: number): Promise<any> {
  const res = await api.post(`/v1/nodes/${nodeId}/update-panel`, {}, { auth: getAuth() });
  return res.data;
}

export async function updateGeofile(nodeId: number): Promise<any> {
  const res = await api.post(`/v1/nodes/${nodeId}/update-geofile`, {}, { auth: getAuth() });
  return res.data;
}

export async function getOutboundsTraffic(nodeId: number): Promise<any[]> {
  const res = await api.get(`/v1/nodes/${nodeId}/outbounds-traffic`, { auth: getAuth() });
  return res.data?.outbounds || [];
}

export async function getNodeTraffic(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/traffic`, { auth: getAuth() });
  return res.data;
}

export async function getNodeOnlineClients(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/online-clients`, { auth: getAuth() });
  return res.data;
}

export async function getXrayMetrics(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/xray-metrics`, { auth: getAuth() });
  return res.data;
}

export async function getXrayObservatory(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/xray-observatory`, { auth: getAuth() });
  return res.data;
}

export async function getXrayConfig(nodeId: number): Promise<any> {
  const res = await api.get(`/v1/nodes/${nodeId}/xray-config`, { auth: getAuth() });
  return res.data;
}

export async function getServerHistory(
  nodeId: number,
  metric: ServerHistoryMetric,
  bucket: ServerHistoryBucket = 360,
): Promise<Array<{t: number; v: number}>> {
  const res = await api.get(`/v1/nodes/${nodeId}/server-history/${metric}`, {
    params: { bucket },
    auth: getAuth(),
  });
  return res.data?.data || [];
}

export async function resetAllNodeTraffics(nodeId: number): Promise<any> {
  const res = await api.post(`/v1/inbounds/${nodeId}/reset-all-traffics`, {}, { auth: getAuth() });
  return res.data;
}

export async function getApiTokens(nodeId: number): Promise<any[]> {
  const res = await api.get(`/v1/nodes/${nodeId}/api-tokens`, { auth: getAuth() });
  return res.data?.tokens || res.data || [];
}

export async function createApiToken(nodeId: number, name: string): Promise<any> {
  const res = await api.post(`/v1/nodes/${nodeId}/api-tokens`, { name }, { auth: getAuth() });
  return res.data;
}

export async function deleteApiToken(nodeId: number, tokenId: number): Promise<any> {
  const res = await api.delete(`/v1/nodes/${nodeId}/api-tokens/${tokenId}`, { auth: getAuth() });
  return res.data;
}

export async function setApiTokenEnabled(nodeId: number, tokenId: number, enabled: boolean): Promise<any> {
  const res = await api.post(`/v1/nodes/${nodeId}/api-tokens/${tokenId}/set-enabled`, { enabled }, { auth: getAuth() });
  return res.data;
}
