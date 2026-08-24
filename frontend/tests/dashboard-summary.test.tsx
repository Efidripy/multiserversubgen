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
  getDashboardSummary: vi.fn(),
  listNodes: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key }),
}));

vi.mock('../src/api/dashboard', () => ({
  getDashboardSummary: mocks.getDashboardSummary,
  normalizeDashboardSummary: (value: unknown) => value,
}));

vi.mock('../src/api/nodes', () => ({
  listNodes: mocks.listNodes,
  NODES_CHANGED_EVENT: 'nodes-changed',
}));

vi.mock('../src/services/DashboardDataContext', () => ({
  useDashboardData: () => null,
}));

import { DashboardSummary } from '../src/components/DashboardSummary';

afterEach(cleanup);

describe('DashboardSummary traffic projection', () => {
  it('renders cached top traffic rows, correct online KPIs and opens the selected client', async () => {
    const onNavigate = vi.fn();
    const onOnlineClientsChange = vi.fn();
    mocks.getDashboardSummary.mockResolvedValue(summary);
    mocks.listNodes.mockResolvedValue([{ id: 1, name: 'alpha', enabled: true }]);
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

  it('loads all traffic KPIs for the selected period in one summary request', async () => {
    mocks.getDashboardSummary.mockResolvedValue(summary);
    mocks.listNodes.mockResolvedValue([{ id: 1, name: 'alpha', enabled: true }]);
    render(<DashboardSummary />);

    await waitFor(() => expect(mocks.getDashboardSummary).toHaveBeenCalledWith('all_time'));
    fireEvent.click(screen.getByRole('button', { name: 'traffic.periodWeek' }));

    await waitFor(() => expect(mocks.getDashboardSummary).toHaveBeenLastCalledWith('week'));
  });
});
