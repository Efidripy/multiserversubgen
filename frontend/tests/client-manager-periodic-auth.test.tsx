import axios from 'axios';
import fs from 'node:fs';
import path from 'node:path';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('../src/services/useTrafficStatsSubscription', () => ({
  useTrafficStatsSubscription: () => undefined,
}));

import api, { resetInFlightGetRequests } from '../src/api/client';
import { getClientPresence, listClientsBySource } from '../src/api/clients';
import { getInboundOptions } from '../src/api/inbounds';
import { listNodes, listTelegramNodePolicies } from '../src/api/nodes';
import { clearAuthCredentials, setAuthCredentials } from '../src/auth';
import { ClientManager } from '../src/components/ClientManager';
import { cacheService } from '../src/services/cacheService';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

const clientProjection = [{
  id: 'client-a',
  email: 'alice@example.test',
  enable: true,
  total: 0,
  up: 0,
  down: 0,
  expiryTime: 0,
  inbound_id: 1,
  node_name: 'edge-a',
  protocol: 'vless',
}];

const axiosResponse = (config: any, data: unknown) => ({
  data,
  status: 200,
  statusText: 'OK',
  headers: {},
  config,
});

describe('Client Manager periodic browser session auth', () => {
  beforeEach(() => {
    cacheService.invalidate();
    resetInFlightGetRequests();
    setAuthCredentials('admin', 'legacy-basic-must-not-be-replayed', '', 'ticket', 'admin');
  });

  afterEach(() => {
    cleanup();
    api.defaults.adapter = axios.defaults.adapter;
    clearAuthCredentials();
    cacheService.invalidate();
    resetInFlightGetRequests();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it('uses the HttpOnly browser session for Client Manager periodic projections', async () => {
    const requests: any[] = [];
    const controller = new AbortController();
    api.defaults.adapter = async (config: any) => {
      requests.push(config);
      return {
        data: config.url === '/v1/inbounds/options' ? { inbounds: [] } : {},
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await Promise.all([
      listNodes({ signal: controller.signal, sessionOnlyAuth: true }),
      listClientsBySource('all', { signal: controller.signal, sessionOnlyAuth: true }),
      getInboundOptions({ signal: controller.signal, sessionOnlyAuth: true }),
      getClientPresence(controller.signal, { sessionOnlyAuth: true }),
      listTelegramNodePolicies({ signal: controller.signal, sessionOnlyAuth: true }),
    ]);

    expect(requests.map((request) => request.url)).toEqual([
      '/v1/nodes',
      '/v1/clients',
      '/v1/inbounds/options',
      '/v1/clients/presence',
      '/v1/telegram/node-policies',
    ]);
    for (const request of requests) {
      expect(request.auth).toBeUndefined();
      expect(request.headers?.get?.('Authorization')).toBeUndefined();
      expect(request.withCredentials).toBe(true);
    }
  });

  it('keeps the unclassified generic node read on its existing Basic contract', async () => {
    let request: any;
    api.defaults.adapter = async (config: any) => {
      request = config;
      return { data: [], status: 200, statusText: 'OK', headers: {}, config };
    };

    await listNodes();

    expect(request.auth).toMatchObject({ username: 'admin', password: 'legacy-basic-must-not-be-replayed' });
  });

  it('binds every Client Manager periodic path to the classified session-only calls', () => {
    const source = read('src/components/ClientManager.tsx');

    expect(source).toContain('getClientPresence(signal, { sessionOnlyAuth: true })');
    expect(source).toContain('CLIENT_PRESENCE_REFRESH_MS = 30 * 1000');
    expect(source).toContain('window.setInterval(refresh, CLIENT_PRESENCE_REFRESH_MS)');
    expect(source).toContain("const [refreshInterval, setRefreshInterval] = useState<number>(_cmPrefs.refreshInterval ?? 60);");
    expect(source).toContain('if (!autoRefresh) return;');
    expect(source).toContain('setInterval(() => loadClients(true), refreshInterval * 1000)');
    expect(source).toContain('fallbackPollIntervalMs: CLIENTS_PAGE_REFRESH_MS');
    expect(source).toContain('CLIENTS_PAGE_REFRESH_MS = 5 * 60 * 1000');
    expect(source).toContain('listNodes({ signal: controller.signal, sessionOnlyAuth: true })');
    expect(source).toContain("listClientsBySource(sourceFilter, { signal: controller.signal, sessionOnlyAuth: true })");
    expect(source).toContain('const loadInboundOptionsAfterPageProjection = async () =>');
    expect(source).toContain('void loadInboundOptionsAfterPageProjection();');
    expect(source).toContain('const [nodeList, clientsPayload] = await Promise.all([');
    expect(source).not.toContain('const [nodeList, clientsPayload, inboundOptions] = await Promise.all([');
    expect(source).toContain('getInboundOptions({ signal: controller.signal, sessionOnlyAuth: true })');
  });

  it('binds the automatic Telegram policy badge read to the browser session', () => {
    const fleetPanel = read('src/components/RegisteredFleetPanel.tsx');
    const nodesApi = read('src/api/nodes.ts');

    expect(fleetPanel).toContain('listTelegramNodePolicies({\n        signal: controller.signal,\n        sessionOnlyAuth: true,\n      })');
    expect(nodesApi).toContain("...(options.sessionOnlyAuth ? { sessionOnlyAuth: true } : { auth: getAuth() })");
  });

  it('renders the client table before the independent cold inbound-options read resolves', async () => {
    const options = deferred<unknown>();
    const optionSignals: AbortSignal[] = [];
    const routes: string[] = [];
    api.defaults.adapter = async (config: any) => {
      routes.push(config.url);
      if (config.url === '/v1/nodes') return axiosResponse(config, [{ id: 1, name: 'edge-a' }]);
      if (config.url === '/v1/clients') return axiosResponse(config, clientProjection);
      if (config.url === '/v1/clients/presence') return axiosResponse(config, {});
      if (config.url === '/v1/inbounds/options') {
        optionSignals.push(config.signal);
        return options.promise.then((data) => axiosResponse(config, data));
      }
      throw new Error(`Unexpected request: ${config.url}`);
    };

    render(<ClientManager />);

    await waitFor(() => expect(screen.getAllByText('alice@example.test').length).toBeGreaterThan(0));
    await waitFor(() => expect(optionSignals).toHaveLength(1));
    expect(routes).toEqual([
      '/v1/nodes',
      '/v1/clients',
      '/v1/clients/presence',
      '/v1/inbounds/options',
    ]);
    expect(optionSignals[0].aborted).toBe(false);
    expect(screen.queryByText('clients.loadFailed')).toBeNull();

    await act(async () => {
      options.resolve({ inbounds: [] });
      await Promise.resolve();
    });
  });

  it('aborts the deferred inbound-options read when Client Manager unmounts', async () => {
    const options = deferred<unknown>();
    const optionSignals: AbortSignal[] = [];
    api.defaults.adapter = async (config: any) => {
      if (config.url === '/v1/nodes') return axiosResponse(config, [{ id: 1, name: 'edge-a' }]);
      if (config.url === '/v1/clients') return axiosResponse(config, clientProjection);
      if (config.url === '/v1/clients/presence') return axiosResponse(config, {});
      if (config.url === '/v1/inbounds/options') {
        optionSignals.push(config.signal);
        return options.promise.then((data) => axiosResponse(config, data));
      }
      throw new Error(`Unexpected request: ${config.url}`);
    };

    const view = render(<ClientManager />);
    await waitFor(() => expect(optionSignals).toHaveLength(1));

    view.unmount();
    expect(optionSignals[0].aborted).toBe(true);
  });

  it('aborts an older options read and rejects its stale result after a second projection', async () => {
    const options = [deferred<unknown>(), deferred<unknown>()];
    const optionSignals: AbortSignal[] = [];
    api.defaults.adapter = async (config: any) => {
      if (config.url === '/v1/nodes') return axiosResponse(config, [{ id: 1, name: 'edge-a' }]);
      if (config.url === '/v1/clients') return axiosResponse(config, clientProjection);
      if (config.url === '/v1/clients/presence') return axiosResponse(config, {});
      if (config.url === '/v1/inbounds/options') {
        const call = options[optionSignals.length];
        optionSignals.push(config.signal);
        return call.promise.then((data) => axiosResponse(config, data));
      }
      throw new Error(`Unexpected request: ${config.url}`);
    };

    render(<ClientManager />);
    await waitFor(() => expect(optionSignals).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: 'common.refresh' }));
    await waitFor(() => expect(optionSignals).toHaveLength(2));
    expect(optionSignals[0].aborted).toBe(true);

    await act(async () => {
      options[1].resolve({
        inbounds: [{ id: 22, node_id: 1, node_name: 'edge-a', protocol: 'vless', remark: 'fresh-option' }],
      });
      await Promise.resolve();
    });
    await act(async () => {
      options[0].resolve({
        inbounds: [{ id: 11, node_id: 1, node_name: 'edge-a', protocol: 'vless', remark: 'stale-option' }],
      });
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole('button', { name: 'clients.batchAdd' }));
    await waitFor(() => expect(screen.getAllByText(/fresh-option/).length).toBeGreaterThan(0));
    expect(screen.queryByText(/stale-option/)).toBeNull();
  });

  it('keeps a successful client table visible when deferred inbound options fail', async () => {
    let optionCalls = 0;
    api.defaults.adapter = async (config: any) => {
      if (config.url === '/v1/nodes') return axiosResponse(config, [{ id: 1, name: 'edge-a' }]);
      if (config.url === '/v1/clients') return axiosResponse(config, clientProjection);
      if (config.url === '/v1/clients/presence') return axiosResponse(config, {});
      if (config.url === '/v1/inbounds/options') {
        optionCalls += 1;
        throw new Error('picker unavailable');
      }
      throw new Error(`Unexpected request: ${config.url}`);
    };

    render(<ClientManager />);

    await waitFor(() => expect(screen.getAllByText('alice@example.test').length).toBeGreaterThan(0));
    await waitFor(() => expect(optionCalls).toBe(1));
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText('clients.loadFailed')).toBeNull());
    expect(screen.getAllByText('alice@example.test').length).toBeGreaterThan(0);
  });
});
