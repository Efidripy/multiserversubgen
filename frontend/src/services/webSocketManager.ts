/**
 * WebSocket Manager for Real-Time Updates
 * Subscribes to live changes and sends delta updates
 */

import React from 'react';
import { getAuth } from '../auth';
import { devLog } from '../utils/devLogger';

export interface DeltaUpdate<T> {
  type: 'full' | 'partial' | 'delete';
  entity: string; // 'client', 'node', 'traffic', etc.
  id: string;
  data?: Partial<T>;
  timestamp: number;
}

export type WebSocketMessageHandler = (message: any) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectDelay = 1000;
  private reconnectMaxDelay = 30000;
  private isConnecting = false;
  private handlers: Map<string, Set<WebSocketMessageHandler>> = new Map();
  private messageQueue: any[] = [];

  constructor(wsUrl?: string) {
    // Construct WebSocket URL from current location if not provided
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
    this.url = wsUrl || `${protocol}://${host}${basePath}/ws`;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.isConnecting || (this.ws && this.ws.readyState === WebSocket.OPEN)) {
        resolve();
        return;
      }

      this.isConnecting = true;
      try {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
          devLog('[WebSocket] Connected');
          this.isConnecting = false;
          this.reconnectDelay = 1000;

          const auth = getAuth();
          if (auth.username && auth.password) {
            this.ws?.send(JSON.stringify({
              type: 'auth',
              username: auth.username,
              password: auth.password,
              totp: auth.totpCode,
            }));
          }

          // Flush queued messages
          while (this.messageQueue.length > 0) {
            const msg = this.messageQueue.shift();
            this.send(msg);
          }

          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            this.dispatchMessage(message);
          } catch (err) {
            console.error('[WebSocket] Parse error:', err);
          }
        };

        this.ws.onerror = (error) => {
          console.error('[WebSocket] Error:', error);
          this.isConnecting = false;
          reject(error);
        };

        this.ws.onclose = (event) => {
          devLog('[WebSocket] Disconnected');
          this.isConnecting = false;
          this.ws = null;
          if (event.code === 1008) {
            return;
          }
          this.attemptReconnect();
        };
      } catch (err) {
        this.isConnecting = false;
        reject(err);
      }
    });
  }

  private attemptReconnect() {
    const delay = Math.min(this.reconnectDelay, this.reconnectMaxDelay);
    setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.reconnectMaxDelay);
      this.connect().catch(() => {
        // Silently fail and retry
      });
    }, delay);
  }

  send(message: any) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.messageQueue.push(message);
      if (!this.isConnecting) {
        this.connect().catch(() => {
          console.error('[WebSocket] Failed to send message');
        });
      }
      return;
    }

    try {
      this.ws.send(JSON.stringify(message));
    } catch (err) {
      console.error('[WebSocket] Send error:', err);
    }
  }

  subscribe(event: string, handler: WebSocketMessageHandler) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);

    // Return unsubscribe function
    return () => {
      this.handlers.get(event)?.delete(handler);
    };
  }

  private dispatchMessage(message: any) {
    const { type, ...data } = message;
    if (!type) return;

    const handlers = this.handlers.get(type) || new Set();
    handlers.forEach((handler) => {
      try {
        handler(data);
      } catch (err) {
        console.error(`[WebSocket] Handler error for '${type}':`, err);
      }
    });
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  close() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

export const wsManager = new WebSocketManager();

/**
 * Hook to use WebSocket subscriptions
 */
export function useWebSocketSubscription<T>(event: string, onMessage: (data: T) => void) {
  const [isConnected, setIsConnected] = React.useState(wsManager.isConnected());
  const onMessageRef = React.useRef(onMessage);
  onMessageRef.current = onMessage;

  React.useEffect(() => {
    wsManager.connect().catch(() => {
      console.warn('[WebSocket] Failed to connect');
    });

    // Stable wrapper so effect only re-runs when `event` changes, not when the callback changes
    const stableHandler = (data: T) => onMessageRef.current(data);
    const unsubscribe = wsManager.subscribe(event, stableHandler);

    const checkConnection = setInterval(() => {
      setIsConnected(wsManager.isConnected());
    }, 5000);

    return () => {
      unsubscribe();
      clearInterval(checkConnection);
    };
  }, [event]); // stable: onMessage read via ref

  return isConnected;
}

