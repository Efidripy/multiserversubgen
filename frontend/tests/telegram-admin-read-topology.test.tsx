import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ translate: (key: string) => key, toast: vi.fn() }));
const api = vi.hoisted(() => ({
  getTelegramBotConfiguration: vi.fn(), getTelegramDashboard: vi.fn(), getTelegramTransport: vi.fn(),
  listBlockedTelegramIdentities: vi.fn(), listDriftFindings: vi.fn(), listLifecycleSchedules: vi.fn(),
  listTelegramAppeals: vi.fn(), listTelegramCustomers: vi.fn(), listTelegramJobsPage: vi.fn(),
  listTelegramRequests: vi.fn(), listTelegramSupportRequests: vi.fn(),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.translate }) }));
vi.mock('../src/components/Toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));
vi.mock('../src/api/telegram', async (importOriginal) => ({ ...(await importOriginal<typeof import('../src/api/telegram')>()), ...api }));
import { TelegramAdmin } from '../src/components/TelegramAdmin';

const directTransport = { mode: 'direct' as const, row_version: 1, configured: true, reachable: true, proxy_host: null, proxy_port: null, updated_by: 'test', updated_at: '2026-10-19 00:00:00' };
const botConfiguration = { configured: false, token_suffix: null, row_version: 1, updated_by: 'test', updated_at: '2026-10-19 00:00:00', source: 'none' as const };
const customer = (email: string, customerId = 1) => ({ customer_id: customerId, email_display: email, origin: 'telegram', status: 'active', row_version: 1, telegram_user_id: null, telegram_username: null, telegram_first_name: null, telegram_last_name: null, node_count: 1, lifetime_bytes: null, traffic_observed_at: null, application_introduction: null, created_at: '2026-10-19 00:00:00', updated_at: '2026-10-19 00:00:00' });

beforeEach(() => {
  localStorage.clear();
  api.listTelegramCustomers.mockResolvedValue([]); api.listTelegramRequests.mockResolvedValue([]);
  api.listBlockedTelegramIdentities.mockResolvedValue([]); api.listTelegramAppeals.mockResolvedValue([]); api.listTelegramSupportRequests.mockResolvedValue([]);
  api.listTelegramJobsPage.mockResolvedValue({ items: [], total: 0, can_clear_history: false }); api.getTelegramDashboard.mockResolvedValue({});
  api.listLifecycleSchedules.mockResolvedValue([]); api.listDriftFindings.mockResolvedValue([]);
  api.getTelegramTransport.mockResolvedValue(directTransport); api.getTelegramBotConfiguration.mockResolvedValue(botConfiguration);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe('TelegramAdmin read topology', () => {
  it('loads only the customer projection for a clean Users entry', async () => {
    render(<TelegramAdmin />);
    await waitFor(() => expect(api.listTelegramCustomers).toHaveBeenCalledTimes(1));
    expect(api.listTelegramRequests).not.toHaveBeenCalled(); expect(api.listBlockedTelegramIdentities).not.toHaveBeenCalled();
    expect(api.listTelegramAppeals).not.toHaveBeenCalled(); expect(api.listTelegramSupportRequests).not.toHaveBeenCalled();
    expect(api.listTelegramJobsPage).not.toHaveBeenCalled(); expect(api.getTelegramDashboard).not.toHaveBeenCalled();
    expect(api.listLifecycleSchedules).not.toHaveBeenCalled(); expect(api.listDriftFindings).not.toHaveBeenCalled();
    expect(api.getTelegramTransport).not.toHaveBeenCalled(); expect(api.getTelegramBotConfiguration).not.toHaveBeenCalled();
  });

  it('loads only the selected tab domain after explicit navigation', async () => {
    render(<TelegramAdmin />);
    await waitFor(() => expect(api.listTelegramCustomers).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.settings' }));
    await waitFor(() => expect(api.getTelegramTransport).toHaveBeenCalledTimes(1));
    expect(api.getTelegramBotConfiguration).toHaveBeenCalledTimes(1); expect(api.listTelegramRequests).not.toHaveBeenCalled(); expect(api.listTelegramJobsPage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.users' }));
    fireEvent.click(screen.getByRole('button', { name: /telegram\.requests/ }));
    await waitFor(() => expect(api.listTelegramRequests).toHaveBeenCalledTimes(1));
    expect(api.listBlockedTelegramIdentities).not.toHaveBeenCalled(); expect(api.listTelegramSupportRequests).not.toHaveBeenCalled();
  });

  it('reads each deferred tab only after its own explicit intent', async () => {
    render(<TelegramAdmin />);
    await waitFor(() => expect(api.listTelegramCustomers).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.operations' }));
    await waitFor(() => expect(api.listTelegramJobsPage).toHaveBeenCalledTimes(1));
    expect(api.getTelegramDashboard).toHaveBeenCalledTimes(1);
    expect(api.listLifecycleSchedules).toHaveBeenCalledTimes(1);
    expect(api.listDriftFindings).toHaveBeenCalledTimes(1);
    expect(api.listTelegramSupportRequests).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.users' }));
    fireEvent.click(screen.getByRole('button', { name: /telegram\.supportOpenTitle/ }));
    await waitFor(() => expect(api.listTelegramSupportRequests).toHaveBeenCalledTimes(1));
    expect(api.listBlockedTelegramIdentities).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /telegram\.blocked/ }));
    await waitFor(() => expect(api.listBlockedTelegramIdentities).toHaveBeenCalledTimes(1));
    expect(api.listTelegramAppeals).toHaveBeenCalledTimes(1);
  });

  it('shows a domain error instead of an empty successful Settings state', async () => {
    api.getTelegramTransport.mockRejectedValueOnce(new Error('unavailable'));
    render(<TelegramAdmin />);
    await waitFor(() => expect(api.listTelegramCustomers).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.settings' }));
    expect((await screen.findByRole('alert')).textContent).toContain('telegram.domainLoadFailed');
  });

  it('aborts a deferred domain read when the user leaves its tab', async () => {
    const signals: AbortSignal[] = [];
    api.getTelegramTransport.mockImplementation((signal: AbortSignal) => new Promise(() => { signals.push(signal); }));
    render(<TelegramAdmin />);
    await waitFor(() => expect(api.listTelegramCustomers).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.settings' }));
    await waitFor(() => expect(signals).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.operations' }));
    expect(signals[0].aborted).toBe(true);
  });

  it('debounces customer search, aborts the replaced request and ignores its late result', async () => {
    const calls: Array<{ query: string; signal: AbortSignal; resolve: (value: ReturnType<typeof customer>[]) => void }> = [];
    api.listTelegramCustomers.mockImplementation((query: string, _refreshToken: number | undefined, signal: AbortSignal) => new Promise((resolve) => { calls.push({ query, signal, resolve }); }));
    render(<TelegramAdmin />);
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () => { calls[0].resolve([customer('initial@example.test')]); });
    await screen.findByText('initial@example.test');
    vi.useFakeTimers();
    fireEvent.change(screen.getByPlaceholderText('common.search'), { target: { value: 'alpha' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(calls).toHaveLength(2); expect(calls[1].query).toBe('alpha');
    fireEvent.change(screen.getByPlaceholderText('common.search'), { target: { value: 'beta' } });
    expect(calls[1].signal.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(calls).toHaveLength(3); expect(calls[2].query).toBe('beta');
    await act(async () => { calls[1].resolve([customer('stale@example.test', 2)]); calls[2].resolve([customer('fresh@example.test', 3)]); });
    vi.useRealTimers();
    await screen.findByText('fresh@example.test');
    expect(screen.queryByText('stale@example.test')).toBeNull();
  });
});