import fs from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const apiDelete = vi.hoisted(() => vi.fn());
const listNodes = vi.hoisted(() => vi.fn());
const getInboundsHeaderSource = vi.hoisted(() => vi.fn());

vi.mock('../src/api', () => ({
  default: { get: apiGet, post: apiPost, delete: apiDelete },
}));

vi.mock('../src/api/nodes', () => ({ listNodes }));

vi.mock('../src/api/dashboard', () => ({ getInboundsHeaderSource }));

vi.mock('../src/auth', () => ({
  getAuth: () => ({ username: 'test', password: 'test', role: 'admin' }),
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('../src/services/useTrafficStatsSubscription', () => ({
  useTrafficStatsSubscription: () => undefined,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { InboundManager } from '../src/components/InboundManager';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  localStorage.clear();
  apiGet.mockReset();
  apiPost.mockReset();
  apiDelete.mockReset();
  listNodes.mockReset();
  getInboundsHeaderSource.mockReset();
  vi.useRealTimers();
});

describe('client and inbound projection lifecycle contract', () => {
  it('hydrates browser snapshots before issuing a non-blocking reconciliation read', () => {
    const clients = read('src/components/ClientManager.tsx');
    const inbounds = read('src/components/InboundManager.tsx');

    expect(clients).toContain('readStaleCache<ClientsPageCache>(CLIENTS_PAGE_CACHE_KEY, Number.MAX_SAFE_INTEGER)');
    expect(clients).toContain('void loadClients(Boolean(cached.data?.clients?.length));');
    expect(inbounds).toContain('readStaleCache<InboundsPageCache>(INBOUNDS_PAGE_CACHE_KEY, Number.MAX_SAFE_INTEGER)');
    expect(inbounds).toContain('void loadInbounds(Boolean(cached.data?.inbounds?.length));');
  });

  it('does not overwrite an inbound snapshot during initial hydration and retains its aggregate stats', () => {
    const inbounds = read('src/components/InboundManager.tsx');

    expect(inbounds).toContain('const [cacheHydrated, setCacheHydrated] = useState(false);');
    expect(inbounds).toContain('if (!cacheHydrated) return;');
    expect(inbounds).toContain('inboundStats?: InboundStats | null;');
    expect(inbounds).toContain('inboundStats,');
  });

  it('uses a session-only node read in the classified Inbounds read-set', () => {
    expect(read('src/components/InboundManager.tsx')).toContain(
      'listNodes({ signal: controller.signal, sessionOnlyAuth: true })',
    );
  });

  it('keeps operation state presentation-only and reconciles after remote success', () => {
    const clients = read('src/components/ClientManager.tsx');
    const inbounds = read('src/components/InboundManager.tsx');
    const store = read('src/services/projectionOperationStore.ts');

    expect(store).toContain("| 'remote_succeeded_awaiting_projection'");
    expect(clients).toContain('reconcileClientsAfterMutation');
    expect(clients).toContain('confirmClientOperationFromProjection');
    expect(clients).toContain("'visible_in_projection'");
    expect(clients).toContain('onRemoteSuccess={handleMultiServerRemoteSuccess}');
    expect(inbounds).toContain('reconcileInboundsAfterMutation');
    expect(inbounds).toContain('confirmInboundOperationFromProjection');
    expect(inbounds).toContain("'visible_in_projection'");
    expect(clients).not.toContain('setClients((previous) => previous.map((item) => clientKey(item) === clientKey(client) ? { ...item, enable: !item.enable } : item))');
  });

  it('keeps an inbound row unchanged until a later authoritative projection confirms an enable mutation', async () => {
    const initialInbound = {
      id: 101,
      node_name: 'node-a',
      node_ip: '127.0.0.1',
      protocol: 'vless',
      port: 443,
      remark: 'alpha',
      enable: true,
      security: 'reality',
      is_reality: true,
      client_count: 1,
    };
    const reconciledInbound = { ...initialInbound, enable: false };

    listNodes.mockResolvedValue([{ id: 1, name: 'node-a' }]);
    getInboundsHeaderSource
      .mockResolvedValueOnce({ inbounds: [initialInbound] })
      .mockResolvedValueOnce({ inbounds: [reconciledInbound] });
    apiGet.mockResolvedValue({ data: { total: 1, enabled: 1, disabled: 0 } });
    apiPost.mockResolvedValue({ data: { ok: true } });

    render(createElement(InboundManager));

    const [statusButton] = await screen.findAllByTitle('inbounds.clickToDisable');
    fireEvent.click(statusButton);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(screen.getAllByTitle('inbounds.clickToDisable')).not.toHaveLength(0);
    expect(screen.getByText('inbounds.projectionOperationAwaiting', { exact: false })).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByTitle('inbounds.clickToEnable')).not.toHaveLength(0);
      expect(screen.getByText('inbounds.projectionOperationVisible', { exact: false })).toBeTruthy();
    }, { timeout: 2_000 });
  });

  it('keeps a deleted inbound visible until an authoritative projection confirms its absence', async () => {
    const initialInbound = {
      id: 202,
      node_name: 'node-b',
      node_ip: '127.0.0.2',
      protocol: 'vless',
      port: 8443,
      remark: 'to-delete',
      enable: true,
      security: 'reality',
      is_reality: true,
      client_count: 0,
    };

    vi.spyOn(window, 'confirm').mockReturnValue(true);
    listNodes.mockResolvedValue([{ id: 2, name: 'node-b' }]);
    getInboundsHeaderSource
      .mockResolvedValueOnce({ inbounds: [initialInbound] })
      .mockResolvedValueOnce({ inbounds: [] });
    apiGet.mockResolvedValue({ data: { total: 1, enabled: 1, disabled: 0 } });
    apiDelete.mockResolvedValue({ data: { ok: true } });

    render(createElement(InboundManager));
    const [deleteButton] = await screen.findAllByTitle('inbounds.deleteInbound');
    fireEvent.click(deleteButton);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(apiDelete).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText('to-delete')).not.toHaveLength(0);
    expect(screen.getByText('inbounds.projectionOperationAwaiting', { exact: false })).toBeTruthy();

    await waitFor(() => {
      expect(screen.queryByText('to-delete')).toBeNull();
      expect(screen.getByText((_, element) => (
        element?.textContent === 'inbounds.projectionOperationVisible · to-delete'
      ))).toBeTruthy();
    }, { timeout: 2_000 });
  });
});
