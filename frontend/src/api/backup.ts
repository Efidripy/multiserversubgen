import api from './client';
import { getAuth } from '../auth';

export async function downloadAllBackups(): Promise<Blob> {
  const res = await api.get('/v1/backup/all', { auth: getAuth(), responseType: 'blob' });
  return res.data;
}

export async function downloadNodeBackup(nodeId: number): Promise<Blob> {
  const res = await api.get(`/v1/backup/node/${nodeId}`, { auth: getAuth(), responseType: 'blob' });
  return res.data;
}

export async function importNodeBackup(nodeId: number, payload: unknown): Promise<any> {
  const res = await api.post(`/v1/backup/node/${nodeId}/import`, payload, { auth: getAuth() });
  return res.data;
}

export async function sendNodeBackupToTelegram(nodeId: number): Promise<any> {
  const res = await api.post(`/v1/nodes/${nodeId}/backup-telegram`, {}, { auth: getAuth() });
  return res.data;
}
