import { useEffect, useRef, useState, useCallback } from 'react';
import { getAuth } from '../auth';

interface WebSocketMessage {
  type: string;
  data: any;
  timestamp?: number;
}

interface UseWebSocketOptions {
  url: string;
  channels?: string[];
  onMessage?: (message: WebSocketMessage) => void;
  reconnectInterval?: number;
  enabled?: boolean;
  trackLastMessage?: boolean;
}

export const useWebSocket = ({
  url,
  channels = [],
  onMessage,
  reconnectInterval = 10000,
  enabled = true,
  trackLastMessage = false,
}: UseWebSocketOptions) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const channelsRef = useRef<string[]>(channels);
  const onMessageRef = useRef<typeof onMessage>(onMessage);
  const reconnectAttemptsRef = useRef(0);
  const lastErrorLogTsRef = useRef(0);
  const reconnectBlockedRef = useRef(false);
  const everConnectedRef = useRef(false);
  const initialConnectFailCountRef = useRef(0);
  const reconnectCooldownUntilRef = useRef(0);

  const safeSend = useCallback((payload: any): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    try {
      ws.send(JSON.stringify(payload));
      return true;
    } catch (error) {
      console.error('WebSocket send error:', error);
      return false;
    }
  }, []);

  // Update channels ref when channels change
  useEffect(() => {
    channelsRef.current = channels;
  }, [channels]);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    if (!enabled) return;
    if (reconnectBlockedRef.current) return;
    if (Date.now() < reconnectCooldownUntilRef.current) return;
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
      const auth = getAuth();
      const wsPath = `${basePath}/ws`;
      let wsUrl = url || `${protocol}//${host}${wsPath}`;
      if (!url && auth.username && auth.password) {
        const token = btoa(`${auth.username}:${auth.password}`);
        const params = new URLSearchParams({ token });
        if (auth.totpCode) {
          params.set('totp', auth.totpCode);
        }
        wsUrl += `?${params.toString()}`;
      }

      wsRef.current = new WebSocket(wsUrl);

      wsRef.current.onopen = () => {
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        reconnectBlockedRef.current = false;
        everConnectedRef.current = true;
        initialConnectFailCountRef.current = 0;
        reconnectCooldownUntilRef.current = 0;

        // Subscribe to channels
        channelsRef.current.forEach((channel) => {
          safeSend({
            type: 'subscribe',
            channel,
          });
        });
      };

      wsRef.current.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          if (trackLastMessage) {
            setLastMessage(message);
          }
          onMessageRef.current?.(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      wsRef.current.onerror = (error) => {
        // Browsers can emit an error while socket is still in CONNECTING state.
        // Do not spam logs for transient reconnect races.
        if (wsRef.current?.readyState === WebSocket.CONNECTING) {
          return;
        }
        const now = Date.now();
        if (now - lastErrorLogTsRef.current > 10000) {
          console.warn('WebSocket error:', error);
          lastErrorLogTsRef.current = now;
        }
      };

      wsRef.current.onclose = (event) => {
        setIsConnected(false);
        wsRef.current = null;

        // 1008 => policy/auth rejection. Do not hammer reconnect loop.
        if (event.code === 1008) {
          reconnectBlockedRef.current = true;
          const now = Date.now();
          if (now - lastErrorLogTsRef.current > 10000) {
            console.error('WebSocket rejected by server (auth/policy). Reconnect paused until next login.');
            lastErrorLogTsRef.current = now;
          }
          return;
        }

        // Skip noisy logs for transient first-connect close.
        if (everConnectedRef.current && event.code !== 1000 && event.code !== 1001) {
          const now = Date.now();
          if (now - lastErrorLogTsRef.current > 10000) {
            console.warn('WebSocket disconnected', event.code);
            lastErrorLogTsRef.current = now;
          }
        }

        // If socket never reaches OPEN repeatedly, pause reconnects.
        if (!everConnectedRef.current) {
          initialConnectFailCountRef.current += 1;
          if (initialConnectFailCountRef.current >= 4) {
            reconnectCooldownUntilRef.current = Date.now() + 5 * 60 * 1000; // 5 minutes
            const now = Date.now();
            if (now - lastErrorLogTsRef.current > 10000) {
              console.warn('WebSocket temporarily paused after repeated connect failures (cooldown 5m).');
              lastErrorLogTsRef.current = now;
            }
            return;
          }
        }

        // Attempt to reconnect
        if (enabled) {
          reconnectAttemptsRef.current += 1;
          const backoff = Math.min(30000, reconnectInterval * (2 ** Math.min(reconnectAttemptsRef.current, 5)));
          const jitter = Math.floor(Math.random() * 500);
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, backoff + jitter);
        }
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
    }
  }, [url, enabled, reconnectInterval, safeSend]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close();
      }
      wsRef.current = null;
    }

    setIsConnected(false);
    reconnectBlockedRef.current = false;
    reconnectCooldownUntilRef.current = 0;
    initialConnectFailCountRef.current = 0;
  }, []);

  const subscribe = useCallback((channel: string) => {
    if (!isConnected) return;
    safeSend({
      type: 'subscribe',
      channel,
    });
  }, [isConnected, safeSend]);

  const unsubscribe = useCallback((channel: string) => {
    if (!isConnected) return;
    safeSend({
      type: 'unsubscribe',
      channel,
    });
  }, [isConnected, safeSend]);

  const sendMessage = useCallback((message: any) => {
    if (!isConnected) return;
    safeSend(message);
  }, [isConnected, safeSend]);

  useEffect(() => {
    if (enabled) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [enabled, connect, disconnect]);

  // Update subscriptions when channels change
  useEffect(() => {
    if (!isConnected || !wsRef.current) return;
    if (wsRef.current.readyState !== WebSocket.OPEN) return;

    // Subscribe to new channels
    channels.forEach((channel) => {
      safeSend({
        type: 'subscribe',
        channel,
      });
    });
  }, [channels, isConnected, safeSend]);

  return {
    isConnected,
    lastMessage,
    subscribe,
    unsubscribe,
    sendMessage,
    disconnect,
  };
};
