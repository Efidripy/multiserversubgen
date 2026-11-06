import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
import { XrayTemplatesEditor } from '../src/components/XrayTemplatesEditor';

const key = (name: string) => `subscriptionClients.sections.xray_json.${name}`;

function Editor() {
  const [values, setValues] = useState({ always_array: false, enabled: false, active: 'Default', templates: [] });
  return <XrayTemplatesEditor values={values} onChange={(name, value) => setValues((prev) => ({ ...prev, [name]: value }))} />;
}

afterEach(cleanup);

describe('Xray templates', () => {
  it('selects, adds and deletes a template, while Default is read only', () => {
    render(<Editor />);
    const editor = () => screen.getByLabelText(key('jsonEditor')) as HTMLTextAreaElement;
    expect(editor().readOnly).toBe(true);
    const defaultText = editor().value;
    fireEvent.change(screen.getByLabelText(key('newName')), { target: { value: 'My template' } });
    fireEvent.click(screen.getByRole('button', { name: key('add') }));
    expect(editor().readOnly).toBe(false);
    expect(editor().value).toBe(defaultText);
    fireEvent.change(editor(), { target: { value: '{"dns":{}}' } });
    fireEvent.change(screen.getByRole('combobox', { name: key('template') }), { target: { value: 'Default' } });
    expect(editor().readOnly).toBe(true);
    fireEvent.change(screen.getByRole('combobox', { name: key('template') }), { target: { value: 'My template' } });
    expect(editor().value).toBe('{"dns":{}}');
    fireEvent.click(screen.getByRole('button', { name: key('delete') }));
    fireEvent.click(screen.getByRole('button', { name: key('confirmDelete') }));
    expect(editor().readOnly).toBe(true);
    expect(editor().value).toBe(defaultText);
  });
});
