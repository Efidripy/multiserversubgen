import { describe, expect, it } from 'vitest';

import { formatOnlineClients } from '../src/components/ServerStatus';

describe('ServerStatus online clients metric', () => {
  it('keeps the loading placeholder only for an unavailable metric', () => {
    expect(formatOnlineClients(null)).toBe('—');
    expect(formatOnlineClients(undefined)).toBe('—');
  });

  it('renders zero and positive counts as real values', () => {
    expect(formatOnlineClients(0)).toBe('0');
    expect(formatOnlineClients(7)).toBe('7');
  });
});
