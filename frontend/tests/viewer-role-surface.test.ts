import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(resolve(__dirname, '..', 'src', path), 'utf8');

describe('viewer role surface', () => {
  it('hides the client and inbound sections that now require operator', () => {
    const app = read('App.tsx');
    expect(app).toContain("? ['dashboard', 'traffic', 'monitoring']");
    expect(app).toContain("role === 'viewer' && (activeTab === 'inbounds' || activeTab === 'clients')");
    expect(app).toContain("channels: role === 'viewer' ? [] : ['inbounds', 'snapshot_delta']");
  });

  it('does not request the raw collector snapshot for a viewer', () => {
    const monitoring = read('components/MonitoringDashboard.tsx');
    const loader = monitoring.slice(monitoring.indexOf('const loadLatestSnapshot'));
    expect(loader.indexOf("getAuth().role === 'viewer'")).toBeGreaterThan(-1);
    expect(loader.indexOf("getAuth().role === 'viewer'")).toBeLessThan(loader.indexOf("'/v1/snapshots/latest'"));
  });
});
