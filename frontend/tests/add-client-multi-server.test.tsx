import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());

vi.mock('../src/api', () => ({
  default: { get: apiGet, post: apiPost },
}));

vi.mock('../src/auth', () => ({
  getAuth: () => ({ username: 'test', password: 'test' }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { AddClientMultiServer } from '../src/components/AddClientMultiServer';

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  apiPost.mockReset();
});

describe('AddClientMultiServer node loading', () => {
  it('passes a cancellation signal and aborts the node-list read on unmount', async () => {
    const pending = new Promise<never>(() => {});
    apiGet.mockReturnValue(pending);

    const view = render(<AddClientMultiServer />);
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith(
      '/v1/nodes/list',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ));
    const signal = apiGet.mock.calls[0][1].signal as AbortSignal;

    view.unmount();
    expect(signal.aborted).toBe(true);
  });
});
