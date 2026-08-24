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

  it('uses the active i18n language for rendered and exported timestamps', () => {
    const panel = readSource('src/components/ActivityLogPanel.tsx');
    const store = readSource('src/services/activityLog.ts');

    expect(panel).toContain("useTranslation();");
    expect(panel).toContain("toLocaleTimeString(i18n.language, { hour12: false })");
    expect(panel).toContain("activityLog.exportText(minLevel, i18n.language)");
    expect(store).toContain("exportText(minLevel: LogLevel = 'debug', locale = 'ru')");
    expect(store).toContain("toLocaleTimeString(locale, { hour12: false })");
  });
});
