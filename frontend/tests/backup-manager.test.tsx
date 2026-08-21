import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  downloadAllBackups: vi.fn(),
  downloadNodeBackup: vi.fn(),
  importNodeBackup: vi.fn(),
  listNodes: vi.fn(),
  sendNodeBackupToTelegram: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key }),
}));

vi.mock('../src/api/backup', () => ({
  downloadAllBackups: mocks.downloadAllBackups,
  downloadNodeBackup: mocks.downloadNodeBackup,
  importNodeBackup: mocks.importNodeBackup,
  sendNodeBackupToTelegram: mocks.sendNodeBackupToTelegram,
}));

vi.mock('../src/api/nodes', () => ({
  listNodes: mocks.listNodes,
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: mocks.toast }),
}));

vi.mock('../src/components/UIIcon', () => ({
  UIIcon: () => null,
}));

vi.mock('../src/components/ChoiceChips', () => ({
  ChoiceChips: () => null,
}));

import { BackupManager } from '../src/components/BackupManager';

describe('BackupManager cold path', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it('loads node metadata on mount without fetching full backup bodies', async () => {
    mocks.listNodes.mockResolvedValue([
      { id: 1, name: 'alpha', ip: '203.0.113.1', port: '443' },
    ]);

    render(<BackupManager />);

    await waitFor(() => expect(screen.getAllByText('alpha').length).toBeGreaterThan(0));

    expect(mocks.listNodes).toHaveBeenCalledTimes(1);
    expect(mocks.downloadAllBackups).not.toHaveBeenCalled();
    expect(mocks.downloadNodeBackup).not.toHaveBeenCalled();
    expect(mocks.sendNodeBackupToTelegram).not.toHaveBeenCalled();
  });

  it('fetches a full backup only after the explicit node download action', async () => {
    mocks.listNodes.mockResolvedValue([
      { id: 1, name: 'alpha', ip: '203.0.113.1', port: '443' },
    ]);
    mocks.downloadNodeBackup.mockResolvedValue(new Blob(['sqlite-backup']));
    const createObjectUrl = vi.fn(() => 'blob:test-backup');
    const revokeObjectUrl = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    Object.defineProperty(window.URL, 'createObjectURL', { configurable: true, value: createObjectUrl });
    Object.defineProperty(window.URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl });

    render(<BackupManager />);

    await waitFor(() => expect(screen.getAllByText('alpha').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByLabelText('backup.download')[0]);

    await waitFor(() => expect(mocks.downloadNodeBackup).toHaveBeenCalledWith(1));
    expect(mocks.downloadAllBackups).not.toHaveBeenCalled();
    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:test-backup');
    expect(click).toHaveBeenCalledTimes(1);
  });

  it('reports only explicit Telegram successes as sent', async () => {
    mocks.listNodes.mockResolvedValue([
      { id: 1, name: 'alpha', ip: '203.0.113.1', port: '443' },
      { id: 2, name: 'beta', ip: '203.0.113.2', port: '443' },
    ]);
    mocks.sendNodeBackupToTelegram
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({ error: 'panel unavailable' });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<BackupManager />);

    await waitFor(() => expect(screen.getAllByText('alpha').length).toBeGreaterThan(0));
    fireEvent.click(screen.getByText('backup.telegramAll'));

    await waitFor(() => expect(mocks.sendNodeBackupToTelegram).toHaveBeenCalledTimes(2));
    expect(mocks.toast).toHaveBeenCalledWith('backup.telegramAllResult', 'success');
  });
});
