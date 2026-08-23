import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { isSystemClient, isSystemClientComment } from '../src/utils/systemClients';

describe('SYSTEM client classification', () => {
  it('recognizes the standalone Comment marker without matching unrelated words', () => {
    expect(isSystemClientComment('SYSTEM')).toBe(true);
    expect(isSystemClientComment('managed by system')).toBe(true);
    expect(isSystemClientComment('ecosystem')).toBe(false);
    expect(isSystemClient({ comment: 'ordinary' })).toBe(false);
    expect(isSystemClient({ is_system: true })).toBe(true);
  });

  it('keeps SYSTEM hidden for all regular filters and exposes the dedicated filter', () => {
    const source = fs.readFileSync(path.resolve(__dirname, '../src/components/ClientManager.tsx'), 'utf8');
    expect(source).toContain("filterStatus === 'system' ? isSystemClient(client) : !isSystemClient(client)");
    expect(source).toContain("{ value: 'system', label: t('clients.system') }");
    expect(source).toContain('const visibleClients = clients.filter(c => !isSystemClient(c));');
  });
});
