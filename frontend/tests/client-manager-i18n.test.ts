import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import en from '../src/i18n/locales/en.json';
import ru from '../src/i18n/locales/ru.json';

const clientManagerSource = fs.readFileSync(
  path.resolve(__dirname, '../src/components/ClientManager.tsx'),
  'utf8',
);

describe('Client Manager localization', () => {
  it('localizes the desktop health column header', () => {
    expect(clientManagerSource).toContain("{t('clients.health')}");
    expect(ru.clients.health).toBe('Состояние');
    expect(en.clients.health).toBe('Health');
  });
});
