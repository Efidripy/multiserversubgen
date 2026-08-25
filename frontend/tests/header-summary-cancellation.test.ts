import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ apiGet: vi.fn(), listNodes: vi.fn() }));

vi.mock('../src/api/client', () => ({ default: { get: mocks.apiGet } }));
vi.mock('../src/auth', () => ({ getAuth: () => ({ username: 'test', password: 'test' }) }));
vi.mock('../src/api/nodes', () => ({ listNodes: mocks.listNodes }));

import {
  getBackupHeaderSource,
  getMonitoringHeaderSource,
  getSubscriptionsHeaderSource,
} from '../src/api/dashboard';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('header summary request lifecycle', () => {
  it('forwards one abort signal through every remote header source', async () => {
    const controller = new AbortController();
    mocks.apiGet.mockResolvedValue({ data: {} });
    mocks.listNodes.mockResolvedValue([]);

    await getMonitoringHeaderSource({ signal: controller.signal });
    await getBackupHeaderSource({ signal: controller.signal });
    await getSubscriptionsHeaderSource({ signal: controller.signal });

    expect(mocks.apiGet).toHaveBeenCalledWith('/v1/health/deps', expect.objectContaining({ signal: controller.signal }));
    expect(mocks.apiGet).toHaveBeenCalledWith('/v1/adguard/overview', expect.objectContaining({ signal: controller.signal }));
    expect(mocks.apiGet).toHaveBeenCalledWith('/v1/monitoring/stack', expect.objectContaining({ signal: controller.signal }));
    expect(mocks.apiGet).toHaveBeenCalledWith('/v1/emails', expect.objectContaining({ signal: controller.signal }));
    expect(mocks.listNodes).toHaveBeenCalledWith({ signal: controller.signal });
  });

  it('cancels the previous header summary before a tab change can leave it in flight', () => {
    const source = read('src/App.tsx');

    expect(source).toContain('const controller = new AbortController();');
    expect(source).toContain('getMonitoringHeaderSource({ signal: controller.signal })');
    expect(source).toContain('getBackupHeaderSource({ signal: controller.signal })');
    expect(source).toContain('getSubscriptionsHeaderSource({ signal: controller.signal })');
    expect(source).toContain('controller.abort();');
  });
});
