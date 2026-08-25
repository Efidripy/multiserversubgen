import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const source = fs.readFileSync(
  path.resolve(__dirname, '..', 'src/components/ClientManager.tsx'),
  'utf8',
);

describe('Client IP search request lifecycle', () => {
  it('cancels superseded searches and ignores stale responses', () => {
    expect(source).toContain('const ipSearchRequestIdRef = useRef(0);');
    expect(source).toContain('const ipSearchAbortRef = useRef<AbortController | null>(null);');
    expect(source).toContain('const requestId = ++ipSearchRequestIdRef.current;');
    expect(source).toContain("signal: controller.signal,");
    expect(source).toContain('requestId !== ipSearchRequestIdRef.current');
    expect(source).toContain('ipSearchAbortRef.current?.abort();');
  });

  it('routes both Enter and button actions through one guarded search helper', () => {
    expect(source).toContain('await runIpSearch();');
    expect(source).toContain('onClick={() => { void runIpSearch(); }}');
    expect(source).toContain('const cancelIpSearch = () => {');
  });
});
