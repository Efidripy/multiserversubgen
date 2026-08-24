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
});
