import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('reload generation guards', () => {
  it('uses monotonic generations and only lets the current request settle client state', () => {
    const source = read('src/components/ClientManager.tsx');

    expect(source).toContain('const requestId = ++requestIdRef.current;');
    expect(source).not.toContain('const requestId = Date.now();');
    expect(source).toContain('clientsLoadLoadingRequestIdRef');
    expect(source).toContain('if (requestIdRef.current !== requestId) return;');
    expect(source).toContain('if (requestIdRef.current === requestId) {');
    expect(source).toContain('if (clientsLoadAbortRef.current === controller) {');
  });

  it('uses monotonic generations and only lets the current request settle inbound state', () => {
    const source = read('src/components/InboundManager.tsx');

    expect(source).toContain('const requestId = ++requestIdRef.current;');
    expect(source).not.toContain('const requestId = Date.now();');
    expect(source).toContain('if (requestIdRef.current !== requestId) return;');
    expect(source).toContain('if (requestIdRef.current === requestId) {');
    expect(source).toContain('if (inboundsAbortRef.current === controller) {');
    expect(source).toContain('setPageLoading(false);');
  });

  it('reloads AdGuard history for the selected range and ignores stale responses', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('const adguardHistoryRequestIdRef = useRef(0);');
    expect(source).toContain('const loadAdguardHistory = async (requestedRangeSec = rangeSec) => {');
    expect(source).toContain('const requestId = ++adguardHistoryRequestIdRef.current;');
    expect(source).toContain('params: { range_sec: requestedRangeSec, bucket_sec: bucketSec }');
    expect(source).toContain('if (requestId !== adguardHistoryRequestIdRef.current) return;');
    expect(source).toContain('loadAdguardHistory(rangeSec);');
    expect(source).toContain('adguardHistoryAbortRef.current?.abort();');
  });

  it('cancels superseded MonitoringDashboard history requests', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('const historyAbortRef = useRef<AbortController | null>(null);');
    expect(source).toContain('historyAbortRef.current?.abort();');
    expect(source).toContain('const controller = new AbortController();');
    expect(source).toContain('fetchAllNodesHistory(sinceSec, perNodeLimit, controller.signal)');
    expect(source).toContain('fetchNodeHistory(nodeId, sinceSec, 2000, controller.signal)');
    expect(source).toContain('signal,');
    expect(source).toContain('if (historyAbortRef.current === controller) {');
    expect(source).toContain('historyAbortRef.current = null;');
  });

  it('cancels overlapping latest-snapshot reads before they can update traffic projections', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('const latestSnapshotRequestIdRef = useRef(0);');
    expect(source).toContain('const latestSnapshotAbortRef = useRef<AbortController | null>(null);');
    expect(source).toContain('latestSnapshotAbortRef.current?.abort();');
    expect(source).toContain("signal: controller.signal");
    expect(source).toContain('if (controller.signal.aborted || requestId !== latestSnapshotRequestIdRef.current) return null;');
    expect(source).toContain('if (cancelled || !snapshot) return;');
    expect(source).toContain('latestSnapshotRequestIdRef.current += 1;');
  });

  it('cancels overlapping MonitoringDashboard server-status reads', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('const serverStatusRequestIdRef = useRef(0);');
    expect(source).toContain('const serverStatusAbortRef = useRef<AbortController | null>(null);');
    expect(source).toContain('const requestId = ++serverStatusRequestIdRef.current;');
    expect(source).toContain('serverStatusAbortRef.current?.abort();');
    expect(source).toContain("api.get('/v1/servers/status', { auth: getAuth(), signal: controller.signal })");
    expect(source).toContain('if (controller.signal.aborted || requestId !== serverStatusRequestIdRef.current) return [];');
    expect(source).toContain('if (requestId === serverStatusRequestIdRef.current) {');
    expect(source).toContain('if (serverStatusAbortRef.current === controller) {');
    expect(source).toContain('serverStatusRequestIdRef.current += 1;');
  });

  it('cancels overlapping MonitoringDashboard collector-status reads', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('const collectorStatusRequestIdRef = useRef(0);');
    expect(source).toContain('const collectorStatusAbortRef = useRef<AbortController | null>(null);');
    expect(source).toContain('const requestId = ++collectorStatusRequestIdRef.current;');
    expect(source).toContain('collectorStatusAbortRef.current?.abort();');
    expect(source).toContain("api.get('/v1/collector/status', { auth: getAuth(), signal: controller.signal })");
    expect(source).toContain('if (controller.signal.aborted || requestId !== collectorStatusRequestIdRef.current) return;');
    expect(source).toContain('if (collectorStatusAbortRef.current === controller) {');
    expect(source).toContain('collectorStatusRequestIdRef.current += 1;');
  });

  it('cancels overlapping MonitoringDashboard dependency-health reads', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('const depsHealthRequestIdRef = useRef(0);');
    expect(source).toContain('const depsHealthAbortRef = useRef<AbortController | null>(null);');
    expect(source).toContain('const requestId = ++depsHealthRequestIdRef.current;');
    expect(source).toContain('depsHealthAbortRef.current?.abort();');
    expect(source).toContain("api.get('/v1/health/deps', { auth: getAuth(), signal: controller.signal })");
    expect(source).toContain('if (controller.signal.aborted || requestId !== depsHealthRequestIdRef.current) return;');
    expect(source).toContain('if (depsHealthAbortRef.current === controller) {');
    expect(source).toContain('depsHealthRequestIdRef.current += 1;');
  });

  it('cancels overlapping MonitoringDashboard stack-status reads', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('const stackStatusRequestIdRef = useRef(0);');
    expect(source).toContain('const stackStatusAbortRef = useRef<AbortController | null>(null);');
    expect(source).toContain('const requestId = ++stackStatusRequestIdRef.current;');
    expect(source).toContain('stackStatusAbortRef.current?.abort();');
    expect(source).toContain("api.get('/v1/monitoring/stack', { auth: getAuth(), signal: controller.signal })");
    expect(source).toContain('if (controller.signal.aborted || requestId !== stackStatusRequestIdRef.current) return;');
    expect(source).toContain('if (stackStatusAbortRef.current === controller) {');
    expect(source).toContain('stackStatusRequestIdRef.current += 1;');
  });

  it('guards TrafficStats online details and cache writes by request generation', () => {
    const source = read('src/components/TrafficStats.tsx');

    expect(source).toContain('const onlineClientsRequestIdRef = useRef(0);');
    expect(source).toContain('const onlineTotalsRequestIdRef = useRef(0);');
    expect(source).toContain('const requestId = ++onlineClientsRequestIdRef.current;');
    expect(source).toContain('const requestId = ++onlineTotalsRequestIdRef.current;');
    expect(source).toContain('if (!isCurrentTrafficRequest(requestId, onlineClientsRequestIdRef.current)) return undefined;');
    expect(source).toContain('if (!isCurrentTrafficRequest(requestId, onlineTotalsRequestIdRef.current)) return;');
    expect(source).toContain('onlineClientsLoadingRequestIdRef.current !== null');
  });
});
