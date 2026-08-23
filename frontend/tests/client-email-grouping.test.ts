import { describe, expect, it } from 'vitest';
import { groupClientsByEmail, normalizeClientEmail } from '../src/utils/clientGroups';

describe('client email grouping', () => {
  it('normalizes whitespace and casing into one logical user while retaining node records', () => {
    const records = [
      { email: 'Client@One.test', node: 'Frankfurt-1' },
      { email: ' client@one.test ', node: 'Amsterdam-2' },
      { email: 'other@one.test', node: 'Helsinki-1' },
    ];

    const groups = groupClientsByEmail(records);

    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({
      key: 'client@one.test',
      email: 'Client@One.test',
    });
    expect(groups[0].clients.map((client) => client.node)).toEqual(['Frankfurt-1', 'Amsterdam-2']);
    expect(groups[1].clients.map((client) => client.node)).toEqual(['Helsinki-1']);
  });

  it('keeps an empty email deterministic instead of merging it into another user', () => {
    expect(normalizeClientEmail(' Client@One.Test ')).toBe('client@one.test');
    expect(groupClientsByEmail([{ email: '' }, { email: ' ' }])[0].clients).toHaveLength(2);
  });
});
