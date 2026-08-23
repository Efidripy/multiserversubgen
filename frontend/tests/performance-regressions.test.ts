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

  it('reads client presence from the collector projection without a navigation-time fleet scan', () => {
    const source = read('src/components/ClientManager.tsx');
    const api = read('src/api/clients.ts');

    expect(source).toContain('getClientPresence(signal)');
    expect(source).toContain('CLIENT_PRESENCE_REFRESH_MS = 30 * 1000');
    expect(source).toContain('onlineClientKeys');
    expect(source).toContain('projection.online_by_node');
    expect(source).toContain('lastOnlineByNode');
    expect(source).toContain("isClientOnline(client) && <span aria-hidden=\"true\" className=\"h-2 w-2 shrink-0 rounded-full bg-emerald-300\" />");
    expect(source).not.toContain("api.get('/v1/clients/online'");
    expect(api).toContain("api.get('/v1/clients/presence'");
    expect(api).toContain('online_by_node?: Record<string, string[]>');
  });

  it('derives logical client groups from already filtered records without adding a fleet request', () => {
    const source = read('src/components/ClientManager.tsx');

    expect(source).toContain('groupClientsByEmail(filteredClients)');
    expect(source).toContain('const visibleClientGroups = sortedClientGroups.slice');
    expect(source).toContain('const visibleSlice = filteredClients.slice(0, TRAFFIC_FETCH_MAX_CLIENTS);');
  });

  it('keeps online traffic details explicit and cancels stale inbound requests', () => {
    const traffic = read('src/components/TrafficStats.tsx');
    const inbounds = read('src/components/InboundManager.tsx');
    expect(traffic).toContain('Full online details remain opt-in.');
    expect(traffic).toContain('const loadOnlineDetails = () =>');
    expect(traffic).toContain('getClientPresence(controller.signal)');
    expect(traffic).not.toContain("api.get('/v1/clients/online'");
    expect(traffic).toContain('groupOnlinePresence');
    expect(inbounds).toContain('inboundsAbortRef.current?.abort();');
    expect(inbounds).toContain('signal: controller.signal');
  });

  it('leaves remote cold-path projections to the active tab instead of the shared header', () => {
    const app = read('src/App.tsx');
    const clients = read('src/components/ClientManager.tsx');
    expect(app).not.toContain('getClientsHeaderSource');
    expect(app).not.toContain('getInboundsHeaderSource');
    expect(app).not.toContain('getTrafficHeaderSource');
    expect(app).toContain("case 'inbounds':\n          case 'clients':\n          case 'traffic':");
    expect(clients).toContain('listNodes({ signal: controller.signal })');
    expect(clients).toContain('getInboundsHeaderSource({ signal: controller.signal })');
  });

  it('renders Dashboard server cards from the cached snapshot instead of probing every node', () => {
    const app = read('src/App.tsx');
    const fleetPanel = read('src/components/RegisteredFleetPanel.tsx');

    expect(app).toContain('dashboardMode');
    expect(app).toContain('includeLiveStatus={false}');
    expect(fleetPanel).toContain('getRegisteredFleetSnapshotOverview()');
    expect(fleetPanel).toContain('load({ live: true })');
  });

  it('uses one persistent aggregate owner for the Dashboard instead of independent cold-path loops', () => {
    const app = read('src/App.tsx');
    const provider = read('src/services/DashboardDataContext.tsx');
    const serverStatus = read('src/components/ServerStatus.tsx');
    const fleetPanel = read('src/components/RegisteredFleetPanel.tsx');

    expect(app).toContain('<DashboardDataProvider>');
    expect(app).not.toContain('getDashboardHeaderMetrics');
    expect(provider).toContain("getDashboardOverview(period)");
    expect(provider).toContain('window.sessionStorage.setItem');
    expect(serverStatus).toContain('enabled: !dashboardData');
    expect(fleetPanel).toContain('if (dashboardData) return;');
  });

  it('does not fetch complete node databases just to render Backup Manager', () => {
    const backupManager = read('src/components/BackupManager.tsx');

    expect(backupManager).toContain('void loadNodes();');
    expect(backupManager).not.toContain("api.get('/v1/backup/all'");
    expect(backupManager).not.toContain('format: \'json\'');
    expect(backupManager).not.toContain('await refreshBackups()');
    expect(backupManager).toContain('downloadAllBackupsBlob()');
    expect(backupManager).toContain('downloadNodeBackup(nodeId)');
  });

  it('coalesces realtime traffic bursts without delaying explicit navigation controls', () => {
    const traffic = read('src/components/TrafficStats.tsx');
    expect(traffic).toContain('REALTIME_TRAFFIC_REFRESH_MIN_INTERVAL_MS = 60 * 1000');
    expect(traffic).toContain('const scheduleRealtimeTrafficRefresh = useCallback');
    expect(traffic).toContain('if (realtimeTrafficRefreshTimerRef.current === null)');
    expect(traffic).toContain("reason: 'group'");
    expect(traffic).toContain("reason: 'period'");
    expect(traffic).toContain('window.clearTimeout(realtimeTrafficRefreshTimerRef.current)');
  });

  it('keeps a per-period stale projection visible while Statistics refreshes', () => {
    const traffic = read('src/components/TrafficStats.tsx');

    expect(traffic).toContain('trafficSelections?: Record<string');
    expect(traffic).toContain('trafficSelectionCacheKey(nextGroupBy, nextPeriod)');
    expect(traffic).toContain('const cachedSelection = readCachedTrafficSelection(nextGroupBy, nextPeriod)');
    expect(traffic).toContain('{isColdLoading ? renderChartSkeleton()');
    expect(traffic).toContain('sessionStorage.removeItem(TRAFFIC_STATS_CACHE_KEY)');
  });
});
