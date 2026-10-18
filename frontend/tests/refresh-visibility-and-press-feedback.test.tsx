import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('refresh visibility and native press feedback contract', () => {
  it('uses one enabled-native-button selector with explicit disabled, aria-disabled and opt-out exclusions', () => {
    const css = read('src/App.css');
    const selector = 'button:not(:disabled):not([aria-disabled="true"]):not([data-press-feedback="off"])';

    expect(css).toContain(`${selector} {`);
    expect(css).toContain(`${selector}:active {`);
    expect(css).toContain('cursor: pointer;');
    expect(css).toContain('transform: translateY(2px) scale(0.97);');
    expect(css).toContain('filter: brightness(0.91) contrast(0.98);');
    expect(css).toContain('box-shadow: inset 0 1px 2px rgba(6, 17, 31, 0.35);');
    expect(css).toContain('@media (prefers-reduced-motion: reduce)');
    expect(css).toContain('transition: none;');
    expect(css).toContain('transform: none;');
    expect(css).toContain('animation: none;');
  });

  it('keeps the Client and Inbound refresh controls coupled to the existing projection state', () => {
    const clients = read('src/components/ClientManager.tsx');
    const inbounds = read('src/components/InboundManager.tsx');

    for (const [source, manager] of [[clients, 'clients'], [inbounds, 'inbounds']] as const) {
      expect(source).toContain("const projectionRefreshing = projectionState === 'refreshing';");
      expect(source).toContain(`data-projection-refresh-status="${manager}"`);
      expect(source).toContain('role="status"');
      expect(source).toContain('aria-live="polite"');
      expect(source).toContain('animate-spin motion-reduce:animate-none');
    }

    expect(clients).toContain('aria-busy={loading || projectionRefreshing}');
    expect(inbounds).toContain('aria-busy={loading || pageLoading || projectionRefreshing}');
    expect(clients).toContain('void loadClients(Boolean(cached.data?.clients?.length));');
    expect(inbounds).toContain('void loadInbounds(Boolean(cached.data?.inbounds?.length));');
  });
});
