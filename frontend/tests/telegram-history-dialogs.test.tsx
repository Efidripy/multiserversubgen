import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ru from '../src/i18n/locales/ru.json';

const api = vi.hoisted(() => ({
  listTelegramHistoryOperations: vi.fn(), listTelegramHistoryBindings: vi.fn(), listTelegramMissingBindingNodes: vi.fn(),
  getTelegramHistoryClearCount: vi.fn(), clearTelegramOperationHistory: vi.fn(), forgetTelegramMissingBindings: vi.fn(),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, values: Record<string, string> = {}) => {
  const value = key.split('.').reduce<unknown>((current, part) => (current as Record<string, unknown>)?.[part], ru);
  return typeof value === 'string' ? value.replace(/{{(\w+)}}/g, (_, name: string) => String(values[name] ?? '')) : key;
} }) }));
vi.mock('../src/components/Toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('../src/api/telegram', async (importOriginal) => ({ ...(await importOriginal<typeof import('../src/api/telegram')>()), ...api }));
import { TelegramHistoryDialogs } from '../src/components/TelegramHistoryDialogs';
import type { TelegramHistoryOverview } from '../src/api/telegram';

const overview = (canClear: boolean): TelegramHistoryOverview => ({
  jobs: { total: 1, terminal: 1 }, operations: { total: 2, terminal: 1, needs_attention: 0 },
  drift: { open: 0, ignored: 0, resolved: 0, adopted: 0 }, missing_bindings: { missing: 1, conflict: 0 },
  audit: { total: 3 }, can_clear: canClear,
});

const renderDialogs = (canClear: boolean) => render(
  <TelegramHistoryDialogs overview={overview(canClear)} canClear={false} mutating={false} setMutating={vi.fn()} onChanged={async () => undefined} />,
);

afterEach(cleanup);

describe('TelegramHistoryDialogs clear actions', () => {
  it('enables the clear and forget buttons when the overview allows clearing', async () => {
    api.listTelegramHistoryOperations.mockResolvedValue({ items: [], total: 0 });
    api.listTelegramHistoryBindings.mockResolvedValue({ items: [], total: 0 });
    api.listTelegramMissingBindingNodes.mockResolvedValue([]);
    renderDialogs(true);
    fireEvent.click(screen.getByRole('button', { name: new RegExp(ru.telegram.historyOperations) }));
    const clear = await screen.findByRole('button', { name: ru.telegram.historyClear });
    await waitFor(() => expect((clear as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: ru.telegram.historyClose }));
    fireEvent.click(screen.getByRole('button', { name: new RegExp(ru.telegram.historyMissing) }));
    const forget = await screen.findByRole('button', { name: ru.telegram.historyForget });
    await waitFor(() => expect((forget as HTMLButtonElement).disabled).toBe(false));
  });

  it('keeps the buttons disabled when the overview forbids clearing', async () => {
    api.listTelegramHistoryOperations.mockResolvedValue({ items: [], total: 0 });
    renderDialogs(false);
    fireEvent.click(screen.getByRole('button', { name: new RegExp(ru.telegram.historyOperations) }));
    const clear = await screen.findByRole('button', { name: ru.telegram.historyClear });
    expect((clear as HTMLButtonElement).disabled).toBe(true);
  });

  it('clears operations through the confirmation dialog and refreshes', async () => {
    api.listTelegramHistoryOperations.mockResolvedValue({ items: [], total: 0 });
    api.getTelegramHistoryClearCount.mockResolvedValue(3);
    api.clearTelegramOperationHistory.mockResolvedValue(3);
    const onChanged = vi.fn(async () => undefined);
    render(<TelegramHistoryDialogs overview={overview(true)} canClear={false} mutating={false} setMutating={vi.fn()} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole('button', { name: new RegExp(ru.telegram.historyOperations) }));
    fireEvent.click(await screen.findByRole('button', { name: ru.telegram.historyClear }));
    await screen.findByText(ru.telegram.historyClearConfirm.replace('{{count}}', '3'));
    fireEvent.click(screen.getByRole('button', { name: ru.common.confirm }));
    await waitFor(() => expect(api.clearTelegramOperationHistory).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('forgets missing bindings through the confirmation dialog', async () => {
    api.listTelegramHistoryBindings.mockResolvedValue({ items: [], total: 0 });
    api.listTelegramMissingBindingNodes.mockResolvedValue([]);
    api.getTelegramHistoryClearCount.mockResolvedValue(35);
    api.forgetTelegramMissingBindings.mockResolvedValue({ deleted_count: 35 });
    render(<TelegramHistoryDialogs overview={overview(true)} canClear={false} mutating={false} setMutating={vi.fn()} onChanged={async () => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: new RegExp(ru.telegram.historyMissing) }));
    fireEvent.click(await screen.findByRole('button', { name: ru.telegram.historyForget }));
    await screen.findByText(ru.telegram.historyForgetConfirm.replace('{{count}}', '35'));
    fireEvent.click(screen.getByRole('button', { name: ru.common.confirm }));
    await waitFor(() => expect(api.forgetTelegramMissingBindings).toHaveBeenCalledTimes(1));
  });
});
