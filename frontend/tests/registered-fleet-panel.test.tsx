import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
  deleteNode: vi.fn(),
  restartXray: vi.fn(),
  stopXray: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../src/api/nodes', () => ({
  getRegisteredFleetOverview: mocks.getRegisteredFleetOverview,
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

import { RegisteredFleetPanel } from '../src/components/RegisteredFleetPanel';

describe('RegisteredFleetPanel edit action', () => {
  it('passes the selected node to the edit flow instead of opening the add-node flow', async () => {
    const onEditNode = vi.fn();
    const onOpenNodes = vi.fn();
    mocks.getRegisteredFleetOverview.mockResolvedValue([node]);

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

    expect(onEditNode).toHaveBeenCalledWith(node);
    expect(onOpenNodes).not.toHaveBeenCalled();
  });
});
