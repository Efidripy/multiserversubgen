import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SchemaForm } from '../src/components/outbound/SchemaForm';
import { deletePath, setPath } from '../src/components/outbound/paths';
import type { FieldDef, Outbound } from '../src/components/outbound/types';
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function Harness({ fields, initial = {} }: { fields: FieldDef[]; initial?: Outbound }) {
  const [value, setValue] = useState(initial);
  return <><SchemaForm fields={fields} value={value} onChange={setValue} /><output data-testid="value">{JSON.stringify(value)}</output></>;
}
const data = () => JSON.parse(screen.getByTestId('value').textContent || '{}');
it('edits scalar, list, select, combobox, boolean and JSON fields', () => {
  const fields: FieldDef[] = [
    { path: ['text'], label: 'text', kind: 'text' },
    { path: ['number'], label: 'number', kind: 'number' },
    { path: ['boolean'], label: 'boolean', kind: 'boolean' },
    { path: ['select'], label: 'select', kind: 'select', options: ['known'] },
    { path: ['combo'], label: 'combo', kind: 'combobox', options: ['known'] },
    { path: ['list'], label: 'list', kind: 'list' },
    { path: ['numbers'], label: 'numbers', kind: 'numberList' },
    { path: ['json'], label: 'json', kind: 'json' },
  ];
  render(<Harness fields={fields} initial={{ select: 'unknown', extra: 1 }} />);
  expect((screen.getByLabelText('select') as HTMLSelectElement).value).toBe('unknown');
  for (const [label, value] of Object.entries({ text: 'abc', number: '12', select: 'known', combo: 'custom',
    list: 'a, b', numbers: '1, 2', json: '{"x":1}' })) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByLabelText('boolean'));
  expect(data()).toEqual({ extra: 1, text: 'abc', number: 12, boolean: true, select: 'known', combo: 'custom',
    list: ['a', 'b'], numbers: [1, 2], json: { x: 1 } });
});
it('renders sections, conditions, toggles, key values and nested arrays', () => {
  const fields: FieldDef[] = [
    { path: [], label: 'section', kind: 'section', fields: [
      { path: ['visible'], label: 'visible', kind: 'text', showIf: o => o.show === true },
    ] },
    { path: ['block'], label: 'block', kind: 'toggle', defaults: { x: 1 }, fields: [] },
    { path: ['map'], label: 'map', kind: 'keyValue' },
    { path: ['items'], label: 'items', kind: 'array', fields: [
      { path: ['name'], label: 'name', kind: 'text' },
      { path: ['children'], label: 'children', kind: 'array', fields: [
        { path: ['name'], label: 'child', kind: 'text' },
      ] },
    ] },
  ];
  render(<Harness fields={fields} initial={{ show: true, items: [{ name: 'first' }, { name: 'second' }] }} />);
  expect(screen.getByLabelText('visible')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('block'));
  vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
  fireEvent.click(screen.getByLabelText('block')); expect(data().block).toEqual({ x: 1 });
  fireEvent.click(screen.getByLabelText('block')); expect(data().block).toBeUndefined();
  fireEvent.click(screen.getAllByText('nodeOps.arrayAdd')[0]);
  fireEvent.change(screen.getByLabelText('nodeOps.key'), { target: { value: 'k' } });
  fireEvent.change(screen.getByLabelText('nodeOps.value'), { target: { value: 'v' } });
  expect(data().map).toEqual({ k: 'v' });
  fireEvent.click(screen.getAllByText('nodeOps.arrayDown')[0]);
  expect(data().items.map((v: Outbound) => v.name)).toEqual(['second', 'first']);
  fireEvent.click(screen.getAllByText('nodeOps.arrayAdd')[1]);
  fireEvent.change(screen.getByLabelText('child'), { target: { value: 'nested' } });
  expect(data().items[0].children[0].name).toBe('nested');
  fireEvent.click(screen.getAllByText('common.delete').at(-1)!);
  expect(data().items).toHaveLength(1);
});
it('updates paths immutably and clears empty parent objects', () => {
  const original = { other: 1 };
  const next = setPath(original, ['a', 'b'], 'value');
  expect(original).toEqual({ other: 1 });
  expect(deletePath(next, ['a', 'b'])).toEqual(original);
});
