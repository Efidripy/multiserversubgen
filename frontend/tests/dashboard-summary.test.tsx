import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { summary } = vi.hoisted(() => ({
  summary: {
    nodes_total: 1,
    nodes_online: 1,
    clients_total: 3,
    online_clients_total: 1,
    online_by_node: { alpha: 1 },
    online_by_node_id: { '1': 1 },
    traffic: { upload: 400, download: 1600, total: 2000 },
    traffic_period: 'all_time',
    traffic_note: null,
    top_clients: [
      { email: 'highest@example.test', upload: 400, download: 600, total: 1000 },
      { email: 'middle@example.test', upload: 30, download: 70, total: 100 },
      { email: 'least@example.test', upload: 2, download: 3, total: 5 },
    ],
  },
}));

const mocks = vi.hoisted(() => ({
  dashboardData: {
    summary,
    fleet: [{ id: 1, name: 'alpha', enabled: true }],
    period: 'all_time' as const,
    loading: false,
    stale: false,
    lastUpdated: new Date('2026-08-25T12:00:00Z'),
    setPeriod: vi.fn(),
    refresh: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key }),
}));

vi.mock('../src/services/DashboardDataContext', () => ({
  useDashboardData: () => mocks.dashboardData,
}));

import { DashboardSummary } from '../src/components/DashboardSummary';

afterEach(cleanup);

describe('DashboardSummary traffic projection', () => {
  it('renders aggregate top traffic rows, correct online KPIs and opens the selected client', async () => {
    const onNavigate = vi.fn();
    const onOnlineClientsChange = vi.fn();
    render(<DashboardSummary onNavigate={onNavigate} onOnlineClientsChange={onOnlineClientsChange} />);

    await waitFor(() => expect(screen.getByText('highest@example.test')).toBeTruthy());

    expect(screen.queryByText('No traffic records found')).toBeNull();
    expect(screen.getByText('middle@example.test')).toBeTruthy();
    expect(screen.getByText('least@example.test')).toBeTruthy();
    expect(screen.getByText('1 / 1')).toBeTruthy();
    expect(screen.getByText('Active Clients')).toBeTruthy();
    expect(onOnlineClientsChange).toHaveBeenLastCalledWith(1);

    const trafficRow = screen.getByText('highest@example.test').parentElement;
    expect(trafficRow?.className).toContain('w-full');
    expect(trafficRow?.className).not.toContain('max-w-[360px]');

    fireEvent.click(screen.getByText('highest@example.test'));
    expect(sessionStorage.getItem('sm_nav_client_search')).toBe('highest@example.test');
    expect(onNavigate).toHaveBeenCalledWith('clients');
  });

  it('delegates period changes and refresh to the shared Dashboard provider', async () => {
    render(<DashboardSummary />);

    fireEvent.click(screen.getByRole('button', { name: 'traffic.periodWeek' }));
    expect(mocks.dashboardData.setPeriod).toHaveBeenCalledWith('week');

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(mocks.dashboardData.refresh).toHaveBeenCalledOnce());
  });
});
