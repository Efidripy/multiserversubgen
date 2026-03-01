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
}

export const useWebSocket = ({
  url,
  channels = [],
  onMessage,
  reconnectInterval = 3000,
  enabled = true,
}: UseWebSocketOptions) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const channelsRef = useRef<string[]>(channels);
  const onMessageRef = useRef<typeof onMessage>(onMessage);
  const reconnectAttemptsRef = useRef(0);
  const lastErrorLogTsRef = useRef(0);

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
        console.log('WebSocket connected');
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;

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
          setLastMessage(message);
          onMessageRef.current?.(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      wsRef.current.onerror = (error) => {
        const now = Date.now();
        if (now - lastErrorLogTsRef.current > 10000) {
          console.error('WebSocket error:', error);
          lastErrorLogTsRef.current = now;
        }
      };

      wsRef.current.onclose = () => {
        console.log('WebSocket disconnected');
        setIsConnected(false);
        wsRef.current = null;

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
