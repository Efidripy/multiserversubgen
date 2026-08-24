import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'ru' } }),
}));

import { ActivityLogPanel } from '../src/components/ActivityLogPanel';
import { activityLog } from '../src/services/activityLog';

afterEach(() => {
  cleanup();
  activityLog.clear();
  vi.restoreAllMocks();
});

describe('ActivityLogPanel viewport and resize contract', () => {
  it('keeps a bounded, resizable dialog and a shrinkable filter control', () => {
    render(<ActivityLogPanel open onClose={vi.fn()} />);

    const dialog = screen.getByRole('dialog');
    expect(dialog.style.right).toBe('8px');
    expect(dialog.style.bottom).toBe('8px');
    expect(dialog.style.resize).toBe('both');
    expect(dialog.style.overflow).toBe('hidden');
    expect(dialog.style.maxWidth).toBe('calc(100vw - 16px)');
    expect(dialog.style.maxHeight).toBe('calc(100dvh - 16px)');

    const filter = screen.getByPlaceholderText('filter...');
    expect(filter.style.minWidth).toBe('0');
    expect(filter.style.flex).toBe('1 1 160px');
  });

  it('closes with Escape and does not render while closed', () => {
    const onClose = vi.fn();
    const { rerender } = render(<ActivityLogPanel open onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<ActivityLogPanel open={false} onClose={onClose} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('subscribes only while open and snapshots entries when it opens', () => {
    const subscribe = vi.spyOn(activityLog, 'subscribe');
    const { rerender } = render(<ActivityLogPanel open={false} onClose={vi.fn()} />);
    expect(subscribe).not.toHaveBeenCalled();

    activityLog.info('Hidden', 'kept in ring buffer');
    rerender(<ActivityLogPanel open onClose={vi.fn()} />);

    expect(subscribe).toHaveBeenCalledTimes(1);
    expect(screen.getByText('kept in ring buffer')).toBeTruthy();

    rerender(<ActivityLogPanel open={false} onClose={vi.fn()} />);
    activityLog.info('Hidden', 'must not trigger a hidden render');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('keeps automatic scrolling inside the log list', async () => {
    const requestAnimationFrame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callback(1);
      return 1;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);

    render(<ActivityLogPanel open onClose={vi.fn()} />);
    const list = screen.getByTestId('activity-log-entries');
    Object.defineProperty(list, 'scrollHeight', { configurable: true, value: 420 });

    activityLog.info('Panel', 'scroll locally');

    await waitFor(() => {
      expect(requestAnimationFrame).toHaveBeenCalled();
      expect(list.scrollTop).toBe(420);
    });
  });
});
