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

  it('localizes the selected-client traffic reset confirmation and result', () => {
    expect(clientManagerSource).toContain("t('clients.confirmResetTrafficSelected', { count: emails.length })");
    expect(clientManagerSource).toContain("t('clients.resetTrafficSelectedResult', { count: res.data?.successful ?? emails.length })");
    expect(clientManagerSource).toContain("t('common.failed')");
    expect(ru.clients.confirmResetTrafficSelected).toBe('Сбросить трафик у выбранных клиентов: {{count}}?');
    expect(ru.clients.resetTrafficSelectedResult).toBe('Сброшен трафик у выбранных клиентов: {{count}}');
    expect(en.clients.confirmResetTrafficSelected).toBe('Reset traffic for {{count}} selected clients?');
    expect(en.clients.resetTrafficSelectedResult).toBe('Traffic reset for selected clients: {{count}}');
  });

  it('uses the shared localized fallback for every Client Manager operation error', () => {
    expect(clientManagerSource).not.toContain("|| 'Failed'");
    expect((clientManagerSource.match(/t\('common\.failed'\)/g) || []).length).toBeGreaterThanOrEqual(14);
    expect(ru.common.failed).toBe('Ошибка');
    expect(en.common.failed).toBe('Failed');
  });
});
