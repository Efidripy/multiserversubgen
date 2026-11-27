import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { InboundEditModal } from '../src/components/InboundEditModal';
import { ThemeProvider } from '../src/contexts/ThemeContext';

const { put } = vi.hoisted(() => ({ put: vi.fn().mockResolvedValue({}) }));
vi.mock('../src/api', () => ({ default: { put } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const base = { id: 7, node_name: 'node', protocol: 'vless', port: 443, remark: 'main', enable: true, security: 'none', is_reality: false };
function open(streamSettings: Record<string, unknown>, sniffing?: Record<string, unknown>) {
  render(<ThemeProvider><InboundEditModal inbound={{ ...base, streamSettings, sniffing }} nodeId={1} onClose={() => {}} onSaved={() => {}} /></ThemeProvider>);
}
function field(name: string): HTMLInputElement {
  return screen.getByText(name).closest('[data-ln="field"]')!.querySelector('input')!;
}
async function save() {
  fireEvent.click(screen.getByText('common.update'));
  await waitFor(() => expect(put).toHaveBeenCalled());
  return put.mock.calls[0][1];
}
afterEach(() => { cleanup(); put.mockClear(); });

describe('inbound form serialization', () => {
  it.each([
    { network: 'ws', wsSettings: { custom: 1 } },
    { network: 'grpc', grpcSettings: { custom: 1 } },
    { network: 'httpupgrade', httpupgradeSettings: { custom: 1 } },
    { network: 'tcp', security: 'reality', realitySettings: { settings: { custom: 1 }, custom: 2 } },
    { network: 'tcp', security: 'tls', tlsSettings: { custom: 1 } },
    { network: 'xhttp', xhttpSettings: { host: 'example.com', custom: 1 } },
    {},
  ])('preserves unchanged settings: %j', async stream => {
    open(stream, { enabled: true, custom: 3 });
    if ('xhttpSettings' in stream) expect(field('inbounds.host').value).toBe('example.com');
    expect(await save()).toEqual({ remark: 'main', port: 443, enable: true, streamSettings: stream });
  });
  it('writes XHTTP values with Xray names and preserves unknown keys', async () => {
    open({ network: 'xhttp', xhttpSettings: { host: ['old', 'ignored'], maxBufferedSize: 5, uploadSizeLimit: 7, paddingBytes: '1-2', extra: true } });
    expect(field('inbounds.host').value).toBe('old');
    fireEvent.change(field('inbounds.host'), { target: { value: 'new.example' } });
    fireEvent.change(field('inbounds.maxBufferedUpload'), { target: { value: '9' } });
    fireEvent.change(field('inbounds.maxUploadSize'), { target: { value: '12' } });
    const padding = screen.getByText('inbounds.paddingBytes').closest('[data-ln="field"]')!.querySelectorAll('input');
    fireEvent.change(padding[0], { target: { value: '3' } });
    fireEvent.click(screen.getByRole('switch', { name: 'inbounds.noSseHeader' }));
    expect(await save()).toEqual({ remark: 'main', port: 443, enable: true, streamSettings: { network: 'xhttp', xhttpSettings: { host: 'new.example', maxBufferedSize: 5, uploadSizeLimit: 7, paddingBytes: '1-2', extra: true, scMaxBufferedPosts: 9, scMaxEachPostBytes: 12, xPaddingBytes: '3-2', noSSEHeader: true } } });
  });
  it('reads canonical XHTTP keys ahead of legacy values', () => {
    open({ network: 'xhttp', xhttpSettings: { scMaxBufferedPosts: 4, maxBufferedSize: 8, scMaxEachPostBytes: 6, uploadSizeLimit: 9, xPaddingBytes: '10-20', paddingBytes: '1-2' } });
    expect(field('inbounds.maxBufferedUpload').value).toBe('4');
    expect(field('inbounds.maxUploadSize').value).toBe('6');
    expect(screen.getByText('inbounds.paddingBytes').closest('[data-ln="field"]')!.querySelector('input')!.value).toBe('10');
  });
  it('writes sockopt and sniffing edits under Xray keys', async () => {
    open({ network: 'tcp', sockopt: { tcpMultiPath: true, tcpCongestion: 'old', v6only: true, extra: 1 } }, { enabled: true, excludeForInbound: ['old'], extra: 2 });
    fireEvent.click(screen.getByText('inbounds.sockopt'));
    fireEvent.click(screen.getByRole('switch', { name: 'inbounds.multipathTcp' }));
    fireEvent.click(screen.getByRole('switch', { name: 'inbounds.v6Only' }));
    fireEvent.change(field('inbounds.tcpCongestion'), { target: { value: 'bbr' } });
    fireEvent.change(field('inbounds.ipsExcluded'), { target: { value: '1.2.3.4' } });
    expect(await save()).toEqual({ remark: 'main', port: 443, enable: true, streamSettings: { network: 'tcp', sockopt: { tcpMultiPath: true, tcpCongestion: 'old', v6only: true, extra: 1, tcpMptcp: false, tcpcongestion: 'bbr', V6Only: false } }, sniffing: { enabled: true, excludeForInbound: ['old'], extra: 2, ipsExcluded: ['1.2.3.4'] } });
  });
});
