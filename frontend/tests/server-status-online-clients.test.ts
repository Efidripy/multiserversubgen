import { describe, expect, it } from 'vitest';

import {
  calculateAverageCpu,
  formatFleetRam,
  formatOnlineClients,
  formatTelemetryNetwork,
  formatTelemetryPercent,
  getReportedCoreVersion,
  toUiServer,
} from '../src/components/ServerStatus';

describe('ServerStatus online clients metric', () => {
  it('keeps the loading placeholder only for an unavailable metric', () => {
    expect(formatOnlineClients(null)).toBe('—');
    expect(formatOnlineClients(undefined)).toBe('—');
  });

  it('renders zero and positive counts as real values', () => {
    expect(formatOnlineClients(0)).toBe('0');
    expect(formatOnlineClients(7)).toBe('7');
  });

  it('aggregates only reported RAM telemetry instead of rendering a fixture value', () => {
    expect(formatFleetRam([
      { ramCurrentBytes: 2 * 1024 ** 3, ramTotalBytes: 4 * 1024 ** 3 },
      { ramCurrentBytes: 512 * 1024 ** 2, ramTotalBytes: 1024 ** 3 },
      {},
    ])).toBe('2.5 GB/5.0 GB');
    expect(formatFleetRam([{}])).toBe('—');
  });

  it('does not invent an Xray core version when telemetry is unavailable', () => {
    expect(getReportedCoreVersion('1.8.24', '3x-ui 2.5.6')).toBe('1.8.24');
    expect(getReportedCoreVersion(undefined, '3x-ui 2.5.6')).toBe('3x-ui 2.5.6');
    expect(getReportedCoreVersion(undefined, undefined)).toBe('—');
  });

  it('keeps missing telemetry unknown while retaining measured zero values', () => {
    const unknown = toUiServer({ node: 'unknown', available: true, system: {}, network: {} });
    const measuredZero = toUiServer({
      node: 'idle',
      available: true,
      system: { cpu: 0, mem: { percent: 0, current: 0, total: 0 }, disk: { percent: 0, current: 0, total: 0 } },
      network: { upload: 0, download: 0 },
    });

    expect(formatTelemetryPercent(unknown.cpu)).toBe('—');
    expect(unknown.network).toBe('—');
    expect(formatTelemetryPercent(measuredZero.cpu)).toBe('0%');
    expect(measuredZero.network).toBe('0 B / 0 B');
    expect(formatTelemetryNetwork({ upload: 0 })).toBe('0 B / —');
  });

  it('calculates fleet CPU from online nodes with reported telemetry only', () => {
    expect(calculateAverageCpu([
      { status: 'online', cpu: 10 },
      { status: 'online', cpu: 0 },
      { status: 'offline', cpu: 90 },
      { status: 'online' },
    ])).toBe(5);
    expect(calculateAverageCpu([{ status: 'offline', cpu: 90 }, { status: 'online' }])).toBeUndefined();
  });
});
