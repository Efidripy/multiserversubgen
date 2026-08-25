import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const apiPut = vi.hoisted(() => vi.fn());
const apiDelete = vi.hoisted(() => vi.fn());
const listNodes = vi.hoisted(() => vi.fn());

vi.mock('../src/api', () => ({
  default: { get: apiGet, post: apiPost, put: apiPut, delete: apiDelete },
}));

vi.mock('../src/api/nodes', () => ({ listNodes }));

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn(() => Promise.resolve('data:image/png;base64,test')) },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

import { SubscriptionManager } from '../src/components/SubscriptionManager';

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  apiPost.mockReset();
  apiPut.mockReset();
  apiDelete.mockReset();
  listNodes.mockReset();
});

describe('SubscriptionManager read lifecycle', () => {
  it('passes one cancellation signal to the refresh fan-out and aborts it on unmount', async () => {
    const pending = new Promise<never>(() => {});
    apiGet.mockImplementation(() => pending);
    listNodes.mockImplementation((options: { signal?: AbortSignal }) => {
      expect(options.signal).toBeInstanceOf(AbortSignal);
      return pending;
    });

    const view = render(<SubscriptionManager apiUrl="https://example.test" />);
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2));
    expect(apiGet.mock.calls[0][1].signal).toBe(apiGet.mock.calls[1][1].signal);
    expect(listNodes).toHaveBeenCalledWith({ signal: apiGet.mock.calls[0][1].signal });

    view.unmount();
    expect(apiGet.mock.calls[0][1].signal.aborted).toBe(true);
    expect(listNodes.mock.calls[0][0].signal.aborted).toBe(true);
  });
});
