import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import en from '../src/i18n/locales/en.json';
import ru from '../src/i18n/locales/ru.json';

const source = fs.readFileSync(
  path.resolve(__dirname, '../src/components/ClientManager.tsx'),
  'utf8',
);

describe('Client Manager Telegram badge', () => {
  it('renders the TG marker only on the grouped row that expands into node records', () => {
    expect(source).toContain('telegram_linked?: boolean;');
    expect(source).toContain('group.clients.some((client) => client.telegram_linked)');
    expect(source).toContain(">TG</span>");
    expect(source).toContain("{expanded && group.clients.map(renderDesktopChild)}");
  });

  it('keeps the marker descriptive in both supported locales', () => {
    expect(ru.clients.telegramLinked).toBe('Привязан к Telegram');
    expect(en.clients.telegramLinked).toBe('Linked to Telegram');
  });
});
