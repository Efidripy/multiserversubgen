import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getDashboardOverview: vi.fn(),
  forceNodeRefresh: vi.fn(),
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
vi.mock('../src/services/forceRefresh', () => ({ forceNodeRefresh: mocks.forceNodeRefresh }));

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

function ForceProbe() {
  const data = useDashboardData();
  return <>
    <button type="button" onClick={() => void data?.refresh(true)}>force</button>
    <output>{data?.summary ? `${data.summary.nodes_total}:${data.fleet.length}` : 'loading'}</output>
    <output data-testid="stale">{String(data?.stale)}</output>
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
  mocks.forceNodeRefresh.mockResolvedValue(undefined);
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

  it('keeps the previous overview visible during and after a failed force refresh', async () => {
    window.sessionStorage.setItem('sub-manager:dashboard-overview:v1:admin', JSON.stringify({
      savedAt: Date.now(), period: 'all_time', overview: {
        projection: 'dashboard-v1',
        summary: { nodes_total: 4, nodes_online: 3, online_clients_total: 1 },
        fleet: [{ id: 1, name: 'old', available: true }],
      },
    }));
    mocks.getDashboardOverview.mockResolvedValueOnce({ projection: 'dashboard-v1', summary: { nodes_total: 4 }, fleet: [{ id: 1 }] });
    render(<DashboardDataProvider><ForceProbe /></DashboardDataProvider>);
    await waitFor(() => expect(screen.getByText('4:1')).toBeTruthy());
    const refreshNow = deferred<void>();
    mocks.forceNodeRefresh.mockReturnValueOnce(refreshNow.promise);
    fireEvent.click(screen.getByRole('button', { name: 'force' }));
    expect(screen.getByText('4:1')).toBeTruthy();
    mocks.getDashboardOverview.mockRejectedValueOnce(new Error('failed'));
    refreshNow.resolve();
    await waitFor(() => expect(screen.getByText('4:1')).toBeTruthy());
  });

  it('replaces the previous overview only after a successful force response', async () => {
    window.sessionStorage.setItem('sub-manager:dashboard-overview:v1:admin', JSON.stringify({
      savedAt: Date.now(), period: 'all_time', overview: {
        projection: 'dashboard-v1', summary: { nodes_total: 2 }, fleet: [{ id: 1 }],
      },
    }));
    const next = deferred<any>();
    mocks.getDashboardOverview.mockResolvedValueOnce({ projection: 'dashboard-v1', summary: { nodes_total: 2 }, fleet: [{ id: 1 }] });
    render(<DashboardDataProvider><ForceProbe /></DashboardDataProvider>);
    await waitFor(() => expect(screen.getByText('2:1')).toBeTruthy());
    mocks.getDashboardOverview.mockReturnValueOnce(next.promise);
    fireEvent.click(screen.getByRole('button', { name: 'force' }));
    expect(screen.getByText('2:1')).toBeTruthy();
    next.resolve({ projection: 'dashboard-v1', summary: { nodes_total: 9 }, fleet: [{ id: 9 }, { id: 10 }] });
    await waitFor(() => expect(screen.getByText('9:2')).toBeTruthy());
  });
});
