import axios from 'axios';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import api from '../src/api';
import { ClientEditModal } from '../src/components/ClientEditModal';
import { normalizeClientRows } from '../src/components/ClientManager';
import { ThemeProvider } from '../src/contexts/ThemeContext';
import '../src/i18n/config';

const GIB = 1024 ** 3;

describe('3x-ui v3 client DTO', () => {
  afterEach(() => {
    cleanup();
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

  it('sends v3 security and byte quota without defaulting an unloaded limitIp to zero', async () => {
    let requestBody: Record<string, unknown> | undefined;
    api.defaults.adapter = async (config: any) => {
      requestBody = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
      return {
        data: { success: true },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    render(
      <ThemeProvider>
        <ClientEditModal
          client={{
            id: 'client-id',
            email: 'alice@example.test',
            enable: true,
            up: 1 * GIB,
            down: 2 * GIB,
            total: 3 * GIB,
            totalGB: 50 * GIB,
            expiryTime: 0,
            node_id: 1,
            inbound_id: 7,
            protocol: 'vless',
            security: 'auto',
          }}
          onClose={() => undefined}
          onSaved={() => undefined}
        />
      </ThemeProvider>,
    );

    const numericInputs = document.querySelectorAll<HTMLInputElement>('input[type="number"]');
    expect(numericInputs).toHaveLength(2);
    expect(numericInputs[0].value).toBe('50');
    expect(numericInputs[1].value).toBe('');

    fireEvent.change(numericInputs[0], { target: { value: '75' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(requestBody).toBeDefined());
    const updates = (requestBody as any).updates;
    expect(updates).toMatchObject({
      email: 'alice@example.test',
      totalGB: 75 * GIB,
      security: 'auto',
    });
    expect(updates).not.toHaveProperty('encryption');
    expect(updates).not.toHaveProperty('limitIp');
  });

  it('allows an explicit zero limitIp to be sent as the operator choice', async () => {
    let requestBody: Record<string, unknown> | undefined;
    api.defaults.adapter = async (config: any) => {
      requestBody = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
      return {
        data: { success: true },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    render(
      <ThemeProvider>
        <ClientEditModal
          client={{
            id: 'client-id',
            email: 'alice@example.test',
            enable: true,
            up: 0,
            down: 0,
            total: 0,
            totalGB: 0,
            expiryTime: 0,
            node_id: 1,
            inbound_id: 7,
            protocol: 'trojan',
          }}
          onClose={() => undefined}
          onSaved={() => undefined}
        />
      </ThemeProvider>,
    );

    const numericInputs = document.querySelectorAll<HTMLInputElement>('input[type="number"]');
    fireEvent.change(numericInputs[1], { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(requestBody).toBeDefined());
    expect((requestBody as any).updates.limitIp).toBe(0);
  });
});
