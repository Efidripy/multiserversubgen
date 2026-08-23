import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  getDashboardOverview,
  type DashboardFleetNode,
  type DashboardOverviewData,
  type DashboardSummaryData,
  type DashboardTrafficPeriod,
} from '../api/dashboard';
import { NODES_CHANGED_EVENT } from '../api/nodes';
import { getAuth } from '../auth';

const STORAGE_PREFIX = 'sub-manager:dashboard-overview:v1';
const REFRESH_INTERVAL_MS = 60_000;

type StoredDashboardOverview = {
  savedAt: number;
  period: DashboardTrafficPeriod;
  overview: DashboardOverviewData;
};

export type DashboardData = {
  summary: DashboardSummaryData | null;
  fleet: DashboardFleetNode[];
  period: DashboardTrafficPeriod;
  loading: boolean;
  stale: boolean;
  lastUpdated: Date | null;
  setPeriod: (period: DashboardTrafficPeriod) => void;
  refresh: () => Promise<void>;
};

const DashboardDataContext = createContext<DashboardData | null>(null);

const storageKey = () => `${STORAGE_PREFIX}:${encodeURIComponent(getAuth().username || 'anonymous')}`;

const readStored = (): StoredDashboardOverview | null => {
  try {
    const raw = window.sessionStorage.getItem(storageKey());
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredDashboardOverview;
    if (!parsed || !parsed.overview || !Array.isArray(parsed.overview.fleet) || !parsed.savedAt) return null;
    return parsed;
  } catch {
    return null;
  }
};

const saveStored = (entry: StoredDashboardOverview) => {
  try {
    window.sessionStorage.setItem(storageKey(), JSON.stringify(entry));
  } catch {
    // Cache persistence is an enhancement; quota/privacy settings must not block Dashboard.
  }
};

export function DashboardDataProvider({ children }: { children: ReactNode }) {
  const [stored] = useState<StoredDashboardOverview | null>(() => readStored());
  const [period, setPeriod] = useState<DashboardTrafficPeriod>(stored?.period ?? 'all_time');
  const [overview, setOverview] = useState<DashboardOverviewData | null>(stored?.overview ?? null);
  const [loading, setLoading] = useState(!stored);
  const [stale, setStale] = useState(Boolean(stored));
  const [lastUpdated, setLastUpdated] = useState<Date | null>(stored ? new Date(stored.savedAt) : null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getDashboardOverview(period);
      const savedAt = Date.now();
      setOverview(next);
      setLastUpdated(new Date(savedAt));
      setStale(false);
      saveStored({ savedAt, period, overview: next });
    } catch {
      // Keep an already rendered snapshot visible when a background refresh
      // fails; the next interval or explicit refresh can recover it.
      setStale(true);
    } finally {
      setLoading(false);
    }
  }, [period]);

  const selectPeriod = useCallback((nextPeriod: DashboardTrafficPeriod) => {
    setStale(true);
    setPeriod(nextPeriod);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const handleNodesChanged = () => void refresh();
    window.addEventListener(NODES_CHANGED_EVENT, handleNodesChanged);
    return () => window.removeEventListener(NODES_CHANGED_EVENT, handleNodesChanged);
  }, [refresh]);

  const value = useMemo<DashboardData>(() => {
    return {
      summary: overview?.summary ?? null,
      fleet: overview?.fleet ?? [],
      period,
      loading,
      stale,
      lastUpdated,
      setPeriod: selectPeriod,
      refresh,
    };
  }, [lastUpdated, loading, overview, period, refresh, selectPeriod, stale]);

  return <DashboardDataContext.Provider value={value}>{children}</DashboardDataContext.Provider>;
}

export function useDashboardData(): DashboardData | null {
  return useContext(DashboardDataContext);
}
