import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const getNodeLogs = vi.hoisted(() => vi.fn());

vi.mock('../src/api/serverOps', () => ({
  getNodeLogs,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, values?: Record<string, string>) => values?.node ? `${key}:${values.node}` : key }),
}));

import { ServerLogsModal } from '../src/components/ServerLogsModal';

afterEach(() => {
  cleanup();
  getNodeLogs.mockReset();
});

describe('ServerLogsModal', () => {
  it('renders logs in a modal and sends level/syslog controls to the API', async () => {
    getNodeLogs.mockResolvedValue(['2026-08-23 INFO ready']);
    render(<ServerLogsModal open nodeId={25} nodeName="5-EST" kind="panel" onClose={vi.fn()} />);

    expect(screen.getByRole('dialog')).toBeTruthy();
    expect((await screen.findByRole('log')).textContent).toContain('2026-08-23 INFO ready');
    expect(getNodeLogs).toHaveBeenCalledWith(25, 'panel', { count: 120, level: 'info' });

    fireEvent.change(screen.getByRole('combobox', { name: 'serverStatus.logsViewerLevel' }), { target: { value: 'notice' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'serverStatus.logsViewerSyslog' }));

    await waitFor(() => expect(getNodeLogs).toHaveBeenLastCalledWith(25, 'panel', { count: 120, level: 'notice', syslog: true }));
  });

  it('closes on Escape and keeps Xray mode free of panel-only controls', async () => {
    getNodeLogs.mockResolvedValue([]);
    const onClose = vi.fn();
    render(<ServerLogsModal open nodeId={25} nodeName="5-EST" kind="xray" onClose={onClose} />);

    await screen.findByRole('log');
    expect(screen.queryByRole('checkbox', { name: 'serverStatus.logsViewerSyslog' })).toBeNull();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
