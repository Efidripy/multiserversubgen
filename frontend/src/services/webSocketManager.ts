/**
 * WebSocket Manager for Real-Time Updates
 * Subscribes to live changes and sends delta updates
 */

import React from 'react';
import { getAuth, setWsTicket } from '../auth';
import { verifyCurrentAuth } from '../api/authService';
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
  private reconnectTimer: number | null = null;
  private closedByOwner = false;
  private policyRefreshAttempted = false;
  private terminalPolicyFailure = false;
  private ticketRefreshPromise: Promise<boolean> | null = null;
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
      this.closedByOwner = false;
      if (this.terminalPolicyFailure) {
        reject(new Error('WebSocket reconnect is paused after an authentication/policy failure.'));
        return;
      }
      if (this.reconnectTimer !== null) {
        window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
      if (this.isConnecting || (this.ws && this.ws.readyState === WebSocket.OPEN)) {
        resolve();
        return;
      }

      this.isConnecting = true;
      try {
        const auth = getAuth();
        if (!auth.wsTicket) {
          this.isConnecting = false;
          reject(new Error('WebSocket ticket is missing; waiting for authenticated session.'));
          return;
        }

        const isSecurePage = window.location.protocol === 'https:';
        const isLocalDevelopment = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
        const allowInsecureWs = import.meta.env.VITE_ALLOW_INSECURE_WS === 'true';
        if (!isSecurePage && !isLocalDevelopment && !allowInsecureWs) {
          this.isConnecting = false;
          reject(new Error('Refusing insecure WebSocket outside local development. Configure HTTPS/WSS.'));
          return;
        }

        this.ws = new WebSocket(this.url, [`mssg-ticket.${auth.wsTicket}`]);

        this.ws.onopen = () => {
          devLog('[WebSocket] Connected');
          this.isConnecting = false;
          this.reconnectDelay = 1000;
          this.policyRefreshAttempted = false;

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
          // The close handler owns recovery.  Browser error events do not
          // include a safe diagnostic and logging each one caused console spam.
          devLog('[WebSocket] transport error', error);
          this.isConnecting = false;
          reject(error);
        };

        this.ws.onclose = (event) => {
          devLog('[WebSocket] Disconnected');
          this.isConnecting = false;
          this.ws = null;
          if (this.closedByOwner) {
            return;
          }
          if (event.code === 1008) {
            if (!this.policyRefreshAttempted) {
              this.policyRefreshAttempted = true;
              void this.refreshTicketAndReconnect();
            } else {
              this.terminalPolicyFailure = true;
            }
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

  private async refreshTicketAndReconnect(): Promise<void> {
    if (this.closedByOwner || this.terminalPolicyFailure) return;
    if (!this.ticketRefreshPromise) {
      this.ticketRefreshPromise = verifyCurrentAuth()
        .then((verified) => {
          if (!verified.ws_ticket) return false;
          setWsTicket(verified.ws_ticket);
          return true;
        })
        .catch(() => false)
        .finally(() => { this.ticketRefreshPromise = null; });
    }
    if (await this.ticketRefreshPromise) {
      this.attemptReconnect();
    } else {
      this.terminalPolicyFailure = true;
    }
  }

  private attemptReconnect() {
    if (this.closedByOwner || this.reconnectTimer !== null) return;
    const delay = Math.min(this.reconnectDelay, this.reconnectMaxDelay);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.closedByOwner) return;
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.reconnectMaxDelay);
      this.connect().catch(() => {
        // Silently fail and retry
      });
    }, delay);
  }

  send(message: any) {
    if (this.closedByOwner) return;
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
        console.error('[WebSocket] Handler error for event:', type, err);
      }
    });
    const allHandlers = this.handlers.get('*') || new Set();
    allHandlers.forEach((handler) => {
      try {
        handler(message);
      } catch (err) {
        console.error('[WebSocket] Generic handler error:', err);
      }
    });
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  resumeAfterAuth() {
    this.closedByOwner = false;
    this.terminalPolicyFailure = false;
    this.policyRefreshAttempted = false;
  }

  close() {
    this.closedByOwner = true;
    this.terminalPolicyFailure = false;
    this.policyRefreshAttempted = false;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.messageQueue = [];
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

export const wsManager = new WebSocketManager();

export interface WebSocketMessagesOptions {
  channels?: string[];
  enabled: boolean;
  onMessage: (message: any) => void;
}

export function useWebSocketMessages({ channels = [], enabled, onMessage }: WebSocketMessagesOptions) {
  const onMessageRef = React.useRef(onMessage);
  onMessageRef.current = onMessage;
  const channelsKey = channels.slice().sort().join(',');

  React.useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    const handler = (message: any) => onMessageRef.current(message);
    const unsubscribe = wsManager.subscribe('*', handler);
    wsManager.connect().then(() => {
      if (cancelled) return;
      channels.forEach((channel) => wsManager.send({ type: 'subscribe', channel }));
    }).catch(() => undefined);

    return () => {
      cancelled = true;
      unsubscribe();
      channels.forEach((channel) => wsManager.send({ type: 'unsubscribe', channel }));
    };
  }, [enabled, channelsKey]);
}

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
