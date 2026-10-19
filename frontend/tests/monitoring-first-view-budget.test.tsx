import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock('../src/api', () => ({
  default: { get: mocks.apiGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock('../src/auth', () => ({
  getAuth: () => ({ username: 'test', password: 'test' }),
}));

vi.mock('../src/contexts/ThemeContext', () => ({
  useTheme: () => ({ stylePreset: '3' }),
}));

vi.mock('../src/services/useTrafficStatsSubscription', () => ({
  useTrafficStatsSubscription: () => undefined,
}));

vi.mock('../src/components/ChoiceChips', () => ({
  ChoiceChips: ({ options, onChange }: { options: Array<{ value: string | number; label: string }>; onChange: (value: string | number) => void }) => (
    <div>{options.map((option) => <button key={String(option.value)} type="button" onClick={() => onChange(option.value)}>{option.label}</button>)}</div>
  ),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-chartjs-2', () => ({
  Bar: () => <div data-testid="bar-chart" />,
  Line: () => <div data-testid="line-chart" />,
}));

import { MonitoringDashboard } from '../src/components/MonitoringDashboard';

const coreAllRoutes = [
  '/v1/nodes',
  '/v1/snapshots/latest',
  '/v1/health/deps',
  '/v1/servers/status',
  '/v1/collector/status',
];

const auxiliaryRoutes = [
  '/v1/history/nodes',
  '/v1/adguard/sources',
  '/v1/adguard/overview',
  '/v1/adguard/history',
  '/v1/monitoring/stack',
];

const successfulResponse = (route: string) => {
  if (route === '/v1/nodes') return { data: [{ id: 1, name: 'alpha' }] };
  if (route === '/v1/snapshots/latest') return { data: { nodes: [] } };
  if (route === '/v1/health/deps') return { data: { status: 'ok', collector_running: true, redis: { enabled: false, ok: true, error: null } } };
  if (route === '/v1/servers/status') return { data: { servers: [] } };
  if (route === '/v1/collector/status') return { data: {} };
  if (route === '/v1/history/nodes') return { data: { points: [] } };
  if (route === '/v1/adguard/sources') return { data: [] };
  if (route === '/v1/adguard/overview') return { data: { summary: {}, sources: [] } };
  if (route === '/v1/adguard/history') return { data: { buckets: [], series: [], summary: {} } };
  if (route === '/v1/monitoring/stack') return { data: { services: {}, public_paths: {} } };
  if (route === '/v1/servers/7/status') return { data: null };
  throw new Error(`Unexpected route: ${route}`);
};

const requestedRoutes = () => mocks.apiGet.mock.calls.map(([route]) => route as string);

describe('MonitoringDashboard first-view request budget', () => {
  afterEach(() => {
    cleanup();
    mocks.apiGet.mockReset();
    window.history.replaceState({}, '', '/');
  });

  it('keeps the All first view to its five truthful core reads and defers auxiliary data until an explicit affordance', async () => {
    mocks.apiGet.mockImplementation((route: string) => Promise.resolve(successfulResponse(route)));

    render(<MonitoringDashboard />);

    await waitFor(() => expect(requestedRoutes().sort()).toEqual([...coreAllRoutes].sort()));
    expect(requestedRoutes()).not.toEqual(expect.arrayContaining(auxiliaryRoutes));
    expect(screen.getByText('monitoringDashboard.historyDeferred')).toBeTruthy();
    expect(screen.getByText('monitoringDashboard.monitoringDetailsDeferred')).toBeTruthy();

    fireEvent.click(screen.getByText('monitoringDashboard.loadHistory'));
    await waitFor(() => expect(requestedRoutes()).toContain('/v1/history/nodes'));

    fireEvent.click(screen.getByText('monitoringDashboard.loadMonitoringDetails'));
    await waitFor(() => expect(requestedRoutes()).toEqual(expect.arrayContaining([
      '/v1/adguard/sources',
      '/v1/adguard/overview',
      '/v1/adguard/history',
      '/v1/monitoring/stack',
    ])));
  });

  it('keeps a selected-node deep link scoped and does not start history or monitoring auxiliary reads', async () => {
    window.history.replaceState({}, '', '/?server=7');
    mocks.apiGet.mockImplementation((route: string) => Promise.resolve(successfulResponse(route)));

    render(<MonitoringDashboard />);

    await waitFor(() => expect(requestedRoutes()).toEqual(['/v1/servers/7/status']));
    expect(requestedRoutes()).not.toEqual(expect.arrayContaining([
      ...coreAllRoutes,
      ...auxiliaryRoutes,
    ]));
  });

  it('shows an explicit unknown state and error when an explicitly requested stack probe fails', async () => {
    mocks.apiGet.mockImplementation((route: string) => {
      if (route === '/v1/monitoring/stack') return Promise.reject({ response: { data: { detail: 'stack unavailable' } } });
      return Promise.resolve(successfulResponse(route));
    });

    render(<MonitoringDashboard />);
    await waitFor(() => expect(requestedRoutes().sort()).toEqual([...coreAllRoutes].sort()));

    fireEvent.click(screen.getByText('monitoringDashboard.loadMonitoringDetails'));
    await waitFor(() => expect(screen.getByText('stack unavailable')).toBeTruthy());
    expect(screen.getAllByText('monitoringDashboard.statusUnknown').length).toBe(3);
  });
});
