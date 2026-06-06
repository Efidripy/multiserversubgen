import api from './client';
import { getAuth } from '../auth';

export type NodeLogKind = 'panel' | 'xray';

export async function restartXray(nodeId: number): Promise<any> {
  const res = await api.post(`/v1/servers/${nodeId}/restart-xray`, {}, { auth: getAuth() });
  return res.data;
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

export async function getServerHistory(nodeId: number, metric: string, bucket: string): Promise<Array<{t: number; v: number}>> {
  const res = await api.get(`/v1/nodes/${nodeId}/server-history/${metric}`, {
    params: { bucket },
    auth: getAuth(),
  });
  return res.data?.data || [];
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
