import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import en from '../src/i18n/locales/en.json';
import ru from '../src/i18n/locales/ru.json';

const readSource = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('Activity Log localization', () => {
  it('localizes all user-facing labels reported by the i18n scanner', () => {
    const app = readSource('src/App.tsx');
    const panel = readSource('src/components/ActivityLogPanel.tsx');

    expect(app).toContain("title={t('common.activityLogTitle')}");
    expect(panel).toContain("t('common.activityLogPanelTitle', { version: 2 })");
    expect(panel).toContain("t('common.activityLogEmpty')");
    expect(ru.common.activityLogTitle).toBe('Журнал активности');
    expect(ru.common.activityLogEmpty).toBe('Нет записей');
    expect(en.common.activityLogPanelTitle).toBe('Activity Log v{{version}}');
  });
});
