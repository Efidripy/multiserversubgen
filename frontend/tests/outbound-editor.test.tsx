import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn() }));
vi.mock('../src/api/serverOps', () => ({ getXrayTemplate: mocks.get, updateXrayTemplate: mocks.update }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../src/components/LazyJsonEditor', () => ({ LazyJsonEditor: ({ value, onChange, label }: any) => <textarea aria-label={label} value={value} onChange={e => onChange?.(e.target.value)} /> }));
import { XrayTemplateEditor } from '../src/components/XrayTemplateEditor';
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('synchronizes form and JSON and saves the exact draft and expected value', async () => {
  const original = [{ tag: 'a', protocol: 'vless', settings: { vnext: [{ address: 'old', port: 443, users: [{ id: 'x', extra: 9 }, { id: 'y' }] }, { address: 'other' }] }, extra: true }];
  mocks.get.mockResolvedValue({ outbounds: original }); mocks.update.mockResolvedValue(undefined); vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<XrayTemplateEditor nodeId={7} section="outbounds" />);
  await screen.findByText('old:443'); fireEvent.click(screen.getByLabelText('common.edit'));
  fireEvent.change(screen.getByLabelText('address'), { target: { value: 'new' } });
  fireEvent.click(screen.getAllByText('JSON')[1]);
  const json = screen.getByLabelText('nodeOps.outboundJson') as HTMLTextAreaElement;
  const draft = JSON.parse(json.value); expect(draft.settings.vnext[0].address).toBe('new');
  draft.settings.vnext[0].users[0].id = 'updated'; fireEvent.change(json, { target: { value: JSON.stringify(draft) } });
  fireEvent.click(screen.getByText('nodeOps.form')); expect((screen.getByLabelText('id') as HTMLInputElement).value).toBe('updated');
  fireEvent.click(screen.getByText('nodeOps.applyDraft')); fireEvent.click(screen.getByText('nodeOps.saveApply'));
  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(7, 'outbounds', [draft], original));
});

it('keeps an untouched outbound identical', async () => {
  const original = [{ tag: 'a', protocol: 'hysteria', settings: { address: 'host', port: 443, extra: 1 },
    streamSettings: { tlsSettings: { serverName: 'example', fingerprint: 'custom' } }, mux: { extra: true } }];
  mocks.get.mockResolvedValue({ outbounds: original });
  mocks.update.mockResolvedValue(undefined);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<XrayTemplateEditor nodeId={7} section="outbounds" />);
  await screen.findByText('host:443');
  fireEvent.click(screen.getByLabelText('common.edit'));
  expect((screen.getByLabelText('fingerprint (custom)') as HTMLInputElement).value).toBe('custom');
  fireEvent.click(screen.getByText('nodeOps.applyDraft'));
  expect((screen.getByText('nodeOps.saveApply') as HTMLButtonElement).disabled).toBe(true);
});
