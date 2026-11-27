import axios from 'axios';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import api from '../src/api';
import { ClientEditModal } from '../src/components/ClientEditModal';
import {
  mergeClientRowsWithTelegramMetadata,
  normalizeClientRows,
} from '../src/components/ClientManager';
import { ThemeProvider } from '../src/contexts/ThemeContext';
import '../src/i18n/config';

vi.mock('../src/components/LazyJsonEditor', () => ({
  LazyJsonEditor: ({ value, onChange, label, readOnly }: any) =>
    <textarea aria-label={label} value={value} readOnly={readOnly} onChange={e => onChange(e.target.value)} />,
}));

const GIB = 1024 ** 3;

describe('3x-ui v3 client DTO', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    api.defaults.adapter = axios.defaults.adapter;
  });

  it('keeps traffic.total bytes separate from the totalGB quota', () => {
    const [client] = normalizeClientRows([{
      email: 'alice@example.test',
      total: 3 * GIB,
      traffic_total: 10 * GIB,
      totalGB: 50 * GIB,
    }]);

    expect(client.total).toBe(10 * GIB);
    expect(client.totalGB).toBe(50 * GIB);
  });

  it('keeps Telegram metadata when a partial realtime snapshot omits it', () => {
    const previous = normalizeClientRows([{
      email: 'alice@example.test',
      node_id: 1,
      telegram_linked: true,
    }]);
    const incoming = normalizeClientRows([{
      email: 'alice@example.test',
      node_id: 1,
      up: 10,
    }]);

    const [client] = mergeClientRowsWithTelegramMetadata(previous, incoming);

    expect(client.telegram_linked).toBe(true);
  });

  it('accepts an explicit unlink from an enriched response', () => {
    const previous = normalizeClientRows([{
      email: 'alice@example.test',
      node_id: 1,
      telegram_linked: true,
    }]);
    const incoming = normalizeClientRows([{
      email: 'alice@example.test',
      node_id: 1,
      telegram_linked: false,
    }]);

    const [client] = mergeClientRowsWithTelegramMetadata(previous, incoming);

    expect(client.telegram_linked).toBe(false);
  });

  const record = { id: 'client-id', email: 'alice@example.test', enable: true, totalGB: 50 * GIB,
    security: 'none', expiryTime: 123456789, extra: { keep: true } };
  const client = { id: 'client-id', email: 'alice@example.test', enable: true, up: 0, down: 0,
    total: 3 * GIB, expiryTime: 0, node_id: 11, inbound_id: 17, protocol: 'vless', notes: 'old' };

  function setup(conflict = false) {
    const requests: { url: string; data: any }[] = [];
    api.defaults.adapter = async (config: any) => {
      if (config.method === 'get') return { data: { value: record }, status: 200, statusText: 'OK', headers: {}, config };
      requests.push({ url: config.url, data: JSON.parse(config.data) });
      if (conflict && config.url.endsWith('/record')) {
        throw { response: { status: 409 } };
      }
      return { data: { success: true }, status: 200, statusText: 'OK', headers: {}, config };
    };
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ThemeProvider><ClientEditModal client={client} onClose={() => undefined} onSaved={() => undefined} /></ThemeProvider>);
    return requests;
  }

  it('saves the exact record and expected without sending unchanged notes', async () => {
    const requests = setup();
    await screen.findByDisplayValue('alice@example.test');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]).toEqual({ url: '/v1/clients/client-id/record', data: {
      node_id: 11, inbound_id: 17, value: record, expected: record,
    } });
  });

  it('synchronizes form and JSON and saves changed notes', async () => {
    const requests = setup();
    fireEvent.change(await screen.findByDisplayValue('alice@example.test'), { target: { value: 'new@example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
    const editor = await screen.findByLabelText('JSON');
    const draft = JSON.parse((editor as HTMLTextAreaElement).value);
    expect(draft.email).toBe('new@example.test');
    draft.extra.keep = false;
    fireEvent.change(editor, { target: { value: JSON.stringify(draft) } });
    fireEvent.click(screen.getByRole('button', { name: 'Form' }));
    expect(screen.getByDisplayValue('new@example.test')).toBeTruthy();
    fireEvent.change(screen.getByDisplayValue('old'), { target: { value: 'new note' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0].data).toEqual({ node_id: 11, inbound_id: 17, expected: record, value: draft });
    expect(requests[1]).toEqual({ url: '/v1/clients/client-id/notes', data: {
      node_id: 11, inbound_id: 17, email: 'new@example.test', notes: 'new note',
    } });
  });

  it('retains the draft after a conflict and blocks invalid JSON', async () => {
    const requests = setup(true);
    fireEvent.change(await screen.findByDisplayValue('alice@example.test'), { target: { value: 'draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText(/Client changed on node/);
    expect(screen.getByDisplayValue('draft')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
    const editor = await screen.findByLabelText('JSON');
    fireEvent.change(editor, { target: { value: '{' } });
    expect((screen.getByRole('button', { name: 'Form' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
    expect(requests).toHaveLength(1);
  });
});
