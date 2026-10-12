import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');
const count = (source: string, needle: string) => source.split(needle).length - 1;

describe('Monitoring request ownership contract', () => {
  it('keeps Monitoring reads in the dashboard owner and consumes a projection in App', () => {
    const app = read('src/App.tsx');
    const dashboard = read('src/components/MonitoringDashboard.tsx');

    expect(app).not.toContain('getMonitoringHeaderSource({ signal: controller.signal })');
    expect(app).toContain('<LazyMonitoringDashboard onHeaderProjectionChange=');
    expect(dashboard).toContain('onHeaderProjectionChange?:');
    expect(dashboard).toContain('lastHeaderProjectionRef');
  });

  it('has one initial owner for each previously duplicated Monitoring route', () => {
    const app = read('src/App.tsx');
    const dashboard = read('src/components/MonitoringDashboard.tsx');
    const duplicatedRoutes = [
      '/v1/health/deps',
      '/v1/adguard/overview',
      '/v1/monitoring/stack',
    ];

    for (const route of duplicatedRoutes) {
      expect(app).not.toContain(`api.get('${route}'`);
      expect(count(dashboard, `api.get('${route}'`)).toBe(1);
    }
  });

  it('keeps the bounded 60-second fallback refresh set explicit', () => {
    const source = read('src/components/MonitoringDashboard.tsx');
    expect(source).toContain('fallbackPollIntervalMs: 60_000');
    for (const route of [
      'loadHistory(selectedScope, rangeSec)',
      'loadLatestSnapshot()',
      'loadDepsHealth()',
      'loadStackStatus()',
      'loadServerStatuses()',
      'loadCollectorStatus()',
    ]) {
      expect(source).toContain(route);
    }
  });

  it('does not introduce mutable AdGuard calls into the refresh fallback', () => {
    const source = read('src/components/MonitoringDashboard.tsx');
    const fallback = source.slice(source.indexOf('fallbackRun:'), source.indexOf('});', source.indexOf('fallbackRun:')));
    expect(fallback).not.toContain('api.post');
    expect(fallback).not.toContain('api.put');
    expect(fallback).not.toContain('api.delete');
  });
});
