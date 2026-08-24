import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearAuthCredentials, setAuthCredentials } from '../src/auth';
import { WebSocketManager } from '../src/services/webSocketManager';

class MockWebSocket {
  static readonly OPEN = 1;
  static instances: MockWebSocket[] = [];

  readonly sent: string[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(_url: string, _protocols?: string[]) {
    MockWebSocket.instances.push(this);
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }

  send(message: string) {
    this.sent.push(message);
  }
}

describe('WebSocket reconnect subscriptions', () => {
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    setAuthCredentials('admin', '', '', 'test-ticket', 'admin');
  });

  afterEach(() => {
    clearAuthCredentials();
    globalThis.WebSocket = originalWebSocket;
    vi.useRealTimers();
  });

  it('replays each active channel exactly once after a transport reconnect', async () => {
    const manager = new WebSocketManager('ws://localhost/ws');
    const initialConnect = manager.connect();
    const first = MockWebSocket.instances[0];
    first.open();
    await initialConnect;

    const releaseTraffic = manager.subscribeChannel('traffic');
    const releaseSnapshot = manager.subscribeChannel('snapshot_delta');
    expect(first.sent.map((message) => JSON.parse(message))).toEqual([
      { type: 'subscribe', channel: 'traffic' },
      { type: 'subscribe', channel: 'snapshot_delta' },
    ]);

    first.close(1006);
    await vi.advanceTimersByTimeAsync(1000);
    const second = MockWebSocket.instances[1];
    second.open();

    expect(second.sent.map((message) => JSON.parse(message))).toEqual([
      { type: 'subscribe', channel: 'traffic' },
      { type: 'subscribe', channel: 'snapshot_delta' },
    ]);

    releaseTraffic();
    releaseSnapshot();
    expect(second.sent.map((message) => JSON.parse(message))).toContainEqual({ type: 'unsubscribe', channel: 'traffic' });
    expect(second.sent.map((message) => JSON.parse(message))).toContainEqual({ type: 'unsubscribe', channel: 'snapshot_delta' });
    manager.close();
  });

  it('shares the opening promise across concurrent consumers', async () => {
    const manager = new WebSocketManager('ws://localhost/ws');
    const firstConnect = manager.connect();
    const secondConnect = manager.connect();
    expect(secondConnect).toBe(firstConnect);

    MockWebSocket.instances[0].open();
    await expect(Promise.all([firstConnect, secondConnect])).resolves.toEqual([undefined, undefined]);
    manager.close();
  });

  it('keeps a channel subscribed until its final consumer releases the lease', async () => {
    const manager = new WebSocketManager('ws://localhost/ws');
    const connected = manager.connect();
    const socket = MockWebSocket.instances[0];
    socket.open();
    await connected;

    const firstRelease = manager.subscribeChannel('traffic');
    const secondRelease = manager.subscribeChannel('traffic');
    expect(socket.sent.map((message) => JSON.parse(message))).toEqual([{ type: 'subscribe', channel: 'traffic' }]);

    firstRelease();
    expect(socket.sent.map((message) => JSON.parse(message))).toEqual([{ type: 'subscribe', channel: 'traffic' }]);
    secondRelease();
    expect(socket.sent.map((message) => JSON.parse(message))).toEqual([
      { type: 'subscribe', channel: 'traffic' },
      { type: 'unsubscribe', channel: 'traffic' },
    ]);
    manager.close();
  });

  it('settles a connect promise when the socket closes before opening', async () => {
    const manager = new WebSocketManager('ws://localhost/ws');
    const connecting = manager.connect();
    MockWebSocket.instances[0].close(1000);

    await expect(connecting).rejects.toThrow('closed before opening');
    manager.close();
  });

  it('allows a fresh connect after an immediate missing-ticket rejection', async () => {
    const manager = new WebSocketManager('ws://localhost/ws');
    clearAuthCredentials();

    await expect(manager.connect()).rejects.toThrow('ticket is missing');
    setAuthCredentials('admin', '', '', 'replacement-ticket', 'admin');

    const retry = manager.connect();
    expect(MockWebSocket.instances).toHaveLength(1);
    MockWebSocket.instances[0].open();
    await expect(retry).resolves.toBeUndefined();
    manager.close();
  });

  it('replays a lease registered before an initial socket can open', async () => {
    const manager = new WebSocketManager('ws://localhost/ws');
    const releaseTraffic = manager.subscribeChannel('traffic');
    const first = MockWebSocket.instances[0];
    first.close(1006);
    await vi.advanceTimersByTimeAsync(1000);
    const second = MockWebSocket.instances[1];
    second.open();

    expect(second.sent.map((message) => JSON.parse(message))).toEqual([{ type: 'subscribe', channel: 'traffic' }]);
    releaseTraffic();
    manager.close();
  });

  it('clears active leases and cancels reconnects when the owner closes the session', async () => {
    const manager = new WebSocketManager('ws://localhost/ws');
    const releaseTraffic = manager.subscribeChannel('traffic');
    const first = MockWebSocket.instances[0];
    first.open();
    first.close(1006);
    manager.close();
    await vi.advanceTimersByTimeAsync(30000);

    expect(MockWebSocket.instances).toHaveLength(1);
    releaseTraffic();
  });
});
