import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { ActivityLogPanel } from '../src/components/ActivityLogPanel';

afterEach(cleanup);

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
});
