import axios from 'axios';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import api, { resetInFlightGetRequests } from '../src/api/client';
import { cacheService } from '../src/services/cacheService';

describe('API cold-request coalescing', () => {
  beforeEach(() => {
    cacheService.invalidate();
    resetInFlightGetRequests();
  });

  afterEach(() => {
    api.defaults.adapter = axios.defaults.adapter;
    cacheService.invalidate();
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
});
