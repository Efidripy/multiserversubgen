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
  user_agent?: string;
  app?: string;
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

export type DeviceSortKey =
  | 'email'
  | 'count'
  | 'app'
  | 'os'
  | 'version'
  | 'model'
  | 'first_seen'
  | 'last_seen';

export type SortDirection = 'asc' | 'desc';

const sortButtonClass =
  'inline-flex min-w-0 items-center gap-1 whitespace-nowrap text-left text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500 transition-colors hover:text-cyan-300';

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

function isEmptyValue(val: unknown, key: DeviceSortKey): boolean {
  if (val == null) return true;
  if (key === 'first_seen' || key === 'last_seen') {
    return typeof val !== 'number' || val <= 0 || Number.isNaN(val);
  }
  if (typeof val === 'number') {
    return Number.isNaN(val);
  }
  return String(val).trim() === '';
}

function compareFieldValues(
  valA: unknown,
  valB: unknown,
  key: DeviceSortKey,
  direction: SortDirection
): number {
  const emptyA = isEmptyValue(valA, key);
  const emptyB = isEmptyValue(valB, key);

  if (emptyA && emptyB) return 0;
  if (emptyA) return 1; // empty values always at the end
  if (emptyB) return -1;

  let cmp = 0;
  if (key === 'version') {
    cmp = String(valA).localeCompare(String(valB), undefined, { numeric: true });
  } else if (key === 'first_seen' || key === 'last_seen' || key === 'count') {
    const numA = Number(valA);
    const numB = Number(valB);
    cmp = numA < numB ? -1 : numA > numB ? 1 : 0;
  } else {
    cmp = String(valA).localeCompare(String(valB));
  }

  return direction === 'asc' ? cmp : -cmp;
}

function getDeviceFieldValue(device: SubscriptionDeviceItem, key: DeviceSortKey): unknown {
  switch (key) {
    case 'email':
      return device.subject;
    case 'app':
      return device.app ?? '';
    case 'os':
      return device.device_os ?? '';
    case 'version':
      return device.os_version ?? '';
    case 'model':
      return device.model ?? '';
    case 'first_seen':
      return device.first_seen;
    case 'last_seen':
      return device.last_seen;
    case 'count':
      return 0;
    default:
      return '';
  }
}

export function sortDeviceGroups(
  groups: DeviceGroup[],
  key: DeviceSortKey = 'email',
  direction: SortDirection = 'asc'
): DeviceGroup[] {
  if (!Array.isArray(groups)) return [];

  // Sort devices inside each group without mutating inputs
  const processedGroups: DeviceGroup[] = groups.map((g) => {
    const devicesCopy = Array.isArray(g.devices) ? [...g.devices] : [];

    devicesCopy.sort((a, b) => {
      if (key === 'email' || key === 'count') {
        return a.id - b.id;
      }
      const valA = getDeviceFieldValue(a, key);
      const valB = getDeviceFieldValue(b, key);
      const cmp = compareFieldValues(valA, valB, key, direction);
      if (cmp !== 0) return cmp;
      return a.id - b.id;
    });

    return {
      ...g,
      devices: devicesCopy,
    };
  });

  // Sort groups
  processedGroups.sort((groupA, groupB) => {
    let cmp = 0;

    if (key === 'email') {
      cmp = compareFieldValues(groupA.label, groupB.label, 'email', direction);
    } else if (key === 'count') {
      cmp = compareFieldValues(groupA.devices.length, groupB.devices.length, 'count', direction);
    } else {
      const firstA = groupA.devices[0];
      const firstB = groupB.devices[0];
      const valA = firstA ? getDeviceFieldValue(firstA, key) : undefined;
      const valB = firstB ? getDeviceFieldValue(firstB, key) : undefined;
      cmp = compareFieldValues(valA, valB, key, direction);
    }

    if (cmp !== 0) return cmp;

    const labelCmp = groupA.label.localeCompare(groupB.label);
    if (labelCmp !== 0) return labelCmp;
    return groupA.key.localeCompare(groupB.key);
  });

  return processedGroups;
}

