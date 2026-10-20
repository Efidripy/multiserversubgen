import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (file: string) => fs.readFileSync(path.resolve(__dirname, '..', file), 'utf8');

describe('force refresh component contracts', () => {
  it('keeps Client Manager mount and polling non-force while the button uses node refresh then force GETs', () => {
    const source = read('src/components/ClientManager.tsx');
    expect(source).toContain('await forceNodeRefresh();');
    expect(source).toContain('listNodes({ signal: controller.signal, sessionOnlyAuth: true, force: true })');
    expect(source).toContain('listNodes({ signal: controller.signal, sessionOnlyAuth: true })');
    expect(source).toContain('setInterval(() => loadClients(true)');
  });

  it('keeps Inbound Manager mount and reconciliation non-force while the button uses force', () => {
    const source = read('src/components/InboundManager.tsx');
    expect(source).toContain('await forceNodeRefresh();');
    expect(source).toContain('getInboundsHeaderSource({ signal: controller.signal, force: true })');
    expect(source).toContain('getInboundsHeaderSource({ signal: controller.signal })');
    expect(source).toContain('void loadInbounds(true);');
  });
});
