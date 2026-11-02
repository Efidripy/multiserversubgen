import { afterEach, describe, expect, it, vi } from 'vitest';

const post = vi.hoisted(() => vi.fn());
vi.mock('../src/api/client', () => ({ default: { post } }));
vi.mock('../src/auth', () => ({ getAuth: () => ({ username: 'u', password: 'p' }) }));

import { forceNodeRefresh, NODE_REFRESH_INCOMPLETE_EVENT } from '../src/services/forceRefresh';

describe('forceNodeRefresh', () => {
  afterEach(() => { post.mockReset(); });

  it('waits for node refresh with a 60 second timeout and shares in-flight calls', async () => {
    let resolve!: (value?: unknown) => void;
    post.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    const first = forceNodeRefresh();
    const second = forceNodeRefresh();
    expect(first).toBe(second);
    expect(post).toHaveBeenCalledWith('/v1/nodes/refresh-now', {}, expect.objectContaining({ params: { wait: true }, timeout: 60_000 }));
    resolve();
    await first;
  });

  it('swallows errors so callers can continue reading', async () => {
    post.mockRejectedValueOnce(new Error('timeout'));
    await expect(forceNodeRefresh()).resolves.toBeUndefined();
  });

  it.each([
    ['the server wait timed out', () => post.mockResolvedValueOnce({ data: { completed: false } }), 1],
    ['the request failed', () => post.mockRejectedValueOnce(new Error('timeout')), 1],
    ['every node refreshed', () => post.mockResolvedValueOnce({ data: { completed: true } }), 0],
  ])('reports an incomplete refresh when %s', async (_name, arrange, expected) => {
    const listener = vi.fn();
    window.addEventListener(NODE_REFRESH_INCOMPLETE_EVENT, listener);
    arrange();
    await forceNodeRefresh();
    window.removeEventListener(NODE_REFRESH_INCOMPLETE_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(expected);
  });
});
