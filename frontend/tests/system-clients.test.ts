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

  it('keeps the Comment contract intact through realtime rows and the editor', () => {
    const snapshotSource = fs.readFileSync(path.resolve(__dirname, '../../backend/services/snapshot_push.py'), 'utf8');
    const editorSource = fs.readFileSync(path.resolve(__dirname, '../src/components/ClientEditModal.tsx'), 'utf8');

    expect(snapshotSource).toContain('"comment": client.get("comment", ""),');
    expect(snapshotSource).toContain('"is_system": is_system_client(client),');
    expect(editorSource).toContain('const [comment, setComment] = useState(client.comment ?? client.remark ?? \'\');');
    expect(editorSource).toContain('comment,');
  });
});
