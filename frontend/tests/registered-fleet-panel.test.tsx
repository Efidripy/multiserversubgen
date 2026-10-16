import { StrictMode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const node = {
  id: 42,
  name: 'edge-42',
  panel_url: 'https://edge.example.test:8443/panel',
  url: 'https://edge.example.test:8443/panel',
  source_type: 'xui',
  verify_tls: true,
  enabled: true,
  read_only: false,
  api_version: 'v3',
  ip: 'edge.example.test',
  port: '8443',
  base_path: 'panel',
  scheme: 'https',
  user: 'root',
  available: true,
};

const mocks = vi.hoisted(() => ({
  getRegisteredFleetOverview: vi.fn(),
  listNodes: vi.fn(),
  listTelegramNodePolicies: vi.fn(),
  updateTelegramNodePolicy: vi.fn(),
  deleteNode: vi.fn(),
  restartXray: vi.fn(),
  stopXray: vi.fn(),
  translate: (key: string) => key,
  dashboardData: {
    summary: null,
    fleet: [] as typeof node[],
    period: 'all_time' as const,
    loading: false,
    stale: false,
    lastUpdated: null,
    setPeriod: vi.fn(),
    refresh: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mocks.translate }),
}));

vi.mock('../src/api/nodes', () => ({
  getRegisteredFleetOverview: mocks.getRegisteredFleetOverview,
  listNodes: mocks.listNodes,
  listTelegramNodePolicies: mocks.listTelegramNodePolicies,
  updateTelegramNodePolicy: mocks.updateTelegramNodePolicy,
  deleteNode: mocks.deleteNode,
}));

