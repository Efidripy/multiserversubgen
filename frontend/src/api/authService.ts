import api from './client';
import { getAuth } from '../auth';

export interface FeatureFlagsResponse {
  monitoringEnabled?: boolean;
}

export interface MfaStatusResponse {
  enabled: boolean;
}

export interface VerifyAuthResponse {
  user?: string;
  ws_ticket?: string;
  role?: 'viewer' | 'operator' | 'admin' | string;
}

export async function getFeatureFlags(): Promise<FeatureFlagsResponse> {
  const res = await api.get('/v1/features', { auth: getAuth() });
  return (res.data || {}) as FeatureFlagsResponse;
}

export async function getMfaStatus(): Promise<MfaStatusResponse> {
  const res = await api.get('/v1/auth/mfa-status');
  return { enabled: Boolean(res.data?.enabled) };
}

export async function verifyCurrentAuth(): Promise<VerifyAuthResponse> {
  const auth = getAuth();
  const headers: Record<string, string> = {};
  if (auth.totpCode) headers['X-TOTP-Code'] = auth.totpCode;

  const res = await api.get('/v1/auth/verify', {
    auth: { username: auth.username, password: auth.password },
    headers,
  });
  return (res.data || {}) as VerifyAuthResponse;
}

export async function verifyLoginCredentials(
  username: string,
  password: string,
  totpCode = '',
): Promise<VerifyAuthResponse> {
  const headers: Record<string, string> = {};
  if (totpCode.trim()) headers['X-TOTP-Code'] = totpCode.trim();

  const res = await api.get('/v1/auth/verify', {
    auth: { username, password },
    headers,
  });
  return (res.data || {}) as VerifyAuthResponse;
}
