import { StrictMode } from 'react';
import { cleanup, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { usePullToRefresh } from '../src/hooks/usePullToRefresh';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

function PullProbe({ onRefresh, scrollTop = 0, enabled = true, children }: {
  onRefresh: () => Promise<void>;
  scrollTop?: number;
  enabled?: boolean;
  children?: React.ReactNode;
}) {
  const pull = usePullToRefresh({ onRefresh, enabled, getScrollTop: () => scrollTop });
  return (
    <div ref={pull.rootRef} data-testid="primary-scroll" {...pull.handlers}>
      <output data-testid="state">{pull.state}:{Math.round(pull.pullDistance)}</output>
      {children}
    </div>
  );
}

const touch = (target: HTMLElement, type: 'touchStart' | 'touchMove' | 'touchEnd' | 'touchCancel', clientY = 0, clientX = 0) => {
  if (type === 'touchEnd' || type === 'touchCancel') {
    fireEvent[type](target, { touches: [] });
    return;
  }
  fireEvent[type](target, { touches: [{ clientX, clientY }] });
};

const multiTouchMove = (target: HTMLElement) => {
  fireEvent.touchMove(target, { touches: [{ clientX: 0, clientY: 80 }, { clientX: 8, clientY: 84 }] });
};

const multiTouchStart = (target: HTMLElement) => {
  fireEvent.touchStart(target, { touches: [{ clientX: 0, clientY: 0 }, { clientX: 8, clientY: 4 }] });
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('primary-scroll pull to refresh', () => {
  it('only arms from the top of the primary scroll and preserves an in-page scroll gesture', () => {
    const refresh = vi.fn(async () => undefined);
    const { rerender } = render(<PullProbe onRefresh={refresh} scrollTop={12} />);
    const scroll = screen.getByTestId('primary-scroll');
    touch(scroll, 'touchStart', 0);
    touch(scroll, 'touchMove', 100);
    touch(scroll, 'touchEnd');
    expect(screen.getByTestId('state').textContent).toBe('idle:0');
    expect(refresh).not.toHaveBeenCalled();

    rerender(<PullProbe onRefresh={refresh} scrollTop={0} />);
    touch(scroll, 'touchStart', 0);
    touch(scroll, 'touchMove', 48);
    expect(screen.getByTestId('state').textContent).toBe('pulling:48');
    touch(scroll, 'touchEnd');
    expect(refresh).not.toHaveBeenCalled();
  });

  it('refreshes once after the threshold and keeps the pending state until the active view accepts it', async () => {
    const pending = deferred();
    const refresh = vi.fn(() => pending.promise);
    render(<PullProbe onRefresh={refresh} />);
    const scroll = screen.getByTestId('primary-scroll');

    touch(scroll, 'touchStart', 0);
    touch(scroll, 'touchMove', 80);
    expect(screen.getByTestId('state').textContent).toBe('armed:80');
    touch(scroll, 'touchEnd');
    touch(scroll, 'touchEnd');

    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('state').textContent).toBe('refreshing:72');
    pending.resolve();
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('idle:0'));
  });

  it('cancels a sideways or cancelled gesture without issuing a refresh', () => {
    const refresh = vi.fn(async () => undefined);
    render(<PullProbe onRefresh={refresh} />);
    const scroll = screen.getByTestId('primary-scroll');
    touch(scroll, 'touchStart', 0, 0);
    touch(scroll, 'touchMove', 24, 48);
    expect(screen.getByTestId('state').textContent).toBe('idle:0');
    touch(scroll, 'touchEnd');
    expect(refresh).not.toHaveBeenCalled();

    touch(scroll, 'touchStart', 0);
    touch(scroll, 'touchMove', 80);
    touch(scroll, 'touchCancel');
    expect(screen.getByTestId('state').textContent).toBe('idle:0');
  });

  it('restores its mounted guard after StrictMode cleanup and ignores a multi-touch gesture', async () => {
    const refresh = vi.fn(async () => undefined);
    render(<StrictMode><PullProbe onRefresh={refresh} /></StrictMode>);
    const scroll = screen.getByTestId('primary-scroll');

    touch(scroll, 'touchStart', 0);
    multiTouchStart(scroll);
    multiTouchMove(scroll);
    touch(scroll, 'touchEnd');
    expect(refresh).not.toHaveBeenCalled();

    touch(scroll, 'touchStart', 0);
    touch(scroll, 'touchMove', 80);
    touch(scroll, 'touchEnd');
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it('allows a Dashboard button pull but leaves form controls, dialogs and nested scroll containers to their owners', async () => {
    const refresh = vi.fn(async () => undefined);
    render(
      <PullProbe onRefresh={refresh}>
        <button type="button">Control</button>
        <input aria-label="Form field" />
        <div role="dialog"><div data-testid="dialog-content">Dialog</div></div>
        <div data-testid="nested-scroll" style={{ overflowY: 'auto' }}><span>Nested</span></div>
      </PullProbe>,
    );
    const scroll = screen.getByTestId('primary-scroll');
    const button = screen.getByRole('button', { name: 'Control' });
    touch(button, 'touchStart', 0);
    touch(button, 'touchMove', 80);
    touch(button, 'touchEnd');
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));

    const attempts = [
      screen.getByRole('textbox', { name: 'Form field' }),
      screen.getByTestId('dialog-content'),
      screen.getByTestId('nested-scroll'),
    ];

    attempts.forEach((target) => {
      touch(target, 'touchStart', 0);
      touch(target, 'touchMove', 80);
      touch(target, 'touchEnd');
    });
    expect(screen.getByTestId('state').textContent).toBe('idle:0');
    expect(refresh).toHaveBeenCalledTimes(1);

    const move = createEvent.touchMove(scroll, { touches: [{ clientX: 0, clientY: 80 }], cancelable: true });
    touch(scroll, 'touchStart', 0);
    expect(fireEvent(scroll, move)).toBe(false);
  });
});
