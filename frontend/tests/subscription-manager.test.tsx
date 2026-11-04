import { cleanup, render, waitFor, fireEvent, screen } from '@testing-library/react';
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

  it('opens per-client settings in a second tab and keeps them loaded', async () => {
    localStorage.removeItem('sub_manager_subscriptions_tab_v1');
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/emails') return Promise.resolve({ data: { emails: [], stats: {} } });
      if (path === '/v1/subscription-client-settings') {
        return Promise.resolve({ data: { settings: { profile: {}, clients: [] }, schema: {}, formats: ['base64'] } });
      }
      return Promise.resolve({ data: { groups: [] } });
    });
    listNodes.mockResolvedValue([]);
    const settingsReads = () => apiGet.mock.calls.filter(([path]) => path === '/v1/subscription-client-settings');

    const { container } = render(<SubscriptionManager apiUrl="https://example.test" />);
    const tab = (id: string) => container.querySelector(`#subscriptions-tab-${id}`) as HTMLButtonElement;
    await waitFor(() => expect(apiGet.mock.calls.some(([path]) => path === '/v1/emails')).toBe(true));
    expect(settingsReads()).toHaveLength(0);

    fireEvent.click(tab('settings'));
    await waitFor(() => expect(settingsReads()).toHaveLength(1));
    expect(tab('settings').getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(tab('links'));
    fireEvent.click(tab('settings'));
    expect(settingsReads()).toHaveLength(1);
    localStorage.removeItem('sub_manager_subscriptions_tab_v1');
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

  it('в разделе есть вкладка проверки User-Agent и в ней работает запрос', async () => {
    localStorage.removeItem('sub_manager_subscriptions_tab_v1');
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/emails') return Promise.resolve({ data: { emails: [], stats: {} } });
      return Promise.resolve({ data: { groups: [] } });
    });
    listNodes.mockResolvedValue([]);
    apiPost.mockResolvedValueOnce({
      data: {
        matched: true,
        client_id: 'happ',
        name: 'Happ',
        format: 'base64',
        headers: {
          'Routing-Enable': 'true',
        },
      },
    });

    const { container } = render(<SubscriptionManager apiUrl="https://example.test" />);
    const tab = (id: string) => container.querySelector(`#subscriptions-tab-${id}`) as HTMLButtonElement;

    expect(tab('uaTest')).toBeTruthy();
    expect(tab('uaTest').textContent).toContain('subscriptions.tabs.uaTest');

    // Click uaTest tab
    fireEvent.click(tab('uaTest'));
    expect(tab('uaTest').getAttribute('aria-pressed')).toBe('true');
    expect(localStorage.getItem('sub_manager_subscriptions_tab_v1')).toBe('uaTest');

    const uaInput = screen.getByPlaceholderText('subscriptionClients.test.userAgentPlaceholder');
    fireEvent.change(uaInput, { target: { value: 'Happ/1.2.3' } });

    const testBtn = screen.getByRole('button', { name: 'subscriptionClients.test.testButton' });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/v1/subscription-client-settings/test', {
        user_agent: 'Happ/1.2.3',
      });
    });

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.test.resultTitle')).toBeTruthy();
    });
    expect(screen.getByText('Happ')).toBeTruthy();
    expect(screen.getByText('base64')).toBeTruthy();

    // Switch to links and back to uaTest; result stays visible
    fireEvent.click(tab('links'));
    expect(tab('links').getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(tab('uaTest'));
    expect(screen.getByText('subscriptionClients.test.resultTitle')).toBeTruthy();

    localStorage.removeItem('sub_manager_subscriptions_tab_v1');
  });

  it('readSubscriptionTab восстанавливает вкладку uaTest', async () => {
    localStorage.setItem('sub_manager_subscriptions_tab_v1', 'uaTest');
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/emails') return Promise.resolve({ data: { emails: [], stats: {} } });
      return Promise.resolve({ data: { groups: [] } });
    });
    listNodes.mockResolvedValue([]);

    const { container } = render(<SubscriptionManager apiUrl="https://example.test" />);
    const tab = (id: string) => container.querySelector(`#subscriptions-tab-${id}`) as HTMLButtonElement;

    expect(tab('uaTest').getAttribute('aria-pressed')).toBe('true');
    localStorage.removeItem('sub_manager_subscriptions_tab_v1');
  });
});