vi.mock('../src/api/serverOps', () => ({
  restartXray: mocks.restartXray,
  stopXray: mocks.stopXray,
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('../src/services/DashboardDataContext', () => ({
  useDashboardData: () => mocks.dashboardData,
}));

import { RegisteredFleetPanel } from '../src/components/RegisteredFleetPanel';

afterEach(cleanup);

describe('RegisteredFleetPanel edit action', () => {
  beforeEach(() => {
    mocks.getRegisteredFleetOverview.mockReset();
    mocks.listNodes.mockReset();
    mocks.listTelegramNodePolicies.mockReset();
    mocks.updateTelegramNodePolicy.mockReset();
    mocks.deleteNode.mockReset();
    mocks.restartXray.mockReset();
    mocks.stopXray.mockReset();
    mocks.dashboardData.fleet = [];
    mocks.dashboardData.refresh.mockReset();
  });

  it('passes the selected node to the edit flow instead of opening the add-node flow', async () => {
    const onEditNode = vi.fn();
    const onOpenNodes = vi.fn();
    mocks.dashboardData.fleet = [node];
    mocks.listNodes.mockResolvedValue([node]);

    render(
      <RegisteredFleetPanel
        collapsed={false}
        setCollapsed={vi.fn()}
        onEditNode={onEditNode}
        onOpenNodes={onOpenNodes}
      />,
    );

    await waitFor(() => expect(screen.getByText('edge-42')).toBeTruthy());
    fireEvent.click(screen.getByTitle('Edit'));

    await waitFor(() => expect(onEditNode).toHaveBeenCalledWith(node));
    expect(mocks.listNodes).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) });
    expect(onOpenNodes).not.toHaveBeenCalled();
  });

  it('aborts the explicit edit-record read when the panel unmounts', async () => {
    let signal: AbortSignal | undefined;
    mocks.dashboardData.fleet = [node];
    mocks.listNodes.mockImplementation((options: { signal?: AbortSignal }) => {
      signal = options.signal;
      return new Promise((_resolve, reject) => {
        options.signal?.addEventListener(
          'abort',
          () => reject(new DOMException('Request aborted', 'AbortError')),
          { once: true },
        );
      });
    });

    const view = render(
      <RegisteredFleetPanel
        collapsed={false}
        setCollapsed={vi.fn()}
        onEditNode={vi.fn()}
        onOpenNodes={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText('edge-42')).toBeTruthy());
    fireEvent.click(screen.getByTitle('Edit'));
    await waitFor(() => expect(signal).toBeInstanceOf(AbortSignal));
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });

  it('keeps remote node probes behind the explicit Test All control', async () => {
    mocks.dashboardData.fleet = [node];
    mocks.getRegisteredFleetOverview.mockResolvedValue([node]);

    render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('edge-42')).toBeTruthy());
    expect(mocks.getRegisteredFleetOverview).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'nodes.testAll' }));
    await waitFor(() => expect(mocks.getRegisteredFleetOverview).toHaveBeenCalledTimes(1));
  });

  it('automatically loads one persisted Telegram policy snapshot for an eligible panel without a mutation', async () => {
    mocks.dashboardData.fleet = [node];
    mocks.listTelegramNodePolicies.mockResolvedValue([{
      node_id: node.id,
      provisioning_enabled: true,
      total_bytes: 0,
      validity_days: 0,
      client_enabled: true,
      policy_version: 3,
      updated_by: 'admin',
    }]);

    render(
      <StrictMode>
        <RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} canManageTelegram />
      </StrictMode>,
    );

    await waitFor(() => expect(mocks.listTelegramNodePolicies).toHaveBeenCalledTimes(1));
    expect(mocks.listTelegramNodePolicies).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) });
    await waitFor(() => expect(screen.getByRole('button', { name: 'nodes.telegramPolicyOnTitle' })).toBeTruthy());
    expect(mocks.updateTelegramNodePolicy).not.toHaveBeenCalled();
    expect(mocks.getRegisteredFleetOverview).not.toHaveBeenCalled();
  });

  it('does not repeat the automatic policy read when the eligible panel rerenders or collapses', async () => {
    mocks.dashboardData.fleet = [node];
    mocks.listTelegramNodePolicies.mockResolvedValue([]);
    const { rerender } = render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} canManageTelegram />);

    await waitFor(() => expect(mocks.listTelegramNodePolicies).toHaveBeenCalledTimes(1));
    rerender(<RegisteredFleetPanel collapsed setCollapsed={vi.fn()} canManageTelegram />);
    rerender(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} canManageTelegram />);

    expect(mocks.listTelegramNodePolicies).toHaveBeenCalledTimes(1);
    expect(mocks.updateTelegramNodePolicy).not.toHaveBeenCalled();
  });

  it('shows a known off state when the automatic policy response has no row for the node', async () => {
    mocks.dashboardData.fleet = [node];
    mocks.listTelegramNodePolicies.mockResolvedValue([]);

    render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} canManageTelegram />);

    await waitFor(() => expect(mocks.listTelegramNodePolicies).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'nodes.telegramPolicyOffTitle' })).toBeTruthy());
    expect(mocks.updateTelegramNodePolicy).not.toHaveBeenCalled();
  });

  it('does not read Telegram policies for an ineligible panel', async () => {
    mocks.dashboardData.fleet = [node];

    render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('edge-42')).toBeTruthy());
    expect(mocks.listTelegramNodePolicies).not.toHaveBeenCalled();
    expect(mocks.updateTelegramNodePolicy).not.toHaveBeenCalled();
  });

  it('performs a fresh second read immediately before the explicit Telegram policy mutation', async () => {
    mocks.dashboardData.fleet = [node];
    const policy = {
      node_id: node.id,
      provisioning_enabled: false,
      total_bytes: 0,
      validity_days: 0,
      client_enabled: true,
      policy_version: 3,
      updated_by: 'admin',
    };
    mocks.listTelegramNodePolicies.mockResolvedValue([policy]);
    mocks.updateTelegramNodePolicy.mockResolvedValue({
      ...policy,
      provisioning_enabled: true,
      policy_version: 4,
    });

    render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} canManageTelegram />);

    await waitFor(() => expect(mocks.listTelegramNodePolicies).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'nodes.telegramPolicyOffTitle' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'nodes.telegramPolicyOffTitle' }));

    await waitFor(() => expect(mocks.listTelegramNodePolicies).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.updateTelegramNodePolicy).toHaveBeenCalledWith(node.id, expect.objectContaining({
      provisioning_enabled: true,
      expected_policy_version: 3,
    })));
  });

  it('keeps Telegram status unknown and performs no mutation after the automatic read fails', async () => {
    mocks.dashboardData.fleet = [node];
    mocks.listTelegramNodePolicies.mockRejectedValue(new Error('policy read unavailable'));

    render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} canManageTelegram />);

    await waitFor(() => expect(mocks.listTelegramNodePolicies).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'nodes.telegramPolicyLoadTitle' })).toBeTruthy());
    expect(mocks.updateTelegramNodePolicy).not.toHaveBeenCalled();
  });

  it('aborts an automatic in-flight policy read on unmount without issuing a mutation', async () => {
    let signal: AbortSignal | undefined;
    mocks.dashboardData.fleet = [node];
    mocks.listTelegramNodePolicies.mockImplementation(({ signal: requestSignal }: { signal?: AbortSignal }) => {
      signal = requestSignal;
      return new Promise((_resolve, reject) => {
        requestSignal?.addEventListener('abort', () => reject(new DOMException('Request aborted', 'AbortError')), { once: true });
      });
    });

    const view = render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} canManageTelegram />);
    await waitFor(() => expect(signal).toBeInstanceOf(AbortSignal));
    view.unmount();

    await waitFor(() => expect(signal?.aborted).toBe(true));
    expect(mocks.updateTelegramNodePolicy).not.toHaveBeenCalled();
  });

});
