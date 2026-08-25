import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ apiPost: vi.fn() }));

vi.mock('../src/api/client', () => ({ default: { post: mocks.apiPost } }));
vi.mock('../src/auth', () => ({ getAuth: () => ({ username: 'test', password: 'test' }) }));

import { createNodesBounded, NODE_BATCH_CREATE_CONCURRENCY } from '../src/api/nodes';

const read = (relativePath: string) => fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8');

describe('bounded batch node creation', () => {
  it('limits in-flight writes while preserving every ordered settled result', async () => {
    const payloads = Array.from({ length: 20 }, (_, index) => ({ id: index + 1 }));
    let active = 0;
    let maxActive = 0;
    mocks.apiPost.mockImplementation(async (_url: string, payload: { id: number }) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 1));
      active -= 1;
      if (payload.id === 7) throw new Error('node 7 rejected');
      return { data: { id: payload.id } };
    });

    const results = await createNodesBounded(payloads, { emitChange: false });

    expect(maxActive).toBeLessThanOrEqual(NODE_BATCH_CREATE_CONCURRENCY);
    expect(mocks.apiPost).toHaveBeenCalledTimes(payloads.length);
    expect(results.map((result) => result.status === 'fulfilled' ? result.value.id : result.reason.message)).toEqual(
      payloads.map((payload) => payload.id === 7 ? 'node 7 rejected' : payload.id),
    );
    mocks.apiPost.mockReset();
  });

  it('keeps Node Manager on the bounded write path', () => {
    const source = read('src/components/NodeManager.tsx');

    expect(source).toContain('createNodesBounded(batchPreview, { emitChange: false })');
    expect(source).not.toContain('batchPreview.map((row) => createNode(row, { emitChange: false }))');
  });
});
