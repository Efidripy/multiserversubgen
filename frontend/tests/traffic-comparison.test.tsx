import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ design: 'classic' }));
vi.mock('../src/contexts/ThemeContext', () => ({ useDesign: () => state.design }));
vi.mock('../src/services/DashboardDataContext', () => ({ useDashboardData: () => null }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
vi.mock('../src/api/trafficComparison', () => ({ getTrafficComparison: vi.fn().mockResolvedValue({ series_current: [], series_previous: [], totals: { current: 200, previous: 100 }, top_clients: [{ email: 'a@example.test', current: 50, previous: null, delta_pct: null }, { email: 'b@example.test', current: 40, previous: 20, delta_pct: 100 }], top_growth: [{ email: 'outside@example.test', current: 10, previous: 1, delta_pct: 900 }] }) }));
import { getTrafficComparison } from '../src/api/trafficComparison';
import { DashboardSummary } from '../src/components/DashboardSummary';
afterEach(cleanup);
it('shows comparison only in new design and handles missing previous values', async () => {
  state.design = 'classic';
  const view = render(<DashboardSummary />);
  expect(screen.queryByTestId('traffic-comparison')).toBeNull();
  state.design = 'new';
  view.rerender(<DashboardSummary />);
  await waitFor(() => expect(screen.getByText('a@example.test')).toBeTruthy());
  expect(screen.getAllByText('+100.0%').length).toBeGreaterThan(0);
  expect(screen.getAllByText('—').length).toBeGreaterThan(0);
});

it('sorts clients by growth', async () => {
  state.design = 'new';
  const view = render(<DashboardSummary />);
  await waitFor(() => expect(screen.getByText('b@example.test')).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'comparison.growth' }));
  const rows = view.container.querySelectorAll('.tc-row');
  expect(rows[0].textContent).toContain('outside@example.test');
  expect(screen.queryByText('a@example.test')).toBeNull();
});


it('uses round byte-unit ticks and caps a share from mismatched sources', async () => {
  const gb = 1024 ** 3;
  vi.mocked(getTrafficComparison).mockResolvedValueOnce({
    history_days: 2,
    previous_available: true,
    series_current: [{ ts: 1, value: 93.1 * gb }],
    series_previous: [{ ts: 1, value: 80 * gb }],
    totals: { current: 100, previous: 50 },
    top_clients: [{ email: 'over@example.test', current: 150, previous: null, delta_pct: null }],
    top_growth: [],
  } as Awaited<ReturnType<typeof getTrafficComparison>>);
  state.design = 'new';
  render(<DashboardSummary />);
  await screen.findByText('over@example.test');
  for (const tick of ['25.0 GB', '50.0 GB', '75.0 GB', '100.0 GB']) expect(screen.getByText(tick)).toBeTruthy();
  expect(screen.getByText('\u2248100%').getAttribute('title')).toBeTruthy();
});

it('hides the current period delta when there is no previous period and bounds the curve', async () => {
  vi.mocked(getTrafficComparison).mockResolvedValueOnce({
    history_days: 1, previous_available: false,
    series_current: [{ ts: 1, value: 0 }, { ts: 2, value: 100 }, { ts: 3, value: 0 }],
    series_previous: [], totals: { current: 100, previous: null }, top_clients: [], top_growth: [],
  } as Awaited<ReturnType<typeof getTrafficComparison>>);
  state.design = 'new';
  const view = render(<DashboardSummary />);
  await screen.findByText('comparison.currentPeriod');
  const tile = screen.getByText('comparison.currentPeriod').parentElement!;
  expect(tile.querySelector('em')).toBeNull();
  const path = view.container.querySelector('.tc-current')!.getAttribute('d')!;
  const ys = [...path.matchAll(/(?:M |C |, )(?:[\d.]+) ([\d.]+)/g)].map(match => Number(match[1]));
  expect(ys.length).toBeGreaterThan(2);
  expect(ys.every(y => y >= 20 && y <= 210)).toBe(true);
});


it('marks interpolated segments and tooltip values', async () => {
  vi.mocked(getTrafficComparison).mockResolvedValueOnce({
    history_days: 2, previous_available: true,
    series_current: [{ ts: 1, value: 10, estimated: true }, { ts: 2, value: 20 }],
    series_previous: [{ ts: 1, value: 5, estimated: true }, { ts: 2, value: 10 }],
    totals: { current: 30, previous: 15 }, top_clients: [], top_growth: [],
  });
  state.design = 'new';
  const view = render(<DashboardSummary />);
  await screen.findByText('comparison.currentPeriod');
  expect(view.container.querySelector('.tc-current[opacity="0.4"]')).toBeTruthy();
  expect(view.container.querySelector('.tc-previous[opacity="0.4"]')).toBeTruthy();
  const chart = screen.getByRole('img', { name: 'comparison.totalTraffic' });
  vi.spyOn(chart, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 600 } as DOMRect);
  fireEvent(chart, new MouseEvent('pointermove', { bubbles: true, clientX: 60 }));
  expect(screen.getAllByTitle('comparison.estimated')).toHaveLength(2);
});
