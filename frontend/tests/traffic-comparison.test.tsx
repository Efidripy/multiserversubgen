import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ design: 'classic' }));
vi.mock('../src/contexts/ThemeContext', () => ({ useDesign: () => state.design }));
vi.mock('../src/services/DashboardDataContext', () => ({ useDashboardData: () => null }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
vi.mock('../src/api/trafficComparison', () => ({ getTrafficComparison: vi.fn().mockResolvedValue({ series_current: [], series_previous: [], totals: { current: 200, previous: 100 }, top_clients: [{ email: 'a@example.test', current: 50, previous: null, delta_pct: null }, { email: 'b@example.test', current: 40, previous: 20, delta_pct: 100 }] }) }));
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
  expect(rows[0].textContent).toContain('b@example.test');
});


it('uses round byte-unit ticks and caps a share from mismatched sources', async () => {
  const gb = 1024 ** 3;
  vi.mocked(getTrafficComparison).mockResolvedValueOnce({
    series_current: [{ ts: 1, value: 93.1 * gb }],
    series_previous: [{ ts: 1, value: 80 * gb }],
    totals: { current: 100, previous: 50 },
    top_clients: [{ email: 'over@example.test', current: 150, previous: null, delta_pct: null }],
  } as Awaited<ReturnType<typeof getTrafficComparison>>);
  state.design = 'new';
  render(<DashboardSummary />);
  await screen.findByText('over@example.test');
  for (const tick of ['25.0 GB', '50.0 GB', '75.0 GB', '100.0 GB']) expect(screen.getByText(tick)).toBeTruthy();
  expect(screen.getByText('\u2248100%').getAttribute('title')).toBeTruthy();
});
