import { describe, expect, it } from 'vitest';

import { formatOnlineTrafficTotal, groupOnlinePresence } from '../src/components/TrafficStats';

describe('online presence grouping', () => {
  it('distinguishes a measured zero total from unavailable traffic data', () => {
    expect(formatOnlineTrafficTotal({ 'zero@example.test': 0 }, 'zero@example.test', (value) => `${value} B`)).toBe('0 B');
    expect(formatOnlineTrafficTotal({}, 'missing@example.test', (value) => `${value} B`)).toBe('—');
  });

  it('groups one email once while retaining only the nodes observed online', () => {
    expect(groupOnlinePresence({
      online_by_node: {
        '7': ['AnnaA@example.test'],
        '9': ['annaa@example.test', 'other@example.test'],
      },
      node_names: { '7': 'alpha', '9': 'beta' },
    })).toEqual([
      {
        email: 'annaa@example.test',
        nodes: [
          { node_id: '7', node_name: 'alpha' },
          { node_id: '9', node_name: 'beta' },
        ],
      },
      {
        email: 'other@example.test',
        nodes: [{ node_id: '9', node_name: 'beta' }],
      },
    ]);
  });
});
