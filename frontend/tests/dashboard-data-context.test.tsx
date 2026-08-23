import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getDashboardOverview: vi.fn(),
}));

vi.mock('../src/api/dashboard', () => ({
  getDashboardOverview: mocks.getDashboardOverview,
}));

vi.mock('../src/api/nodes', () => ({
  NODES_CHANGED_EVENT: 'nodes-changed',
}));

vi.mock('../src/auth', () => ({
  getAuth: () => ({ username: 'admin' }),
}));

import { DashboardDataProvider, useDashboardData } from '../src/services/DashboardDataContext';

function Probe() {
  const data = useDashboardData();
  return <output>{data?.summary ? `${data.summary.nodes_total}:${data.fleet.length}` : 'loading'}</output>;
}

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.clearAllMocks();
});

describe('DashboardDataProvider', () => {
  it('loads one aggregate, persists only the lightweight overview, and shares it with consumers', async () => {
    mocks.getDashboardOverview.mockResolvedValue({
      projection: 'dashboard-v1',
      summary: { nodes_total: 100, nodes_online: 98, online_clients_total: 30 },
      fleet: [{ id: 1, name: 'alpha', panel_url: 'https://alpha.example.test', available: true }],
    });

    render(<DashboardDataProvider><Probe /></DashboardDataProvider>);

    await waitFor(() => expect(screen.getByText('100:1')).toBeTruthy());
    expect(mocks.getDashboardOverview).toHaveBeenCalledTimes(1);
    const stored = window.sessionStorage.getItem('sub-manager:dashboard-overview:v1:admin');
    expect(stored).toContain('dashboard-v1');
    expect(stored).not.toContain('password');
    expect(stored).not.toContain('inbounds');
  });
});
