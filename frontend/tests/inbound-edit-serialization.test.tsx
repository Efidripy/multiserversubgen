import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { InboundEditModal } from '../src/components/InboundEditModal';

const { get, put } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock('../src/api', () => ({ default: { get, put } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../src/components/LazyJsonEditor', () => ({ LazyJsonEditor: (props: any) =>
  <textarea aria-label={props.label} value={props.value} onChange={e => props.onChange(e.target.value)} /> }));

const config = { remark: 'main', port: 443, enable: true, protocol: 'vless', listen: '', settings: { custom: 1 },
  streamSettings: { network: 'tcp', custom: 2 }, sniffing: {} };
function open() {
  get.mockResolvedValue({ data: structuredClone(config) });
  put.mockResolvedValue({});
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<InboundEditModal inbound={{ id: 7, node_name: 'node', protocol: 'vless' }} nodeId={1}
    onClose={() => {}} onSaved={() => {}} />);
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); get.mockReset(); put.mockReset(); });

describe('inbound editor', () => {
  it('saves without changes', async () => {
    open();
    await screen.findByLabelText('Remark');
    fireEvent.click(screen.getByText('common.save'));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][1]).toEqual({ value: config, expected: config });
  });
  it('saves a changed form while preserving unknown fields and expected version', async () => {
    open();
    fireEvent.change(await screen.findByLabelText('Remark'), { target: { value: 'updated' } });
    fireEvent.click(screen.getByText('common.save'));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][1]).toEqual({ value: { ...config, remark: 'updated' }, expected: config });
  });
  it('deletes JSON keys, blocks invalid JSON and retains the draft on conflict', async () => {
    open();
    await screen.findByLabelText('Remark');
    fireEvent.click(screen.getByText('JSON', { selector: 'button' }));
    const editor = screen.getByLabelText('JSON');
    fireEvent.change(editor, { target: { value: '{' } });
    expect((screen.getByText('common.save') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText('inbounds.form') as HTMLButtonElement).disabled).toBe(true);
    const next = structuredClone(config); delete (next.settings as Partial<typeof next.settings>).custom;
    fireEvent.change(editor, { target: { value: JSON.stringify(next) } });
    put.mockRejectedValueOnce({ response: { data: { detail: 'conflict' } } });
    fireEvent.click(screen.getByText('common.save'));
    await screen.findByText('conflict');
    expect(JSON.parse((editor as HTMLTextAreaElement).value)).toEqual(next);
    expect(put.mock.calls[0][1]).toEqual({ value: next, expected: config });
  });
});
