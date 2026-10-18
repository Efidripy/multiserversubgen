import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { toUiServer } from '../src/components/ServerStatus';
import { SectionNetworkActivity } from '../src/App';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('section activity and TCP RTT contract', () => {
  it('keeps unknown TCP RTT honest and formats only the measured handshake', () => {
    expect(toUiServer({ node: 'alpha', available: true, tcp_rtt_ms: 12.5 }).tcpRtt).toBe('12.50 ms');
    expect(toUiServer({ node: 'beta', available: true }).tcpRtt).toBe('—');
    expect(toUiServer({ node: 'gamma', available: false, tcp_rtt_ms: 8 }).tcpRtt).toBe('No connection');
  });

  it('uses TCP-qualified wording, only one online header chip, and preserves offline connection text', () => {
    const source = read('src/components/ServerStatus.tsx');
    expect(source).toContain("t('serverStatus.tcpRtt')");
    expect(source).toContain('{isOffline && (');
    expect(source).not.toContain('latency: isOnline');
    expect(source).toContain('{server.status}');
    expect(source).toContain('{server.tcpRtt}');
  });

  it('marks the aggregate refresh busy and spins before its full refresh chain settles', () => {
    const source = read('src/components/ServerStatus.tsx');
    expect(source).toContain('setRefreshPending(true);');
    expect(source).toContain('await refreshNodesNow();');
    expect(source).toContain('await dashboardData?.refresh();');
    expect(source).toContain('aria-busy={refreshBusy}');
    expect(source).toContain("refreshBusy ? 'animate-spin motion-reduce:animate-none' : ''");
  });

  it('renders the dot only during tracked network activity and disables its motion when requested', () => {
    const { rerender } = render(<SectionNetworkActivity active={false} label="Network activity" />);
    expect(screen.queryByRole('status')).toBeNull();

    rerender(<SectionNetworkActivity active label="Network activity" />);
    expect(screen.getByRole('status', { name: 'Network activity' }).className).toContain('app-topbar__activity-dot');

    const app = read('src/App.tsx');
    const css = read('src/App.css');
    expect(app).toContain('active={pendingRequests > 0}');
    expect(css).toContain('app-topbar-activity-pulse');
    expect(css).toContain('@media (prefers-reduced-motion: reduce)');
  });
});
