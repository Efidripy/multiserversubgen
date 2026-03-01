import axios, { InternalAxiosRequestConfig } from 'axios';
import { cacheService } from './services/cacheService';
import { getAuth } from './auth';

/**
 * API base URL used by all frontend requests.
 *
 * Resolution order (first defined wins):
 *   1. VITE_API_BASE_URL env var  – explicit override, useful for CDN / split deployments
 *   2. Derived from BASE_URL       – BASE_URL is set to VITE_BASE at build time
 *                                    (e.g. "/my-panel/"), so the API lives at "/my-panel/api"
 *
 * Examples:
 *   VITE_BASE=/          → API_BASE = "/api"
 *   VITE_BASE=/my-panel/   → API_BASE = "/my-panel/api"
 *   VITE_API_BASE_URL=https://api.example.com → API_BASE = "https://api.example.com"
 */
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  import.meta.env.BASE_URL.replace(/\/$/, '') + '/api';

/**
 * Per-route cache TTLs in milliseconds.
 * Used by the request interceptor to determine how long to cache each GET response.
 */
export const CACHE_TTL = {
  NODES: 5 * 60 * 1000,    // 5 min — node list changes infrequently
  CLIENTS: 3 * 60 * 1000,  // 3 min — client list
  TRAFFIC: 1 * 60 * 1000,  // 1 min — traffic data changes frequently
  INBOUNDS: 5 * 60 * 1000, // 5 min — inbound configuration
  EMAILS: 10 * 60 * 1000,  // 10 min — subscription emails
  DEFAULT: 2 * 60 * 1000,  // 2 min — fallback
} as const;

/** Map URL path fragments to their cache TTL. */
const ROUTE_TTLS: Array<[string, number]> = [
  ['/v1/nodes', CACHE_TTL.NODES],
  ['/v1/clients', CACHE_TTL.CLIENTS],
  ['/v1/traffic', CACHE_TTL.TRAFFIC],
  ['/v1/inbounds', CACHE_TTL.INBOUNDS],
  ['/v1/emails', CACHE_TTL.EMAILS],
];

function getTTLForUrl(url: string): number {
  for (const [pattern, ttl] of ROUTE_TTLS) {
    if (url.includes(pattern)) return ttl;
  }
  return CACHE_TTL.DEFAULT;
}

function buildCacheKey(url: string, params: unknown): string {
  if (params == null) return url;
  // Sort object keys so that {a:1, b:2} and {b:2, a:1} map to the same key.
  const stable = JSON.stringify(params, Object.keys(params as Record<string, unknown>).sort());
  return url + ':' + stable;
}

/** Pre-configured axios instance – use this instead of raw axios for all API calls. */
const api = axios.create({ baseURL: API_BASE });

/**
 * Request interceptor — for GET requests, check the in-memory cache first.
 * If a fresh entry exists, override the adapter to return the cached response
 * immediately without making a network round-trip.
 */
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const auth = getAuth();
  if (auth.totpCode) {
    config.headers = config.headers ?? {};
    config.headers['X-TOTP-Code'] = auth.totpCode;
  }

  if (config.method?.toLowerCase() === 'get') {
    const url = config.url ?? '';
    const ttl = getTTLForUrl(url);
    if (ttl > 0) {
      const key = buildCacheKey(url, config.params);
      const cached = cacheService.get(key);
      if (cached !== undefined) {
        // Short-circuit the HTTP request by returning the cached response via a
        // custom adapter.  This keeps callers' .then()/.catch() chains intact.
        config.adapter = () => Promise.resolve(cached as any);
      }
    }
  }
  return config;
});

/**
 * Response interceptor:
 *  • GET  success — store the response in the cache with the appropriate TTL.
 *  • POST / PUT / DELETE success — invalidate cached entries for the same resource
 *    so stale data is never served after a mutation.
 */
api.interceptors.response.use((response) => {
  const method = response.config.method?.toLowerCase();
  const url = response.config.url ?? '';

  if (method === 'get') {
    const ttl = getTTLForUrl(url);
    if (ttl > 0) {
      const key = buildCacheKey(url, response.config.params);
      cacheService.set(key, response, ttl);
    }
  } else if (method === 'post' || method === 'put' || method === 'delete') {
    // Derive the resource segment (e.g. '/v1/nodes') and invalidate all cached
    // entries for that resource so the next GET fetches fresh data.
    const match = url.match(/^(\/v\d+\/[^/?]+)/);
    if (match) {
      cacheService.invalidate(match[1]);
    }
  }

  return response;
});

export default api;
