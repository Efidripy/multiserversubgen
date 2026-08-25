import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const getNodeTraffic = vi.hoisted(() => vi.fn());
const getNodeOnlineClients = vi.hoisted(() => vi.fn());

vi.mock('../src/api/serverOps', () => ({
  createApiToken: vi.fn(),
  deleteApiToken: vi.fn(),
  generateNodeMldsa65: vi.fn(),
  generateNodeUuid: vi.fn(),
  generateNodeVlessEncryption: vi.fn(),
  generateNodeX25519: vi.fn(),
  getApiTokens: vi.fn(),
  getNodeOnlineClients,
  getNodeTraffic,
  getOutboundsTraffic: vi.fn(),
  getXrayConfig: vi.fn(),
  getXrayMetrics: vi.fn(),
  getXrayObservatory: vi.fn(),
  getXrayVersions: vi.fn(),
  installXray: vi.fn(),
  resetAllNodeTraffics: vi.fn(),
  setApiTokenEnabled: vi.fn(),
  updatePanel: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

import { NodeOperationsModal } from '../src/components/NodeOperationsModal';

afterEach(() => {
  cleanup();
  getNodeTraffic.mockReset();
  getNodeOnlineClients.mockReset();
});

describe('NodeOperationsModal tab loading', () => {
  it('ignores a stale tab failure after the operator switches to a newer tab', async () => {
    let rejectTraffic: ((reason?: unknown) => void) | undefined;
    let resolveOnline: ((value: unknown) => void) | undefined;
    let trafficSignal: AbortSignal | undefined;
    getNodeTraffic.mockImplementation((_nodeId: number, options: { signal?: AbortSignal }) => {
      trafficSignal = options.signal;
      return new Promise((_, reject) => { rejectTraffic = reject; });
    });
    getNodeOnlineClients.mockImplementation(() => new Promise((resolve) => { resolveOnline = resolve; }));

    render(<NodeOperationsModal nodeId={7} nodeName="node-a" onClose={vi.fn()} />);
    await waitFor(() => expect(getNodeTraffic).toHaveBeenCalledWith(7, expect.objectContaining({ signal: expect.any(AbortSignal) })));

    fireEvent.click(screen.getByRole('button', { name: 'serverStatus.onlineClients' }));
    await waitFor(() => expect(getNodeOnlineClients).toHaveBeenCalledWith(7, expect.objectContaining({ signal: expect.any(AbortSignal) })));

    expect(trafficSignal?.aborted).toBe(true);

    rejectTraffic?.(new Error('stale traffic request'));
    resolveOnline?.({ fresh: true });

    await screen.findByText(/"fresh": true/);
    expect(screen.queryByText('stale traffic request')).toBeNull();
  });
});
