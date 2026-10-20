import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const source = fs.readFileSync(
  path.resolve(__dirname, '../src/services/useTrafficStatsSubscription.ts'),
  'utf8',
);

describe('traffic subscription fallback contract', () => {
  it('requires a caller-owned fallback and does not issue an undocumented raw request', () => {
    expect(source).toContain('fallbackRun: () => void | Promise<void>;');
    expect(source).toContain('await fallbackRunRef.current?.();');
    expect(source).not.toContain('/clients/stats/traffic?period=day');
  });
});
