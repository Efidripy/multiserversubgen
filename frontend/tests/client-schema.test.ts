// @vitest-environment jsdom
import { createElement, useState } from 'react';
import { fireEvent, render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SchemaForm } from '../src/components/outbound/SchemaForm';
import { clientFields } from '../src/components/outbound/schema/client';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(cleanup);

function form(protocol: string, initial: Record<string, unknown>, changed: (value: Record<string, unknown>) => void) {
  function Form() {
    const [value, setValue] = useState(initial);
    return createElement(SchemaForm, { value, fields: clientFields(protocol, value), onChange: next => {
      setValue(next);
      changed(next);
    } });
  }
  render(createElement(Form));
}

describe('client schema', () => {
  it('selects protocol fields and the actual UUID key', () => {
    const paths = (protocol: string, record = {}) => clientFields(protocol, record).map(f => JSON.stringify(f.path));
    expect(paths('vless', { id: 42, uuid: 'abc' })).toContain('["uuid"]');
    expect(paths('vless', { id: 42 })).not.toContain('["id"]');
    expect(paths('vmess')).toContain('["id"]');
    expect(paths('vmess')).toContain('["security"]');
    expect(paths('trojan')).toContain('["password"]');
    expect(paths('shadowsocks')).toContain('["password"]');
    expect(paths('hysteria')).toContain('["auth"]');
    expect(paths('hysteria2')).toContain('["auth"]');
    expect(paths('wireguard')).toContain('["allowedIPs"]');
    expect(paths('mtproto')).toContain('["adTag"]');
    expect(paths('trojan')).not.toContain('["flow"]');
    expect(clientFields('vless', {}).find(f => f.label === 'UUID')?.generate).toBe('uuid');
  });

  it('edits only touched values, preserving unknown and absent keys', () => {
    const changed = vi.fn();
    form('vless', { id: 3, uuid: 'old', reverse: { other: true }, extra: 7 }, changed);
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('UUID'), { target: { value: 'new' } });
    expect(changed).toHaveBeenLastCalledWith({ id: 3, uuid: 'new', reverse: { other: true }, extra: 7 });
    fireEvent.change(screen.getByLabelText('Reverse tag'), { target: { value: 'tag' } });
    expect(changed).toHaveBeenLastCalledWith({ id: 3, uuid: 'new', reverse: { other: true, tag: 'tag' }, extra: 7 });
  });

  it('shows only reset fields present in the record and retains forwarded ports', () => {
    const changed = vi.fn();
    form('vless', { resetDay: 3, resetMax: 5, forwardedPorts: [80] }, changed);
    expect(screen.getByLabelText('Reset day')).toBeTruthy();
    expect(screen.getByLabelText('Reset max')).toBeTruthy();
    expect(screen.queryByLabelText('Reset weekday')).toBeNull();
    fireEvent.change(screen.getByLabelText('Reset day'), { target: { value: '4' } });
    expect(changed).toHaveBeenLastCalledWith({ resetDay: 4, resetMax: 5, forwardedPorts: [80] });
  });

  it('converts quota and delayed expiry and supports a date with time', () => {
    const changed = vi.fn();
    form('vmess', { totalGB: 2 ** 30, expiryTime: -2 * 86400000 }, changed);
    expect((screen.getByLabelText('Traffic limit (GB)') as HTMLInputElement).value).toBe('1');
    expect((screen.getByLabelText('Delayed start (days)') as HTMLInputElement).value).toBe('2');
    fireEvent.change(screen.getByLabelText('Traffic limit (GB)'), { target: { value: '1.5' } });
    expect(changed.mock.lastCall?.[0].totalGB).toBe(1.5 * 2 ** 30);
    fireEvent.change(screen.getByLabelText('Delayed start (days)'), { target: { value: '3' } });
    expect(changed.mock.lastCall?.[0].expiryTime).toBe(-3 * 86400000);
    fireEvent.click(screen.getByLabelText('Delayed start'));
    fireEvent.change(screen.getByLabelText('Expiry date and time'), { target: { value: '2030-05-06T12:34' } });
    expect(changed.mock.lastCall?.[0].expiryTime).toBe(new Date('2030-05-06T12:34').getTime());
  });
});
