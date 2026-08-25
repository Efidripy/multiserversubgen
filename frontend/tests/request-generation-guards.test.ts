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
