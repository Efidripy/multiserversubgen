import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight } from 'lucide-react';
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
  max_devices?: number;
}

export interface DeviceGroup {
  key: string;
  label: string;
  isGroup: boolean;
  devices: SubscriptionDeviceItem[];
}

export function groupDevices(devices: SubscriptionDeviceItem[]): DeviceGroup[] {
  if (!Array.isArray(devices) || devices.length === 0) {
    return [];
  }

  const groupMap = new Map<string, DeviceGroup>();

  for (const device of devices) {
    const rawSubject = (device?.subject ?? '').trim();
    const groupKey = rawSubject;

    let existing = groupMap.get(groupKey);
    if (!existing) {
      let label = rawSubject;
      let isGroup = false;

      if (/^email:/i.test(rawSubject)) {
        label = rawSubject.slice(6);
        isGroup = false;
      } else if (/^group:/i.test(rawSubject)) {
        label = rawSubject.slice(6);
        isGroup = true;
      }

      existing = {
        key: groupKey,
        label,
        isGroup,
        devices: [],
      };
      groupMap.set(groupKey, existing);
    }

    existing.devices.push(device);
  }

  return Array.from(groupMap.values()).sort((a, b) => {
    const cmp = a.label.localeCompare(b.label);
    if (cmp !== 0) return cmp;
    return a.key.localeCompare(b.key);
  });
}

