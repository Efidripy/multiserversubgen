import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const source = fs.readFileSync(path.resolve(__dirname, '../src/components/ServerStatus.tsx'), 'utf8');

describe('Server card log routing', () => {
  it('opens general server logs from the visible log button', () => {
    expect(source).toContain("title={t('serverStatus.serverLogsTitle', { node: server.name })}");
    expect(source).toContain("onClick={() => onShowLogs(server, 'panel')}");
  });

  it('keeps Xray access logs behind the explicitly titled icon action', () => {
    expect(source).toContain("title={t('serverStatus.xrayLogsTitle', { node: server.name })}");
    expect(source).toContain("onClick={() => onShowLogs(server, 'xray')}");
  });
});
