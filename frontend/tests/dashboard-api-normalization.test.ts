import { describe, expect, it } from 'vitest';
import { normalizeDashboardFleet } from '../src/api/dashboard';

describe('dashboard fleet normalization', () => {
  it('preserves incomplete inventory telemetry as unknown instead of zero', () => {
    expect(normalizeDashboardFleet([{
      id: 1,
      name: 'partial',
      available: true,
      inbounds_available: false,
      online_clients: null,
      traffic_total: null,
    }])).toMatchObject([{
      id: 1,
      inbounds_available: false,
      online_clients: null,
      traffic_total: null,
    }]);
  });
});
