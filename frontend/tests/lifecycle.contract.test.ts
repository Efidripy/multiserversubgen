import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

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
    expect(clients).not.toContain('setClients((previous) => previous.map((item) => clientKey(item) === clientKey(client) ? { ...item, enable: !item.enable } : item))');
  });
});
