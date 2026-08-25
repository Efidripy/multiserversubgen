import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ apiGet: vi.fn() }));

vi.mock('../src/api/client', () => ({ default: { get: mocks.apiGet } }));
vi.mock('../src/auth', () => ({ getAuth: () => ({ username: 'test', password: 'test' }) }));

import { getRegisteredFleetOverview } from '../src/api/nodes';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('registered fleet probe orchestration', () => {
  it('keeps probe concurrency bounded while preserving node order', async () => {
    const nodes = Array.from({ length: 20 }, (_, index) => ({ id: index + 1, name: `node-${index + 1}` }));
    let active = 0;
    let maxActive = 0;
    mocks.apiGet.mockImplementation(async (url: string) => {
      if (url === '/v1/nodes') return { data: { nodes } };
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 1));
      active -= 1;
      const id = Number(url.match(/nodes\/(\d+)\/server-status/)?.[1]);
      return { data: { available: id % 2 === 0 } };
    });

    const result = await getRegisteredFleetOverview();
    expect(result.map(({ id, available }) => ({ id, available }))).toEqual(
      nodes.map((node) => ({ id: node.id, available: node.id % 2 === 0 })),
    );
    expect(result.every((node) => typeof node.latency === 'number')).toBe(true);
    expect(maxActive).toBeLessThanOrEqual(8);
    mocks.apiGet.mockReset();
  });

  it('bounds explicit fleet probes and cancels superseded panel refreshes', () => {
    const nodesApi = read('src/api/nodes.ts');
    const fleetPanel = read('src/components/RegisteredFleetPanel.tsx');

    expect(nodesApi).toContain('const FLEET_PROBE_CONCURRENCY = 8;');
    expect(nodesApi).toContain('getNodeServerStatus(node.id, { signal: options.signal })');
    expect(nodesApi).toContain('Array.from({ length: concurrency }, () => probe())');
    expect(nodesApi).not.toContain('nodes.map(async (node) => {');
    expect(fleetPanel).toContain('const fleetRefreshAbortRef = useRef<AbortController | null>(null);');
    expect(fleetPanel).toContain('getRegisteredFleetOverview({ signal: controller.signal })');
    expect(fleetPanel).toContain('fleetRefreshAbortRef.current?.abort();');
    expect(fleetPanel).toContain('if (controller.signal.aborted || fleetRefreshAbortRef.current !== controller) return;');
  });
});
