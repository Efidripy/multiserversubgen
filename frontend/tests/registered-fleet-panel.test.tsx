import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

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
  getRegisteredFleetSnapshotOverview: vi.fn(),
  listNodes: vi.fn(),
  deleteNode: vi.fn(),
  restartXray: vi.fn(),
  stopXray: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../src/api/nodes', () => ({
  getRegisteredFleetOverview: mocks.getRegisteredFleetOverview,
  getRegisteredFleetSnapshotOverview: mocks.getRegisteredFleetSnapshotOverview,
  listNodes: mocks.listNodes,
  deleteNode: mocks.deleteNode,
  NODES_CHANGED_EVENT: 'nodes-changed',
}));

vi.mock('../src/api/serverOps', () => ({
  restartXray: mocks.restartXray,
  stopXray: mocks.stopXray,
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('../src/services/DashboardDataContext', () => ({
  useDashboardData: () => null,
}));

import { RegisteredFleetPanel } from '../src/components/RegisteredFleetPanel';

afterEach(cleanup);

describe('RegisteredFleetPanel edit action', () => {
  it('passes the selected node to the edit flow instead of opening the add-node flow', async () => {
    const onEditNode = vi.fn();
    const onOpenNodes = vi.fn();
    mocks.getRegisteredFleetSnapshotOverview.mockResolvedValue([node]);

    render(
      <RegisteredFleetPanel
        collapsed={false}
        setCollapsed={vi.fn()}
        onEditNode={onEditNode}
        onOpenNodes={onOpenNodes}
      />,
    );

    await waitFor(() => expect(screen.getByText('edge-42')).toBeTruthy());
    expect(mocks.getRegisteredFleetOverview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTitle('Edit'));

    expect(onEditNode).toHaveBeenCalledWith(node);
    expect(onOpenNodes).not.toHaveBeenCalled();
  });

  it('keeps remote node probes behind the explicit Test All control', async () => {
    mocks.getRegisteredFleetSnapshotOverview.mockResolvedValue([node]);
    mocks.getRegisteredFleetOverview.mockResolvedValue([node]);

    render(<RegisteredFleetPanel collapsed={false} setCollapsed={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('edge-42')).toBeTruthy());
    expect(mocks.getRegisteredFleetOverview).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'nodes.testAll' }));
    await waitFor(() => expect(mocks.getRegisteredFleetOverview).toHaveBeenCalledTimes(1));
  });
});
