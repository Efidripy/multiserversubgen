import axios from 'axios';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import api, { resetInFlightGetRequests } from '../src/api/client';
import { getClientPresence, listClientsBySource } from '../src/api/clients';
import { getInboundOptions } from '../src/api/inbounds';
import { listNodes } from '../src/api/nodes';
import { clearAuthCredentials, setAuthCredentials } from '../src/auth';
import { cacheService } from '../src/services/cacheService';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('Client Manager periodic browser session auth', () => {
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

  it('uses the HttpOnly browser session for Client Manager periodic projections', async () => {
    const requests: any[] = [];
    const controller = new AbortController();
    api.defaults.adapter = async (config: any) => {
      requests.push(config);
      return {
        data: config.url === '/v1/inbounds/options' ? { inbounds: [] } : {},
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await Promise.all([
      listNodes({ signal: controller.signal, sessionOnlyAuth: true }),
      listClientsBySource('all', { signal: controller.signal, sessionOnlyAuth: true }),
      getInboundOptions({ signal: controller.signal, sessionOnlyAuth: true }),
      getClientPresence(controller.signal, { sessionOnlyAuth: true }),
    ]);

    expect(requests.map((request) => request.url)).toEqual([
      '/v1/nodes',
      '/v1/clients',
      '/v1/inbounds/options',
      '/v1/clients/presence',
    ]);
    for (const request of requests) {
      expect(request.auth).toBeUndefined();
      expect(request.headers?.get?.('Authorization')).toBeUndefined();
      expect(request.withCredentials).toBe(true);
    }
  });

  it('keeps the unclassified generic node read on its existing Basic contract', async () => {
    let request: any;
    api.defaults.adapter = async (config: any) => {
      request = config;
      return { data: [], status: 200, statusText: 'OK', headers: {}, config };
    };

    await listNodes();

    expect(request.auth).toMatchObject({ username: 'admin', password: 'legacy-basic-must-not-be-replayed' });
  });

  it('binds every Client Manager periodic path to the classified session-only calls', () => {
    const source = read('src/components/ClientManager.tsx');

    expect(source).toContain('getClientPresence(signal, { sessionOnlyAuth: true })');
    expect(source).toContain('CLIENT_PRESENCE_REFRESH_MS = 30 * 1000');
    expect(source).toContain('window.setInterval(refresh, CLIENT_PRESENCE_REFRESH_MS)');
    expect(source).toContain("const [refreshInterval, setRefreshInterval] = useState<number>(_cmPrefs.refreshInterval ?? 60);");
    expect(source).toContain('if (!autoRefresh) return;');
    expect(source).toContain('setInterval(() => loadClients(true), refreshInterval * 1000)');
    expect(source).toContain('fallbackPollIntervalMs: CLIENTS_PAGE_REFRESH_MS');
    expect(source).toContain('CLIENTS_PAGE_REFRESH_MS = 5 * 60 * 1000');
    expect(source).toContain('listNodes({ signal: controller.signal, sessionOnlyAuth: true })');
    expect(source).toContain("listClientsBySource(sourceFilter, { signal: controller.signal, sessionOnlyAuth: true })");
    expect(source).toContain('getInboundOptions({ signal: controller.signal, sessionOnlyAuth: true })');
  });
});
