/**
 * Хук для подписки на real-time обновления трафика через WebSocket
 * Заменяет регулярный polling
 */
import { useEffect, useRef, useCallback, useMemo, useState } from 'react';
import { wsManager } from './webSocketManager';

export interface TrafficUpdate {
  type: 'traffic_update' | 'client_update' | 'server_status' | 'inbound_update';
  data: Record<string, any>;
  timestamp: number;
  delta?: boolean;
}

export interface TrafficStatsSubscriptionOptions {
  channels: string[]; // 'traffic', 'clients', 'server_status', 'inbounds'
  onUpdate: (update: TrafficUpdate) => void;
  onError?: (error: Error) => void;
  fallbackPollIntervalMs?: number; // Fallback если WebSocket недоступен
  fallbackRun?: () => void | Promise<void>;
}

const CHANNEL_TO_EVENT: Record<string, TrafficUpdate['type']> = {
  traffic: 'traffic_update',
  traffic_update: 'traffic_update',
  clients: 'client_update',
  client_update: 'client_update',
  server_status: 'server_status',
  inbounds: 'inbound_update',
  inbound_update: 'inbound_update',
};

const EVENT_TO_CHANNEL: Record<string, string> = {
  traffic_update: 'traffic',
  client_update: 'clients',
  server_status: 'server_status',
  inbound_update: 'inbounds',
};

/**
 * Хук для подписки на обновления трафика через WebSocket
 */
export function useTrafficStatsSubscription({
  channels,
  onUpdate,
  onError,
  fallbackPollIntervalMs = 60_000,
  fallbackRun,
}: TrafficStatsSubscriptionOptions) {
  const fallbackIntervalRef = useRef<number | null>(null);
  const [isConnected, setIsConnected] = useState(wsManager.isConnected());
  const lastUpdateRef = useRef<number>(0);
  const debounceMs = 100; // Debounce обновлений на 100ms

  const normalizedChannels = useMemo(() => {
    const source = Array.isArray(channels) && channels.length > 0
      ? channels
      : ['traffic', 'clients', 'server_status'];
    return source
      .map((c) => EVENT_TO_CHANNEL[c] || c)
      .filter((c, idx, arr) => Boolean(c) && arr.indexOf(c) === idx);
  }, [channels]);

  useEffect(() => {
    let cancelled = false;
    const unsubscribers: Array<() => void> = [];

    const handleEvent = (eventType: TrafficUpdate['type']) => (message: unknown) => {
      const now = Date.now();
      if (now - lastUpdateRef.current < debounceMs) return;
      lastUpdateRef.current = now;

      const payload = (message as Record<string, any>) || {};
      const data = payload.data && typeof payload.data === 'object' ? payload.data : payload;
      const update: TrafficUpdate = {
        type: eventType,
        data,
        timestamp: Number(payload.timestamp) || now,
        delta: Boolean((payload.data as any)?._delta || (payload as any)._delta),
      };

      onUpdate(update);
    };

    const connectAndSubscribe = async () => {
      try {
        await wsManager.connect();
        if (cancelled) return;

        setIsConnected(wsManager.isConnected());

        normalizedChannels.forEach((channel) => {
          const eventType = CHANNEL_TO_EVENT[channel];
          if (!eventType) return;
          const unsubscribe = wsManager.subscribe(eventType, handleEvent(eventType));
          unsubscribers.push(unsubscribe);
          wsManager.send({ type: 'subscribe', channel });
        });
      } catch (err) {
        onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    };

    connectAndSubscribe().catch(() => undefined);

    const checkConnection = window.setInterval(() => {
      setIsConnected(wsManager.isConnected());
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(checkConnection);
      unsubscribers.forEach((unsub) => unsub());
      normalizedChannels.forEach((channel) => {
        wsManager.send({ type: 'unsubscribe', channel });
      });
    };
  }, [normalizedChannels, onUpdate, onError]);

  // Fallback на polling если нет WebSocket
  useEffect(() => {
    if (isConnected) {
      // WebSocket подключен - отключить polling
      if (fallbackIntervalRef.current !== null) {
        window.clearInterval(fallbackIntervalRef.current);
        fallbackIntervalRef.current = null;
        console.log('[TrafficStats] WebSocket подключен - polling отключен');
      }
      return;
    }

    // WebSocket недоступен - использовать fallback polling
    console.log('[TrafficStats] Offline/WS недоступен - используем fallback polling');
    fallbackIntervalRef.current = window.setInterval(async () => {
      try {
        if (fallbackRun) {
          await fallbackRun();
          return;
        }

        const response = await fetch('/api/clients/stats/traffic?period=day');
        if (!response.ok) return;
        const data = await response.json();
        onUpdate({
          type: 'traffic_update',
          data,
          timestamp: Date.now(),
          delta: false,
        });
      } catch (err) {
        onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    }, fallbackPollIntervalMs);

    return () => {
      if (fallbackIntervalRef.current !== null) {
        window.clearInterval(fallbackIntervalRef.current);
        fallbackIntervalRef.current = null;
      }
    };
  }, [isConnected, onUpdate, onError, fallbackPollIntervalMs, fallbackRun]);

  // Вернуть функцию для явной отписки
  return useCallback(() => {
    if (fallbackIntervalRef.current !== null) {
      window.clearInterval(fallbackIntervalRef.current);
      fallbackIntervalRef.current = null;
    }
  }, []);
}

export default useTrafficStatsSubscription;
