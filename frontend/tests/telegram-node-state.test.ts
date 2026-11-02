import { describe, expect, it } from 'vitest';
import { countCustomerNodes, groupCustomerNodes } from '../src/components/TelegramAdmin';
import type { CustomerNode } from '../src/api/telegram';

const node = (node_id: number, state: string): CustomerNode => ({
  node_id,
  node_name: `node-${node_id}`,
  state,
  binding_id: null,
  desired_enabled: null,
  management_state: null,
});

describe('Telegram customer node state projection', () => {
  it('groups nodes by state while preserving backend order within each group', () => {
    const nodes = [node(1, 'available_to_add'), node(2, 'active'), node(3, 'problem'), node(4, 'active'), node(5, 'suspended')];

    expect(groupCustomerNodes(nodes).map((item) => item.node_id)).toEqual([2, 4, 5, 3, 1]);
    expect(countCustomerNodes(nodes)).toEqual({ active: 2, suspended: 1, available_to_add: 1, problem: 1 });
  });

  it('keeps a node with an unknown state visible', () => {
    expect(groupCustomerNodes([node(1, 'future_state'), node(2, 'active')]).map((item) => item.node_id)).toEqual([2, 1]);
  });
});
