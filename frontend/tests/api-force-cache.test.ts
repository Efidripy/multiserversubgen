import axios from 'axios';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import api, { resetInFlightGetRequests } from '../src/api/client';
import { cacheService } from '../src/services/cacheService';

describe('API force cache option', () => {
  beforeEach(() => { cacheService.invalidate(); resetInFlightGetRequests(); });
  afterEach(() => { api.defaults.adapter = axios.defaults.adapter; cacheService.invalidate(); resetInFlightGetRequests(); });

  it('bypasses cache, adds refresh only to contract routes, and refreshes cached value', async () => {
    let calls = 0;
    api.defaults.adapter = async (config: any) => ({ data: { value: ++calls }, status: 200, statusText: 'OK', headers: {}, config: { ...config, method: 'get' } });
    await api.get('/v1/clients', { sessionOnlyAuth: true });
    expect((await api.get('/v1/clients')).data.value).toBe(1);
    const forced = await api.get('/v1/clients', { force: true });
    expect(forced.data.value).toBe(2);
    expect(forced.config.params.refresh).toBe(1);
    const other = await api.get('/v1/telegram/requests', { force: true });
    expect(other.config.params?.refresh).toBeUndefined();
  });
});
