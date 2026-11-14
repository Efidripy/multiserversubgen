import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ru from '../src/i18n/locales/ru.json';

const api = vi.hoisted(() => ({
  listTelegramCustomers: vi.fn(), listTelegramJobsPage: vi.fn(), getCustomerNodes: vi.fn(),
  getCustomerOperations: vi.fn(), getCustomerTraffic: vi.fn(), getCustomerTags: vi.fn(),
  getCustomerTimeline: vi.fn(), repairCustomer: vi.fn(), getTelegramAttention: vi.fn(), getTelegramHistoryOverview: vi.fn(),
  getTelegramDashboard: vi.fn(), listLifecycleSchedules: vi.fn(), listDriftFindings: vi.fn(),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, values: Record<string, string> = {}) => {
  const value = key.split('.').reduce<unknown>((current, part) => (current as Record<string, unknown>)?.[part], ru);
  return typeof value === 'string' ? value.replace(/{{(\w+)}}/g, (_, name: string) => String(values[name] ?? '')) : key;
} }) }));
vi.mock('../src/components/Toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('../src/api/telegram', async (importOriginal) => ({ ...(await importOriginal<typeof import('../src/api/telegram')>()), ...api }));
import { TelegramAdmin } from '../src/components/TelegramAdmin';

const customer = { customer_id: 1, email_display: 'customer@example.test', status: 'active', node_count: 0, nodes_active: 0, nodes_suspended: 0, nodes_available: 0, nodes_problem: 0, telegram_user_id: null, telegram_username: null, telegram_first_name: null, telegram_last_name: null, lifetime_bytes: null, traffic_observed_at: null, application_introduction: null };

beforeEach(() => {
  localStorage.clear();
  api.listTelegramCustomers.mockResolvedValue([customer]);
  api.listTelegramJobsPage.mockResolvedValue({ items: [], total: 0, can_clear_history: false });
  api.getCustomerNodes.mockResolvedValue([]); api.getCustomerOperations.mockResolvedValue([]);
  api.getCustomerTraffic.mockResolvedValue(null); api.getCustomerTags.mockResolvedValue([]); api.getCustomerTimeline.mockResolvedValue([]);
  api.getTelegramDashboard.mockResolvedValue({}); api.listLifecycleSchedules.mockResolvedValue([]); api.listDriftFindings.mockResolvedValue([]);
  api.getTelegramAttention.mockResolvedValue({ provisioning: [], lifecycle: [] });
  api.getTelegramHistoryOverview.mockResolvedValue(null);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('TelegramAdmin repair and attention', () => {
  it('repairs a customer and displays the fixed item and remaining problems', async () => {
    api.repairCustomer.mockResolvedValue({ fixed: ['remote_snapshot_ready'], problems: [{ code: 'binding_missing', node_name: 'Test node' }, { code: 'identity_not_approved' }] });
    render(<TelegramAdmin />);
    fireEvent.click((await screen.findAllByText('customer@example.test'))[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'Починить' }));
    await waitFor(() => expect(api.repairCustomer).toHaveBeenCalledWith(1));
    expect(await screen.findByText('Первичная настройка отмечена завершённой')).toBeTruthy();
    expect(screen.getByText('На ноде Test node клиента нет на панели — добавьте его заново или запустите сверку.')).toBeTruthy();
    expect(screen.getByText('Заявка не одобрена — проверьте её в админке.')).toBeTruthy();
  });

  it('shows the error summary or falls back to the error code for both kinds of attempts', async () => {
    const attempts = [{ node_name: 'Node A', status: 'failed', error_code: 'hidden_code', error_summary: 'Понятная причина' }, { node_name: 'Node B', status: 'failed', error_code: 'visible_code', error_summary: '' }];
    api.getTelegramAttention.mockResolvedValue({ provisioning: [{ job_id: 1, customer_email: 'job@example.test', trigger: 'initial', status: 'failed', attempts }], lifecycle: [{ operation_id: 2, customer_email: 'operation@example.test', operation_type: 'suspend', status: 'failed', attempts }] });
    render(<TelegramAdmin />);
    fireEvent.click(screen.getByRole('button', { name: ru.telegram.tabs.operations }));
    await waitFor(() => expect(screen.getAllByText(/Node A: Понятная причина, Node B: visible_code/)).toHaveLength(2));
    expect(screen.queryByText(/hidden_code/)).toBeNull();
  });
});
