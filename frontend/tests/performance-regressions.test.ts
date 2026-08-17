import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { filterRealtimeChannelsForRole } from '../src/services/useTrafficStatsSubscription';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('navigation performance regressions', () => {
  it('keeps privileged realtime channels out of a viewer session', () => {
    expect(filterRealtimeChannelsForRole(['traffic', 'clients', 'inbounds', 'server_status'], 'viewer'))
      .toEqual(['traffic', 'server_status']);
    expect(filterRealtimeChannelsForRole(['traffic', 'clients', 'inbounds'], 'operator'))
      .toEqual(['traffic', 'clients', 'inbounds']);
  });

  it('does not run the denied last-online mutation when Client Manager mounts', () => {
    const source = read('src/components/ClientManager.tsx');
    expect(source).not.toContain("api.post('/v1/clients/last-online'");
    expect(source).toContain('!expandedKey || filteredClients.length === 0');
  });

  it('keeps online traffic details explicit and cancels stale inbound requests', () => {
    const traffic = read('src/components/TrafficStats.tsx');
    const inbounds = read('src/components/InboundManager.tsx');
    expect(traffic).toContain('Full online details remain opt-in.');
    expect(traffic).toContain('const loadOnlineDetails = () =>');
    expect(inbounds).toContain('inboundsAbortRef.current?.abort();');
    expect(inbounds).toContain('signal: controller.signal');
  });
});
