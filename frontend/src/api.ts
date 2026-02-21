import axios from 'axios';

/**
 * API base URL used by all frontend requests.
 *
 * Resolution order (first defined wins):
 *   1. VITE_API_BASE_URL env var  – explicit override, useful for CDN / split deployments
 *   2. Derived from BASE_URL       – BASE_URL is set to VITE_BASE at build time
 *                                    (e.g. "/my-vpn/"), so the API lives at "/my-vpn/api"
 *
 * Examples:
 *   VITE_BASE=/          → API_BASE = "/api"
 *   VITE_BASE=/my-vpn/   → API_BASE = "/my-vpn/api"
 *   VITE_API_BASE_URL=https://api.example.com → API_BASE = "https://api.example.com"
 */
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  import.meta.env.BASE_URL.replace(/\/$/, '') + '/api';

/** Pre-configured axios instance – use this instead of raw axios for all API calls. */
const api = axios.create({ baseURL: API_BASE });

export default api;
