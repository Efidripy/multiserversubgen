import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const source = fs.readFileSync(path.resolve(__dirname, '../src/components/ClientManager.tsx'), 'utf8');

describe('Client Manager desktop table layout', () => {
  it('keeps the exact online marker spaced from its node label', () => {
    expect(source).toContain("'max-w-full justify-start gap-1.5 bg-[#0a0e1a] text-slate-200'");
  });

  it('renders last seen as a compact date and time stack', () => {
    expect(source).toContain('const hasLastSeen = lastSeenAt !== null');
    expect(source).toContain('lastSeenAt.toLocaleDateString()');
    expect(source).toContain("lastSeenAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })");
  });

  it('reserves room and wraps the long translated last-seen header', () => {
    expect(source).toContain('const sortButtonWrapClass');
    expect(source).toContain('w-[136px] px-3 py-3 align-top');
    expect(source).toContain('min-w-0 whitespace-normal');
    expect(source).toContain('w-16 px-3 py-3 align-top');
    expect(source).toContain('w-[224px] px-3 py-3 align-top');
  });
});
