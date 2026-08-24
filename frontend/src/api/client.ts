import axios, { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { activityLog } from '../services/activityLog';
import { cacheService } from '../services/cacheService';
import { getAuth } from '../auth';
import { requestActivityStore } from '../services/requestActivity';

declare module 'axios' {
  interface AxiosRequestConfig<D = any> {
    /** Explicit opt-out for a POST that is a read projection, not a mutation. */
    skipCacheInvalidation?: boolean;
  }
}

export const AUTH_REQUIRED_EVENT = 'sub-manager:auth-required';
let authRequiredEventSent = false;

export const resetAuthRequiredEventGuard = () => {
  authRequiredEventSent = false;
};

const inFlightGetRequests = new Map<string, Promise<AxiosResponse>>();
let cacheGeneration = 0;

export const resetInFlightGetRequests = () => {
  inFlightGetRequests.clear();
};

export const resetCacheGeneration = () => {
  cacheGeneration = 0;
};

type CacheAwareRequestConfig = InternalAxiosRequestConfig & {
  __cacheGeneration?: number;
};

const dispatchAuthRequired = (url: string, method: string) => {
  if (authRequiredEventSent || typeof window === 'undefined') return;
  authRequiredEventSent = true;
  window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT, {
    detail: { url, method },
  }));
};

/**
 * API base URL used by all frontend requests.
 *
 * Resolution order (first defined wins):
 *   1. VITE_API_BASE_URL env var  – explicit override, useful for CDN / split deployments
 *   2. Derived from BASE_URL       – BASE_URL is set to Vite `base` at build time
 *                                    (e.g. "/mssg/"), so the API lives at "/mssg/api"
 *
 * Examples:
 *   VITE_BASE=/          → API_BASE = "/api"
 *   VITE_BASE=/mssg/     → API_BASE = "/mssg/api"
 *   VITE_API_BASE_URL=https://api.example.com → API_BASE = "https://api.example.com"
 */
const normalizeApiBase = (baseUrl: string): string => {
  const trimmed = baseUrl.replace(/\/$/, '');
  return `${trimmed}/api`;
};

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ??
  normalizeApiBase(import.meta.env.BASE_URL);

/**
 * Per-route cache TTLs in milliseconds.
 * Used by the request interceptor to determine how long to cache each GET response.
 */
export const CACHE_TTL = {
  DASHBOARD: 30_000,
  NODES: 30_000,
  CLIENTS: 10_000,
  TRAFFIC: 8_000,
  INBOUNDS: 20_000,
  EMAILS: 20_000,
  DEFAULT: 5_000,
} as const;

/** Map URL path fragments to their cache TTL. */
const ROUTE_TTLS: Array<[string, number]> = [
  ['/v1/dashboard', CACHE_TTL.DASHBOARD],
  ['/v1/nodes', CACHE_TTL.NODES],
  ['/v1/clients', CACHE_TTL.CLIENTS],
  ['/v1/traffic', CACHE_TTL.TRAFFIC],
  ['/v1/inbounds', CACHE_TTL.INBOUNDS],
  ['/v1/emails', CACHE_TTL.EMAILS],
];

function getTTLForUrl(url: string): number {
  if (url.includes('/generate-')) return 0;
  for (const [pattern, ttl] of ROUTE_TTLS) {
    if (url.includes(pattern)) return ttl;
  }
  return CACHE_TTL.DEFAULT;
}