export const SubscriptionDevicesPanel: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();

  const [devices, setDevices] = useState<SubscriptionDeviceItem[]>([]);
  const [maxDevices, setMaxDevices] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

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
      if (typeof data?.max_devices === 'number' && data.max_devices >= 0) {
        setMaxDevices(data.max_devices);
      } else {
        setMaxDevices(0);
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

  const toggleGroupExpanded = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const groups = useMemo(() => groupDevices(devices), [devices]);

  const formatTimestamp = (ts: number): string => {
    if (!ts || typeof ts !== 'number' || ts <= 0) return '—';
    try {
      return new Date(ts * 1000).toLocaleString();
    } catch {
      return String(ts);
    }
  };

  const renderMobileChild = (device: SubscriptionDeviceItem) => (
    <article
      key={device.id}
      className="ml-4 min-w-0 overflow-hidden rounded-lg border border-cyan-500/10 bg-[#0a0e1a] p-3"
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="truncate text-xs font-semibold text-slate-100">
              {device.device_os || '—'}
            </span>
            {device.os_version && (
              <span className="shrink-0 rounded border border-cyan-500/20 bg-[#0f1420] px-1.5 py-0.5 font-mono text-[11px] text-slate-300">
                {device.os_version}
              </span>
            )}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs">
            <span className="shrink-0 text-slate-500">
              {t('subscriptionClients.devices.model')}:
            </span>
            <span
              className="truncate text-slate-300"
              title={device.model || '—'}
            >
              {device.model || '—'}
            </span>
          </div>
        </div>
        <button
          type="button"
          className={cn(
            iconButtonClass,
            'h-8 w-8 shrink-0 text-rose-400 hover:text-rose-300'
          )}
          disabled={deletingId === device.id}
          aria-label={t('subscriptionClients.devices.delete')}
          title={t('subscriptionClients.devices.delete')}
          onClick={() => void handleDelete(device.id)}
        >
          <UIIcon
            name={deletingId === device.id ? 'spinner' : 'trash'}
            size={14}
          />
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
        <div className="min-w-0">
          <span className="block uppercase tracking-wider">
            {t('subscriptionClients.devices.firstSeen')}
          </span>
          <span
            className="mt-1 block break-words font-mono tabular-nums text-slate-300"
            title={formatTimestamp(device.first_seen)}
          >
            {formatTimestamp(device.first_seen)}
          </span>
        </div>
        <div className="min-w-0 text-right">
          <span className="block uppercase tracking-wider">
            {t('subscriptionClients.devices.lastSeen')}
          </span>
          <span
            className="mt-1 block break-words font-mono tabular-nums text-slate-300"
            title={formatTimestamp(device.last_seen)}
          >
            {formatTimestamp(device.last_seen)}
          </span>
        </div>
      </div>
    </article>
  );

  const renderDesktopChild = (device: SubscriptionDeviceItem) => (
    <tr
      key={device.id}
      className="hover:bg-slate-800/30"
    >
      <td className="py-2 pr-3 pl-8 text-slate-200">{device.device_os || '—'}</td>
      <td className="py-2 pr-3 font-mono">{device.os_version || '—'}</td>
      <td className="py-2 pr-3">{device.model || '—'}</td>
      <td className="py-2 pr-3 text-slate-400">{formatTimestamp(device.first_seen)}</td>
      <td className="py-2 pr-3 text-slate-400">{formatTimestamp(device.last_seen)}</td>
      <td className="py-2 text-right pr-2">
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
  );

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

      {!loading && !error && groups.length === 0 && (
        <div className="py-8 text-center text-sm text-slate-400">
          {t('subscriptionClients.devices.empty')}
        </div>
      )}

      {!loading && !error && groups.length > 0 && (
        <>
          {/* Mobile view (< lg) */}
          <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 lg:hidden">
            {groups.map((group) => {
              const expanded = expandedKeys.has(group.key);
              const count = group.devices.length;
              const isWarning = maxDevices > 0 && count >= maxDevices;
              const counterText =
                maxDevices > 0
                  ? t('subscriptionClients.devices.deviceCountLimit', { count, max: maxDevices })
                  : t('subscriptionClients.devices.deviceCount', { count });

              return (
                <article
                  key={group.key}
                  className="min-w-0 overflow-hidden rounded-lg bg-cyan-500/5 p-3 ring-1 ring-cyan-500/10"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <button
                      type="button"
                      className="flex w-full min-w-0 items-center justify-between gap-2 text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
                      aria-expanded={expanded}
                      aria-label={
                        expanded
                          ? t('subscriptionClients.devices.collapseGroup', { subject: group.label })
                          : t('subscriptionClients.devices.expandGroup', { subject: group.label })
                      }
                      onClick={() => toggleGroupExpanded(group.key)}
                    >
                      <div className="flex min-w-0 flex-1 items-center gap-2">
                        <ChevronRight
                          className={cn(
                            'h-4 w-4 shrink-0 text-cyan-300 transition-transform duration-150',
                            expanded && 'rotate-90'
                          )}
                          aria-hidden="true"
                        />
                        <span
                          className="min-w-0 truncate font-mono text-xs font-medium text-slate-200"
                          title={group.label}
                        >
                          {group.label || '—'}
                        </span>
                        {group.isGroup && (
                          <span className="shrink-0 rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium text-cyan-300">
                            {t('subscriptionClients.devices.groupBadge')}
                          </span>
                        )}
                      </div>
                      <div className="shrink-0">
                        <span
                          className={cn(
                            'inline-flex items-center rounded px-2 py-0.5 font-mono text-xs tabular-nums',
                            isWarning
                              ? 'border border-amber-400/40 bg-amber-400/15 text-amber-300 font-medium'
                              : 'border border-cyan-500/20 bg-[#0f1420] text-slate-400'
                          )}
                        >
                          {counterText}
                        </span>
                      </div>
                    </button>
                  </div>
                  {expanded && (
                    <div className="mt-3 grid min-w-0 grid-cols-1 gap-2">
                      {group.devices.map(renderMobileChild)}
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          {/* Desktop view (>= lg) */}
          <div className="mt-4 hidden min-w-0 overflow-x-auto lg:block">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="border-b border-cyan-500/20 text-[11px] uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="py-2 pr-3 pl-8">{t('subscriptionClients.devices.os')}</th>
                  <th className="py-2 pr-3">{t('subscriptionClients.devices.version')}</th>
                  <th className="py-2 pr-3">{t('subscriptionClients.devices.model')}</th>
                  <th className="py-2 pr-3">{t('subscriptionClients.devices.firstSeen')}</th>
                  <th className="py-2 pr-3">{t('subscriptionClients.devices.lastSeen')}</th>
                  <th className="py-2 text-right pr-2">{t('subscriptionClients.devices.actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-cyan-500/10">
                {groups.map((group) => {
                  const expanded = expandedKeys.has(group.key);
                  const count = group.devices.length;
                  const isWarning = maxDevices > 0 && count >= maxDevices;
                  const counterText =
                    maxDevices > 0
                      ? t('subscriptionClients.devices.deviceCountLimit', { count, max: maxDevices })
                      : t('subscriptionClients.devices.deviceCount', { count });

                  return (
                    <React.Fragment key={group.key}>
                      <tr className="bg-cyan-500/5 text-slate-100">
                        <td colSpan={6} className="p-0">
                          <button
                            type="button"
                            className="flex w-full min-w-0 items-center justify-between gap-3 px-3 py-2.5 text-left transition-colors hover:bg-cyan-500/10 focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
                            aria-expanded={expanded}
                            aria-label={
                              expanded
                                ? t('subscriptionClients.devices.collapseGroup', { subject: group.label })
                                : t('subscriptionClients.devices.expandGroup', { subject: group.label })
                            }
                            onClick={() => toggleGroupExpanded(group.key)}
                          >
                            <div className="flex min-w-0 flex-1 items-center gap-2">
                              <ChevronRight
                                className={cn(
                                  'h-4 w-4 shrink-0 text-cyan-300 transition-transform duration-150',
                                  expanded && 'rotate-90'
                                )}
                                aria-hidden="true"
                              />
                              <span
                                className="truncate font-mono text-xs font-medium text-slate-200"
                                title={group.label}
                              >
                                {group.label || '—'}
                              </span>
                              {group.isGroup && (
                                <span className="shrink-0 rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium text-cyan-300">
                                  {t('subscriptionClients.devices.groupBadge')}
                                </span>
                              )}
                            </div>
                            <div className="shrink-0">
                              <span
                                className={cn(
                                  'inline-flex items-center rounded px-2 py-0.5 font-mono text-xs tabular-nums',
                                  isWarning
                                    ? 'border border-amber-400/40 bg-amber-400/15 text-amber-300 font-medium'
                                    : 'border border-cyan-500/20 bg-[#0f1420] text-slate-400'
                                )}
                              >
                                {counterText}
                              </span>
                            </div>
                          </button>
                        </td>
                      </tr>
                      {expanded && group.devices.map(renderDesktopChild)}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
};
