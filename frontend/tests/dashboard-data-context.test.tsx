import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

function PeriodSwitchProbe() {
  const data = useDashboardData();
  return <>
    <button type="button" onClick={() => data?.setPeriod('week')}>week</button>
    <output>{data?.summary ? `${data.period}:${data.summary.nodes_total}` : 'loading'}</output>
  </>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
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

  it('aborts and ignores an older period response after the operator selects a newer period', async () => {
    const allTime = deferred<any>();
    const week = deferred<any>();
    mocks.getDashboardOverview
      .mockImplementationOnce(() => allTime.promise)
      .mockImplementationOnce(() => week.promise);

    render(<DashboardDataProvider><PeriodSwitchProbe /></DashboardDataProvider>);

    await waitFor(() => expect(mocks.getDashboardOverview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'week' }));
    await waitFor(() => expect(mocks.getDashboardOverview).toHaveBeenCalledTimes(2));
    expect(mocks.getDashboardOverview.mock.calls[0][1].signal.aborted).toBe(true);

    week.resolve({
      projection: 'dashboard-v1',
      summary: { nodes_total: 7, nodes_online: 7, online_clients_total: 2 },
      fleet: [{ id: 7, name: 'week-node', panel_url: 'https://week.example.test', available: true }],
    });
    await waitFor(() => expect(screen.getByText('week:7')).toBeTruthy());

    allTime.resolve({
      projection: 'dashboard-v1',
      summary: { nodes_total: 1, nodes_online: 1, online_clients_total: 1 },
      fleet: [{ id: 1, name: 'old-node', panel_url: 'https://old.example.test', available: true }],
    });
    await waitFor(() => expect(screen.getByText('week:7')).toBeTruthy());
    expect(window.sessionStorage.getItem('sub-manager:dashboard-overview:v1:admin')).toContain('week-node');
    expect(window.sessionStorage.getItem('sub-manager:dashboard-overview:v1:admin')).not.toContain('old-node');
  });
});
