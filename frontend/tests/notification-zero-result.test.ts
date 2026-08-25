import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('inbound notification noise guard', () => {
  it('drops only empty 0/0 websocket results before creating a notification', () => {
    const source = read('src/App.tsx');
    const inboundHandler = source.indexOf("if (msg.type === 'inbound_update')");
    const emptyGuard = source.indexOf('if (successful === 0 && total === 0) return;', inboundHandler);
    const notificationCall = source.indexOf('pushUiNotification(', emptyGuard);

    expect(inboundHandler).toBeGreaterThanOrEqual(0);
    expect(emptyGuard).toBeGreaterThan(inboundHandler);
    expect(notificationCall).toBeGreaterThan(emptyGuard);
    expect(source).toContain('`${actionLabel}: ${successful}/${total}`');
    expect(source).toContain("successful === total ? 'success' : 'warning'");
  });

  it('keeps non-empty success, partial and failed result variants in the handler', () => {
    const source = read('src/App.tsx');
    const inboundHandler = source.indexOf("if (msg.type === 'inbound_update')");
    const handler = source.slice(inboundHandler, source.indexOf("if (msg.type === 'snapshot_delta')", inboundHandler));

    expect(handler).toContain('successful === 0 && total === 0');
    expect(handler).toContain('successful === total ?');
    expect(handler).toContain('successful}/${total}');
  });
});