function stableStringify(value: unknown): string {
  if (value == null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(',')}]`;
  }
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(obj[key])}`).join(',')}}`;
}

function buildCacheKey(url: string, params: unknown, identity: string): string {
  const prefix = `GET:${identity || 'anonymous'}:${url}`;
  if (params == null) return prefix;
  return `${prefix}:${stableStringify(params)}`;
}

function deriveResourceTag(url: string): string {
  const match = url.match(/^(\/v\d+\/[^/?]+)/);
  return match?.[1] ?? url;
}

function deriveCacheTags(url: string): string[] {
  const tags = new Set<string>();
  const resource = deriveResourceTag(url);
  tags.add(`resource:${resource}`);

  if (resource.startsWith('/v1/nodes')) tags.add('domain:nodes');
  if (resource.startsWith('/v1/dashboard')) tags.add('domain:dashboard');
  if (resource.startsWith('/v1/clients')) tags.add('domain:clients');
  if (resource.startsWith('/v1/inbounds')) tags.add('domain:inbounds');
  if (resource.startsWith('/v1/traffic')) tags.add('domain:traffic');
  if (resource.startsWith('/v1/emails')) tags.add('domain:emails');

  const nodeMatch = url.match(/\/v1\/nodes\/(\d+)/);
  if (nodeMatch) tags.add(`node:${nodeMatch[1]}`);

  return Array.from(tags);
}

function invalidateForMutation(url: string): void {
  const resource = deriveResourceTag(url);
  cacheService.invalidateByTag(`resource:${resource}`);

  if (resource.startsWith('/v1/nodes')) {
    cacheService.invalidateByTag('domain:nodes');
    cacheService.invalidateByTag('domain:clients');
    cacheService.invalidateByTag('domain:inbounds');
    cacheService.invalidateByTag('domain:emails');
    cacheService.invalidateByTag('domain:traffic');
    cacheService.invalidateByTag('domain:dashboard');
  }

  if (resource.startsWith('/v1/clients')) {
    cacheService.invalidateByTag('domain:clients');
    cacheService.invalidateByTag('domain:traffic');
    cacheService.invalidateByTag('domain:dashboard');
    cacheService.invalidateByTag('domain:emails');
  }

  if (resource.startsWith('/v1/inbounds')) {
    cacheService.invalidateByTag('domain:inbounds');
    cacheService.invalidateByTag('domain:emails');
    cacheService.invalidateByTag('domain:traffic');
    cacheService.invalidateByTag('domain:dashboard');
  }

  if (resource.startsWith('/v1/traffic')) {
    cacheService.invalidateByTag('domain:traffic');
  }

  // Backward compatible safety net for older keys.
  cacheService.invalidate(resource);
}

/** Pre-configured axios instance – use this instead of raw axios for all API calls. */
function isCanceledApiError(error: any): boolean {
  return axios.isCancel(error)
    || error?.code === 'ERR_CANCELED'
    || error?.name === 'CanceledError'
    || error?.message === 'canceled';
}

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

/**
 * Request interceptor — for GET requests, check the in-memory cache first.
 * If a fresh entry exists, override the adapter to return the cached response
 * immediately without making a network round-trip.
 */
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  requestActivityStore.increment();
  const _method = config.method?.toUpperCase() ?? 'GET';
  const _url = config.url ?? '';
  // Skip auth/verify noise at debug level
  if (!_url.includes('/auth/verify') && !_url.includes('/auth/mfa')) {
    activityLog.debug('API', `→ ${_method} ${_url}`);
  }
  const auth = getAuth();
  if (auth.totpCode) {
    config.headers = config.headers ?? {};
    config.headers['X-TOTP-Code'] = auth.totpCode;
  }
  if (!config.auth && auth.username && auth.password) {
    config.auth = { username: auth.username, password: auth.password };
  }

  if (config.method?.toLowerCase() === 'get') {
    const url = config.url ?? '';
    const ttl = getTTLForUrl(url);
    if (ttl > 0) {
      const cacheConfig = config as CacheAwareRequestConfig;
      const requestGeneration = cacheGeneration;
      cacheConfig.__cacheGeneration = requestGeneration;
      const key = buildCacheKey(url, config.params, auth.username);
      const cached = cacheService.get(key);
      if (cached !== undefined) {
        // Short-circuit the HTTP request by returning the cached response via a
        // custom adapter.  This keeps callers' .then()/.catch() chains intact.
        config.adapter = () => Promise.resolve(cached as any);
      } else if (!config.signal) {
        // Cache is populated only after the first response.  Coalesce equal
        // cold requests so a header and a lazily mounted page cannot create a
        // duplicate full-fleet API fetch before that cache entry exists.
        const sourceAdapter = config.adapter;
        config.adapter = async (requestConfig) => {
          const inFlightKey = `${requestGeneration}:${key}`;
          const active = inFlightGetRequests.get(inFlightKey);
          if (active) {
            const response = await active;
            return { ...response, config: requestConfig };
          }

          const adapter = axios.getAdapter(sourceAdapter ?? api.defaults.adapter);
          const request = Promise.resolve(adapter(requestConfig));
          inFlightGetRequests.set(inFlightKey, request);
          try {
            return await request;
          } finally {
            if (inFlightGetRequests.get(inFlightKey) === request) {
              inFlightGetRequests.delete(inFlightKey);
            }
          }
        };
      }
    }
  }
  return config;
}, (error) => {
  requestActivityStore.decrement();
  if (isCanceledApiError(error)) {
    return Promise.reject(error);
  }
  const errUrl = error.config?.url ?? '';
  const errStatus = error.response?.status ?? 0;
  const errMethod = error.config?.method?.toUpperCase() ?? '';
  if (!errUrl.includes('/auth/')) {
    activityLog.error('API', `✕ ${errMethod} ${errUrl} ${errStatus}`, { msg: error.response?.data?.detail ?? error.message });
  }
  return Promise.reject(error);
});

/**
 * Response interceptor:
 *  • GET  success — store the response in the cache with the appropriate TTL.
 *  • POST / PUT / DELETE success — invalidate cached entries for the same resource
 *    so stale data is never served after a mutation, unless a typed read-only
 *    POST opts out explicitly.
 */
api.interceptors.response.use((response) => {
  requestActivityStore.decrement();
  const _rMethod = response.config.method?.toUpperCase() ?? '';
  const _rUrl = response.config.url ?? '';
  const _status = response.status;
  if (!_rUrl.includes('/auth/verify') && !_rUrl.includes('/auth/mfa')) {
    const level = _status >= 400 ? 'error' : _rMethod !== 'GET' ? 'info' : 'debug';
    activityLog[level]('API', `← ${_rMethod} ${_rUrl} ${_status}`);
  }
  const method = response.config.method?.toLowerCase();
  const url = response.config.url ?? '';

  if (method === 'get') {
    const ttl = getTTLForUrl(url);
    if (ttl > 0) {
      const key = buildCacheKey(url, response.config.params, getAuth().username);
      const requestGeneration = (response.config as CacheAwareRequestConfig).__cacheGeneration;
      if (requestGeneration !== cacheGeneration) {
        return response;
      }
        cacheService.set(key, response, ttl, deriveCacheTags(url));
    }
  } else if ((method === 'post' || method === 'put' || method === 'delete') && !response.config.skipCacheInvalidation) {
      cacheGeneration += 1;
      invalidateForMutation(url);
  }

  return response;
}, (error) => {
  requestActivityStore.decrement();
  if (isCanceledApiError(error)) {
    return Promise.reject(error);
  }
  const errUrl = error.config?.url ?? '';
  const errStatus = error.response?.status ?? 0;
  const errMethod = error.config?.method?.toUpperCase() ?? '';
  if (errStatus === 401 && !errUrl.includes('/auth/verify')) {
    dispatchAuthRequired(errUrl, errMethod);
  }
  if (!errUrl.includes('/auth/')) {
    activityLog.error('API', `✕ ${errMethod} ${errUrl} ${errStatus}`, { msg: error.response?.data?.detail ?? error.message });
  }
  return Promise.reject(error);
});

export default api;
