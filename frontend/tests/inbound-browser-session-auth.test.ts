import axios from 'axios';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import api, { resetInFlightGetRequests } from '../src/api/client';
import { getInboundsHeaderSource } from '../src/api/dashboard';
import { clearAuthCredentials, setAuthCredentials } from '../src/auth';
import { cacheService } from '../src/services/cacheService';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('Inbound browser session auth', () => {
  beforeEach(() => {
    cacheService.invalidate();
    resetInFlightGetRequests();
    setAuthCredentials('admin', 'legacy-basic-must-not-be-replayed', '', 'ticket', 'admin');
  });

  afterEach(() => {
    api.defaults.adapter = axios.defaults.adapter;
    clearAuthCredentials();
    cacheService.invalidate();
    resetInFlightGetRequests();
  });

  it('uses the HttpOnly session for the full Inbounds projection and aggregate stats', async () => {
    const requests: any[] = [];
    api.defaults.adapter = async (config: any) => {
      requests.push(config);
      return {
        data: config.url === '/v1/inbounds' ? { inbounds: [] } : {},
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await getInboundsHeaderSource();
    await api.get('/v1/inbounds/stats', { sessionOnlyAuth: true });

    expect(requests.map((request) => request.url)).toEqual([
      '/v1/inbounds',
      '/v1/inbounds/stats',
    ]);
    for (const request of requests) {
      expect(request.auth).toBeUndefined();
      expect(request.headers?.get?.('Authorization')).toBeUndefined();
      expect(request.withCredentials).toBe(true);
    }
  });

  it('binds Inbounds cold reads to the exact session-only requests', () => {
    expect(read('src/api/dashboard.ts')).toContain(
      "api.get('/v1/inbounds', { sessionOnlyAuth: true, signal: options.signal })",
    );
    expect(read('src/components/InboundManager.tsx')).toContain(
      ".get('/v1/inbounds/stats', { sessionOnlyAuth: true, signal: controller.signal })",
    );
    expect(read('src/components/InboundManager.tsx')).toContain(
      'listNodes({ signal: controller.signal, sessionOnlyAuth: true })',
    );
  });
});
