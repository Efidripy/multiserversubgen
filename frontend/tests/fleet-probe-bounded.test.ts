import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('registered fleet probe orchestration', () => {
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
