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

  // Update channels ref when channels change
  useEffect(() => {
    channelsRef.current = channels;
  }, [channels]);

  const connect = useCallback(() => {
    if (!enabled) return;

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

        // Subscribe to channels
        channelsRef.current.forEach((channel) => {
          wsRef.current?.send(JSON.stringify({
            type: 'subscribe',
            channel,
          }));
        });
      };

      wsRef.current.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          setLastMessage(message);
          onMessage?.(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      wsRef.current.onerror = (error) => {
        console.error('WebSocket error:', error);
      };

      wsRef.current.onclose = () => {
        console.log('WebSocket disconnected');
        setIsConnected(false);

        // Attempt to reconnect
        if (enabled) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        }
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
    }
  }, [url, enabled, onMessage, reconnectInterval]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsConnected(false);
  }, []);

  const subscribe = useCallback((channel: string) => {
    if (wsRef.current && isConnected) {
      wsRef.current.send(JSON.stringify({
        type: 'subscribe',
        channel,
      }));
    }
  }, [isConnected]);

  const unsubscribe = useCallback((channel: string) => {
    if (wsRef.current && isConnected) {
      wsRef.current.send(JSON.stringify({
        type: 'unsubscribe',
        channel,
      }));
    }
  }, [isConnected]);

  const sendMessage = useCallback((message: any) => {
    if (wsRef.current && isConnected) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, [isConnected]);

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

    // Subscribe to new channels
    channels.forEach((channel) => {
      wsRef.current?.send(JSON.stringify({
        type: 'subscribe',
        channel,
      }));
    });
  }, [channels, isConnected]);

  return {
    isConnected,
    lastMessage,
    subscribe,
    unsubscribe,
    sendMessage,
    disconnect,
  };
};
