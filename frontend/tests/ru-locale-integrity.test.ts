import { describe, expect, it } from 'vitest';
import en from '../src/i18n/locales/en.json';
import ru from '../src/i18n/locales/ru.json';

const mojibake = /(?:Ð|Ñ|Ã|Â|â|ð|ï»¿|[\u0080-\u009F])/;

const flattenStrings = (value: unknown): string[] => {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap(flattenStrings);
  if (value && typeof value === 'object') return Object.values(value).flatMap(flattenStrings);
  return [];
};

const flattenKeys = (value: unknown, prefix = ''): string[] => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [prefix];
  return Object.entries(value).flatMap(([key, item]) => flattenKeys(item, prefix ? `${prefix}.${key}` : key));
};

describe('Russian locale integrity', () => {
  it('contains readable Russian text instead of mojibake or unrecoverable replacement runs', () => {
    const values = flattenStrings(ru);

    expect(ru.app.title).toBe('Мульти-Серверный Менеджер');
    expect(ru.nodes.editNode).toBe('Редактировать узел');
    expect(values.some((value) => mojibake.test(value))).toBe(false);
    expect(values.some((value) => /\?{3,}/.test(value))).toBe(false);
    expect(flattenKeys(ru).sort()).toEqual(flattenKeys(en).sort());
  });
});
