import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const source = fs.readFileSync(path.resolve(__dirname, '../src/components/ServerStatus.tsx'), 'utf8');

describe('ServerStatus refresh control contract', () => {
  it('uses the new-design refresh control class and keeps busy state semantic', () => {
    expect(source).toContain('server-status__refresh-btn');
    expect(source).toContain('aria-busy={refreshBusy}');
    expect(source).toContain('server-status__refresh-icon');
    expect(source).toContain("refreshBusy ? 'animate-spin motion-reduce:animate-none' : ''");
  });
});
