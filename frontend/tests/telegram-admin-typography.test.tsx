import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  translate: (key: string) => key,
  toast: vi.fn(),
}));

const api = vi.hoisted(() => ({
  getTelegramBotConfiguration: vi.fn(),
  getTelegramDashboard: vi.fn(),
  getTelegramTransport: vi.fn(),
  listBlockedTelegramIdentities: vi.fn(),
  listDriftFindings: vi.fn(),
  listLifecycleSchedules: vi.fn(),
  listTelegramAppeals: vi.fn(),
  listTelegramCustomers: vi.fn(),
  listTelegramJobsPage: vi.fn(),
  listTelegramRequests: vi.fn(),
  listTelegramSupportRequests: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mocks.translate }),
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: mocks.toast }),
}));

vi.mock('../src/api/telegram', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api/telegram')>()),
  ...api,
}));

import { TelegramAdmin } from '../src/components/TelegramAdmin';

const directTransport = {
  mode: 'direct' as const,
  row_version: 1,
  configured: true,
  reachable: true,
  proxy_host: null,
  proxy_port: null,
  updated_by: 'test',
  updated_at: '2026-10-18 00:00:00',
};

const botConfiguration = {
  configured: false,
  token_suffix: null,
  row_version: 1,
  updated_by: 'test',
  updated_at: '2026-10-18 00:00:00',
  source: 'none' as const,
};

beforeEach(() => {
  localStorage.clear();
  api.listTelegramRequests.mockResolvedValue([]);
  api.listTelegramCustomers.mockResolvedValue([]);
  api.listBlockedTelegramIdentities.mockResolvedValue([]);
  api.getTelegramTransport.mockResolvedValue(directTransport);
  api.getTelegramBotConfiguration.mockResolvedValue(botConfiguration);
  api.listTelegramJobsPage.mockResolvedValue({ items: [], total: 0, can_clear_history: false });
  api.listTelegramAppeals.mockResolvedValue([]);
  api.listTelegramSupportRequests.mockResolvedValue([]);
  api.getTelegramDashboard.mockResolvedValue({
    pending_requests: 0,
    active_customers: 0,
    suspended_customers: 0,
    lifecycle_attention: 0,
    provisioning_attention: 0,
    open_appeals: 0,
    open_support_requests: 0,
    open_drift_findings: 0,
    scheduled_lifecycle_actions: 0,
  });
  api.listLifecycleSchedules.mockResolvedValue([]);
  api.listDriftFindings.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('TelegramAdmin typography +4 px', () => {
  it('renders scoped +4 typography for the section heading, tabs, controls and settings input', async () => {
    render(<TelegramAdmin />);

    await waitFor(() => expect(api.listTelegramRequests).toHaveBeenCalledTimes(1));
    const root = screen.getByTestId('telegram-admin');
    expect(root).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'telegram.tabs.users' }).className).toContain('text-[24px]');
    expect(screen.getByRole('button', { name: 'telegram.tabs.users' }).className).toContain('text-[16px]');
    expect(screen.getByRole('button', { name: 'common.refresh' }).className).toContain('text-[15px]');
    expect(screen.getByRole('button', { name: 'common.refresh' }).className).toContain('h-9');

    fireEvent.click(screen.getByRole('button', { name: 'telegram.tabs.settings' }));

    const tokenInput = await screen.findByLabelText('telegram.botTokenInputLabel');
    expect(tokenInput.className).toContain('text-[16px]');
    expect(screen.getByText('telegram.botTokenTitle').className).toContain('text-[16px]');
  });

  it('keeps the enlarged metric cards content-led instead of clipping it at the former fixed height', async () => {
    render(<TelegramAdmin />);

    await waitFor(() => expect(api.listTelegramRequests).toHaveBeenCalledTimes(1));
    const metric = screen.getByRole('button', { name: /telegram\.customers/ });
    expect(metric.className).toContain('min-h-[66px]');
    expect(metric.className).not.toContain('h-[58px]');
    expect(metric.querySelector('.text-\\[19px\\]')).toBeTruthy();
    expect(metric.querySelector('.text-\\[13px\\]')).toBeTruthy();
  });
});