export function getNextSort(
  currentKey: DeviceSortKey,
  currentDirection: SortDirection,
  newKey: DeviceSortKey
): { key: DeviceSortKey; direction: SortDirection } {
  if (currentKey === newKey) {
    return {
      key: currentKey,
      direction: currentDirection === 'asc' ? 'desc' : 'asc',
    };
  }
  const startsDesc = newKey === 'first_seen' || newKey === 'last_seen' || newKey === 'count';
  return {
    key: newKey,
    direction: startsDesc ? 'desc' : 'asc',
  };
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

  const [sortKey, setSortKey] = useState<DeviceSortKey>('email');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

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

  const handleSort = (newKey: DeviceSortKey) => {
    const next = getNextSort(sortKey, sortDirection, newKey);
    setSortKey(next.key);
    setSortDirection(next.direction);
  };

  const sortIndicator = (field: DeviceSortKey) =>
    sortKey === field ? (sortDirection === 'asc' ? ' ^' : ' v') : '';

  const getAriaSort = (field: DeviceSortKey): 'ascending' | 'descending' | 'none' =>
    sortKey === field ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none';

  const rawGroups = useMemo(() => groupDevices(devices), [devices]);
  const sortedGroups = useMemo(
    () => sortDeviceGroups(rawGroups, sortKey, sortDirection),
    [rawGroups, sortKey, sortDirection]
  );

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
              {t('subscriptionClients.devices.app')}:
            </span>
            <span
              className="truncate text-slate-300"
              title={device.user_agent || undefined}
            >
              {device.app || '—'}
            </span>
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
      <td
        className="py-2 pr-3 pl-8 text-slate-200"
        title={device.user_agent || undefined}
      >
        {device.app || '—'}
      </td>
      <td className="py-2 pr-3 text-slate-200">{device.device_os || '—'}</td>
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

      {!loading && !error && sortedGroups.length === 0 && (
        <div className="py-8 text-center text-sm text-slate-400">
          {t('subscriptionClients.devices.empty')}
        </div>
      )}

      {!loading && !error && sortedGroups.length > 0 && (
        <>
          {/* Mobile view (< lg) */}
          <div className="mt-4 flex flex-col gap-3 lg:hidden">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 flex-1 items-center gap-1.5">
                <label
                  htmlFor="mobile-device-sort-key"
                  className="shrink-0 text-xs text-slate-400"
                >
                  {t('subscriptionClients.devices.sortBy')}:
                </label>
                <select
                  id="mobile-device-sort-key"
                  className="min-w-0 flex-1 rounded border border-cyan-500/20 bg-[#0f1420] px-2 py-1 text-xs text-slate-200 focus:border-cyan-400 focus:outline-none"
                  value={sortKey}
                  onChange={(e) => handleSort(e.target.value as DeviceSortKey)}
                >
                  <option value="email">{t('subscriptionClients.devices.subject')}</option>
                  <option value="count">{t('subscriptionClients.devices.used')}</option>
                  <option value="app">{t('subscriptionClients.devices.app')}</option>
                  <option value="os">{t('subscriptionClients.devices.os')}</option>
                  <option value="version">{t('subscriptionClients.devices.version')}</option>
                  <option value="model">{t('subscriptionClients.devices.model')}</option>
                  <option value="first_seen">{t('subscriptionClients.devices.firstSeen')}</option>
                  <option value="last_seen">{t('subscriptionClients.devices.lastSeen')}</option>
                </select>
              </div>
              <button
                type="button"
                className={cn(secondaryButtonClass, 'h-7 shrink-0 px-2 text-xs')}
                onClick={() => setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))}
                aria-label={
                  sortDirection === 'asc'
                    ? t('subscriptionClients.devices.sortAscending')
                    : t('subscriptionClients.devices.sortDescending')
                }
                title={
                  sortDirection === 'asc'
                    ? t('subscriptionClients.devices.sortAscending')
                    : t('subscriptionClients.devices.sortDescending')
                }
              >
                <span className="font-mono text-cyan-300">{sortDirection === 'asc' ? '↑' : '↓'}</span>
                <span className="text-[11px]">
                  {sortDirection === 'asc'
                    ? t('subscriptionClients.devices.directionAsc')
                    : t('subscriptionClients.devices.directionDesc')}
                </span>
              </button>
            </div>

            <div className="grid min-w-0 grid-cols-1 gap-3">
              {sortedGroups.map((group) => {
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
          </div>

          {/* Desktop view (>= lg) */}
          <div className="mt-4 hidden min-w-0 overflow-x-auto lg:block">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="border-b border-cyan-500/20 text-[11px] uppercase tracking-wider text-slate-400">
                <tr className="border-b border-cyan-500/10 bg-[#0f1420]/60">
                  <th colSpan={5} className="py-2 pr-3 pl-3" aria-sort={getAriaSort('email')}>
                    <button
                      type="button"
                      className={sortButtonClass}
                      onClick={() => handleSort('email')}
                    >
                      <span>{t('subscriptionClients.devices.subject')}</span>
                      <span>{sortIndicator('email')}</span>
                    </button>
                  </th>
                  <th colSpan={2} className="py-2 pr-2 text-right" aria-sort={getAriaSort('count')}>
                    <button
                      type="button"
                      className={cn(sortButtonClass, 'w-full justify-end')}
                      onClick={() => handleSort('count')}
                    >
                      <span>{t('subscriptionClients.devices.used')}</span>
                      <span>{sortIndicator('count')}</span>
                    </button>
                  </th>
                </tr>
                <tr>
                  <th className="py-2 pr-3 pl-8" aria-sort={getAriaSort('app')}>
                    <button
                      type="button"
                      className={sortButtonClass}
                      onClick={() => handleSort('app')}
                    >
                      <span>{t('subscriptionClients.devices.app')}</span>
                      <span>{sortIndicator('app')}</span>
                    </button>
                  </th>
                  <th className="py-2 pr-3" aria-sort={getAriaSort('os')}>
                    <button
                      type="button"
                      className={sortButtonClass}
                      onClick={() => handleSort('os')}
                    >
                      <span>{t('subscriptionClients.devices.os')}</span>
                      <span>{sortIndicator('os')}</span>
                    </button>
                  </th>
                  <th className="py-2 pr-3" aria-sort={getAriaSort('version')}>
                    <button
                      type="button"
                      className={sortButtonClass}
                      onClick={() => handleSort('version')}
                    >
                      <span>{t('subscriptionClients.devices.version')}</span>
                      <span>{sortIndicator('version')}</span>
                    </button>
                  </th>
                  <th className="py-2 pr-3" aria-sort={getAriaSort('model')}>
                    <button
                      type="button"
                      className={sortButtonClass}
                      onClick={() => handleSort('model')}
                    >
                      <span>{t('subscriptionClients.devices.model')}</span>
                      <span>{sortIndicator('model')}</span>
                    </button>
                  </th>
                  <th className="py-2 pr-3" aria-sort={getAriaSort('first_seen')}>
                    <button
                      type="button"
                      className={sortButtonClass}
                      onClick={() => handleSort('first_seen')}
                    >
                      <span>{t('subscriptionClients.devices.firstSeen')}</span>
                      <span>{sortIndicator('first_seen')}</span>
                    </button>
                  </th>
                  <th className="py-2 pr-3" aria-sort={getAriaSort('last_seen')}>
                    <button
                      type="button"
                      className={sortButtonClass}
                      onClick={() => handleSort('last_seen')}
                    >
                      <span>{t('subscriptionClients.devices.lastSeen')}</span>
                      <span>{sortIndicator('last_seen')}</span>
                    </button>
                  </th>
                  <th className="py-2 text-right pr-2">
                    <span>{t('subscriptionClients.devices.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-cyan-500/10">
                {sortedGroups.map((group) => {
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
                        <td colSpan={5} className="py-1.5 pr-3 pl-3">
                          <button
                            type="button"
                            className="flex min-w-0 items-center gap-2 text-left transition-colors hover:text-cyan-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
                            aria-expanded={expanded}
                            aria-label={
                              expanded
                                ? t('subscriptionClients.devices.collapseGroup', { subject: group.label })
                                : t('subscriptionClients.devices.expandGroup', { subject: group.label })
                            }
                            onClick={() => toggleGroupExpanded(group.key)}
                          >
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
                          </button>
                        </td>
                        <td colSpan={2} className="py-1.5 pr-2 text-right">
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
