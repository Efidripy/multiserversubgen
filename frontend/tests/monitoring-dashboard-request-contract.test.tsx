import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { monitoringScopeFromSearch } from '../src/components/MonitoringDashboard';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');
const count = (source: string, needle: string) => source.split(needle).length - 1;

describe('Monitoring request ownership contract', () => {
  it('accepts only a positive numeric server deep link before initial effects run', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain("export function monitoringScopeFromSearch(search: string): string");
    expect(source).toContain("new URLSearchParams(search).get('server')");
    expect(source).toContain("/^[1-9]\\d*$/.test(candidate)");
    expect(source).toContain("monitoringScopeFromSearch(typeof window === 'undefined' ? '' : window.location.search)");
  });

  it('normalizes the deep-link server id without accepting a fleet or malformed scope', () => {
    expect(monitoringScopeFromSearch('?server=17')).toBe('17');
    expect(monitoringScopeFromSearch('?server=00017')).toBe('all');
    expect(monitoringScopeFromSearch('?server=all')).toBe('all');
    expect(monitoringScopeFromSearch('?server=-1')).toBe('all');
    expect(monitoringScopeFromSearch('?scope=17')).toBe('all');
  });

  it('keeps a valid server deep link scoped until the operator explicitly selects All', () => {
    const source = read('src/components/MonitoringDashboard.tsx');

    expect(source).toContain('loadSelectedServerStatus(selectedNodeId)');
    expect(source).toContain('api.get(`/v1/servers/${nodeId}/status`');
    expect(source).toContain('do not initialize picker, snapshot, or fleet cards');
    expect(source).toContain("...(!isAllScope && selectedNodeId !== null && !nodes.some((node) => node.id === selectedNodeId)");
    expect(source).toContain("{ value: selectedScope, label: selectedNodeName }");
  });

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

  it('uses the HttpOnly browser session for every Monitoring read without weakening mutations', () => {
    const source = read('src/components/MonitoringDashboard.tsx');
    const reads = source.slice(0, source.indexOf('const collectAdguardNow'));
    const mutations = source.slice(source.indexOf('const collectAdguardNow'));

    expect(count(reads, 'sessionOnlyAuth: true,')).toBe(13);
    expect(reads).not.toContain('auth: getAuth()');
    expect(mutations).toContain("api.post('/v1/adguard/collect-now', {}, { auth: getAuth() })");
    expect(mutations).toContain('await api.put(`');
    expect(mutations).toContain('await api.delete(`');
  });
  it('does not introduce mutable AdGuard calls into the refresh fallback', () => {
    const source = read('src/components/MonitoringDashboard.tsx');
    const fallback = source.slice(source.indexOf('fallbackRun:'), source.indexOf('});', source.indexOf('fallbackRun:')));
    expect(fallback).not.toContain('api.post');
    expect(fallback).not.toContain('api.put');
    expect(fallback).not.toContain('api.delete');
  });
});
