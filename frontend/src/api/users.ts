import api from './client';
import { getAuth } from '../auth';

export type UserRole = 'viewer' | 'operator' | 'admin';
export type UserSource = 'env' | 'db';

export interface ManagedUser {
  username: string;
  role: UserRole;
  source: UserSource;
  owner: boolean;
  locked: boolean;
}

export interface UsersPayload {
  users: ManagedUser[];
  candidates: string[];
}

export async function listUsers(options: { signal?: AbortSignal } = {}): Promise<UsersPayload> {
  const response = await api.get<UsersPayload>('/v1/users', {
    auth: getAuth(),
    signal: options.signal,
    force: true,
  });
  return {
    users: Array.isArray(response.data?.users) ? response.data.users : [],
    candidates: Array.isArray(response.data?.candidates) ? response.data.candidates : [],
  };
}

export async function updateUserRole(username: string, role: UserRole): Promise<ManagedUser> {
  const response = await api.put<ManagedUser>(`/v1/users/${encodeURIComponent(username)}/role`, { role }, { auth: getAuth() });
  return response.data;
}

export async function deleteUserRole(username: string): Promise<{ username: string; removed: boolean }> {
  const response = await api.delete<{ username: string; removed: boolean }>(`/v1/users/${encodeURIComponent(username)}/role`, { auth: getAuth() });
  return response.data;
}
