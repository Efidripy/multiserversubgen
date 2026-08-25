import axios from 'axios';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import api, { resetCacheGeneration, resetInFlightGetRequests } from '../src/api/client';
import { checkNodeConnection } from '../src/api/nodes';
import { cacheService } from '../src/services/cacheService';

describe('API cold-request coalescing', () => {
  beforeEach(() => {
    cacheService.invalidate();
    resetCacheGeneration();
    resetInFlightGetRequests();
  });

  afterEach(() => {
    api.defaults.adapter = axios.defaults.adapter;
    cacheService.invalidate();
    resetCacheGeneration();
    resetInFlightGetRequests();
  });

  it('shares concurrent identical GET requests before the cache is warm', async () => {
    let calls = 0;
    let release: (() => void) | undefined;
    api.defaults.adapter = async (config: any) => {
      calls += 1;
      await new Promise<void>((resolve) => { release = resolve; });
      return {
        data: { ok: true },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    const first = api.get('/v1/perf-coalescing');
    const second = api.get('/v1/perf-coalescing');
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(calls).toBe(1);

    release?.();
    await expect(Promise.all([first, second])).resolves.toHaveLength(2);
    expect(calls).toBe(1);
  });

  it('does not cache a GET response that started before a successful mutation', async () => {
    let getCalls = 0;
    let releaseStaleGet: (() => void) | undefined;
    api.defaults.adapter = async (config: any) => {
      if (config.method === 'get') {
        getCalls += 1;
        if (getCalls === 1) {
          await new Promise<void>((resolve) => { releaseStaleGet = resolve; });
          return {
            data: { version: 'before' },
            status: 200,
            statusText: 'OK',
            headers: {},
            config,
          };
        }
        return {
          data: { version: 'after' },
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        };
      }
      return {
        data: { success: true },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    const staleGet = api.get('/v1/clients');
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await api.put('/v1/clients/client-1', { email: 'after@example.test' });

    releaseStaleGet?.();
    await expect(staleGet).resolves.toMatchObject({ data: { version: 'before' } });

    await expect(api.get('/v1/clients')).resolves.toMatchObject({ data: { version: 'after' } });
    expect(getCalls).toBe(2);
  });

  it('keeps cached traffic projections after the designated read-only totals POST', async () => {
    let trafficGetCalls = 0;
    api.defaults.adapter = async (config: any) => {
      if (config.method === 'get') {
        trafficGetCalls += 1;
        return {
          data: { stats: { 'operator@example.test': { total: 42 } } },
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        };
      }
      return {
        data: { totals: { 'operator@example.test': 42 } },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await api.get('/v1/traffic/stats-by-period', { params: { group_by: 'client', period: 'day' } });
    await api.post('/v1/traffic/client-totals', { emails: ['operator@example.test'], period: 'day' }, {
      skipCacheInvalidation: true,
    });
    await api.get('/v1/traffic/stats-by-period', { params: { group_by: 'client', period: 'day' } });

    expect(trafficGetCalls).toBe(1);
  });

  it('keeps cached read projections after a node connection probe', async () => {
    let trafficGetCalls = 0;
    api.defaults.adapter = async (config: any) => {
      if (config.method === 'get') {
        trafficGetCalls += 1;
        return {
          data: { stats: { 'operator@example.test': { total: 42 } } },
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        };
      }
      expect(config.url).toBe('/v1/nodes/check-connection');
      expect(config.skipCacheInvalidation).toBe(true);
      return {
        data: { success: true },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await api.get('/v1/traffic/stats-by-period', { params: { group_by: 'client', period: 'day' } });
    await checkNodeConnection({ url: 'https://node.example.test' });
    await api.get('/v1/traffic/stats-by-period', { params: { group_by: 'client', period: 'day' } });

    expect(trafficGetCalls).toBe(1);
  });

  it('continues to invalidate traffic cache after an ordinary POST mutation', async () => {
    let trafficGetCalls = 0;
    api.defaults.adapter = async (config: any) => {
      if (config.method === 'get') {
        trafficGetCalls += 1;
        return {
          data: { stats: {} },
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        };
      }
      return {
        data: { success: true },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await api.get('/v1/traffic/stats-by-period', { params: { group_by: 'client', period: 'day' } });
    await api.post('/v1/traffic/reset', { email: 'operator@example.test' });
    await api.get('/v1/traffic/stats-by-period', { params: { group_by: 'client', period: 'day' } });

    expect(trafficGetCalls).toBe(2);
  });
});
