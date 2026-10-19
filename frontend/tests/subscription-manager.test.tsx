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

  it('owns the initial email and node reads once, then publishes the header only after both are authoritative', async () => {
    let resolveEmails: ((value: any) => void) | undefined;
    let resolveNodes: ((value: any) => void) | undefined;
    const emails = new Promise((resolve) => { resolveEmails = resolve; });
    const nodes = new Promise((resolve) => { resolveNodes = resolve; });
    const onHeaderProjectionChange = vi.fn();

    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/emails') return emails;
      return Promise.resolve({ data: { groups: [] } });
    });
    listNodes.mockReturnValue(nodes);

    render(<SubscriptionManager apiUrl="https://example.test" onHeaderProjectionChange={onHeaderProjectionChange} />);

    await waitFor(() => expect(apiGet.mock.calls.filter(([path]) => path === '/v1/emails')).toHaveLength(1));
    expect(listNodes).toHaveBeenCalledTimes(1);
    expect(onHeaderProjectionChange).not.toHaveBeenCalled();

    resolveEmails?.({ data: { emails: ['owner@example.test'], stats: { 'owner@example.test': { count: 0, last: '' } } } });
    await Promise.resolve();
    expect(onHeaderProjectionChange).not.toHaveBeenCalled();

    resolveNodes?.([{ id: 1, name: 'node-a' }]);
    await waitFor(() => expect(onHeaderProjectionChange).toHaveBeenCalledWith({
      emails: ['owner@example.test'],
      stats: { 'owner@example.test': { count: 0, last: '' } },
      nodes: [{ id: 1, name: 'node-a' }],
    }));
  });

  it('does not publish a stale header projection after the route unmounts', async () => {
    let resolveEmails: ((value: any) => void) | undefined;
    let resolveNodes: ((value: any) => void) | undefined;
    const onHeaderProjectionChange = vi.fn();
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/emails') return new Promise((resolve) => { resolveEmails = resolve; });
      return Promise.resolve({ data: { groups: [] } });
    });
    listNodes.mockImplementation(() => new Promise((resolve) => { resolveNodes = resolve; }));

    const view = render(<SubscriptionManager apiUrl="https://example.test" onHeaderProjectionChange={onHeaderProjectionChange} />);
    await waitFor(() => expect(listNodes).toHaveBeenCalledTimes(1));
    view.unmount();

    resolveEmails?.({ data: { emails: ['stale@example.test'], stats: {} } });
    resolveNodes?.([{ id: 1, name: 'node-a' }]);
    await Promise.resolve();
    await Promise.resolve();

    expect(onHeaderProjectionChange).not.toHaveBeenCalled();
  });
});
