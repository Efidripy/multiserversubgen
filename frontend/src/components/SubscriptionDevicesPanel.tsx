import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { useToast } from './Toast';
import { UIIcon } from './UIIcon';
import {
  cn,
  hintClass,
  iconButtonClass,
  secondaryButtonClass,
  titleClass,
} from './SubscriptionManager';

export interface SubscriptionDeviceItem {
  id: number;
  subject: string;
  device_os: string;
  os_version: string;
  model: string;
  first_seen: number;
  last_seen: number;
}

export interface SubscriptionDevicesApiResponse {
  devices: SubscriptionDeviceItem[];
}

export const SubscriptionDevicesPanel: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();

  const [devices, setDevices] = useState<SubscriptionDeviceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const fetchDevices = async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/v1/subscription-client-settings/devices', { signal });
      const data = res.data;
      if (Array.isArray(data?.devices)) {
        setDevices(data.devices);
      } else {
        setDevices([]);
      }
    } catch (err: any) {
      if (signal?.aborted) return;
      const detail = err.response?.data?.detail || err.message || t('subscriptionClients.devices.failed');
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void fetchDevices(controller.signal);
    return () => {
      controller.abort();
    };
  }, []);

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    try {
      await api.delete(`/v1/subscription-client-settings/devices/${id}`);
      setDevices((prev) => prev.filter((d) => d.id !== id));
      toast(t('subscriptionClients.devices.deleted'), 'success');
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message || t('subscriptionClients.devices.deleteFailed');
      toast(typeof detail === 'string' ? detail : JSON.stringify(detail), 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const formatTimestamp = (ts: number): string => {
    if (!ts || typeof ts !== 'number' || ts <= 0) return '—';
    try {
      return new Date(ts * 1000).toLocaleString();
    } catch {
      return String(ts);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-3 sm:p-4 shadow-sm">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h4 className={cn(titleClass, 'text-cyan-300')}>
            {t('subscriptionClients.devices.title')}
          </h4>
          <p className={hintClass}>
            {t('subscriptionClients.devices.hint')}
          </p>
        </div>
        <div>
          <button
            type="button"
            className={cn(secondaryButtonClass, 'h-8 px-3 text-xs')}
            onClick={() => void fetchDevices()}
            disabled={loading}
          >
            <UIIcon name="refresh" size={13} />
            <span className="whitespace-nowrap">{t('subscriptionClients.devices.refresh')}</span>
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex min-w-0 items-center justify-center gap-3 py-10 text-slate-400">
          <UIIcon name="spinner" size={18} />
          <span className="text-sm">{t('subscriptionClients.devices.loading')}</span>
        </div>
      )}

      {error && !loading && (
        <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          <div className="flex items-center justify-between gap-2">
            <span>{error}</span>
            <button
              type="button"
              className={cn(secondaryButtonClass, 'h-7 px-2 text-xs')}
              onClick={() => void fetchDevices()}
            >
              {t('subscriptionClients.devices.retry')}
            </button>
          </div>
        </div>
      )}

      {!loading && !error && devices.length === 0 && (
        <div className="py-8 text-center text-sm text-slate-400">
          {t('subscriptionClients.devices.empty')}
        </div>
      )}

      {!loading && !error && devices.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="border-b border-cyan-500/20 text-[11px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="py-2 pr-3">{t('subscriptionClients.devices.subject')}</th>
                <th className="py-2 pr-3">{t('subscriptionClients.devices.os')}</th>
                <th className="py-2 pr-3">{t('subscriptionClients.devices.version')}</th>
                <th className="py-2 pr-3">{t('subscriptionClients.devices.model')}</th>
                <th className="py-2 pr-3">{t('subscriptionClients.devices.firstSeen')}</th>
                <th className="py-2 pr-3">{t('subscriptionClients.devices.lastSeen')}</th>
                <th className="py-2 text-right">{t('subscriptionClients.devices.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-cyan-500/10">
              {devices.map((device) => (
                <tr key={device.id} className="hover:bg-slate-800/30">
                  <td className="py-2 pr-3 font-mono font-medium text-slate-200">
                    {device.subject || '—'}
                  </td>
                  <td className="py-2 pr-3">{device.device_os || '—'}</td>
                  <td className="py-2 pr-3 font-mono">{device.os_version || '—'}</td>
                  <td className="py-2 pr-3">{device.model || '—'}</td>
                  <td className="py-2 pr-3 text-slate-400">{formatTimestamp(device.first_seen)}</td>
                  <td className="py-2 pr-3 text-slate-400">{formatTimestamp(device.last_seen)}</td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      className={cn(iconButtonClass, 'h-8 w-8 text-rose-400 hover:text-rose-300')}
                      disabled={deletingId === device.id}
                      aria-label={t('subscriptionClients.devices.delete')}
                      title={t('subscriptionClients.devices.delete')}
                      onClick={() => void handleDelete(device.id)}
                    >
                      <UIIcon name={deletingId === device.id ? 'spinner' : 'trash'} size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
