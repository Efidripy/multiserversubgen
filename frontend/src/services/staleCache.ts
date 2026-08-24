export type StaleCacheEnvelope<T> = {
  ts: number;
  data: T;
};

export type StaleCacheReadResult<T> = {
  data: T | null;
  isFresh: boolean;
  ts: number;
};

const SESSION_SNAPSHOT_CACHE_KEYS = [
  'sub_manager_header_summary_cache_v1',
  'sub_manager_clients_page_cache_v1',
  'sub_manager_inbounds_page_cache_v1',
  'sub_manager_traffic_stats_cache_v3',
] as const;

const LOCAL_SNAPSHOT_CACHE_KEYS = [
  'sub_manager_node_list_cache_v1',
  'sub_manager_node_status_cache_v1',
] as const;

const DASHBOARD_OVERVIEW_CACHE_PREFIX = 'sub-manager:dashboard-overview:v1:';

/**
 * Remove data snapshots that must never cross an authenticated session boundary.
 * UI preferences intentionally remain untouched.
 */
export function clearManagerSnapshotCaches(): void {
  try {
    for (const key of SESSION_SNAPSHOT_CACHE_KEYS) {
      sessionStorage.removeItem(key);
    }

    for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(DASHBOARD_OVERVIEW_CACHE_PREFIX)) {
        sessionStorage.removeItem(key);
      }
    }
  } catch {
    // Storage availability is an enhancement; logout must always complete.
  }

  try {
    for (const key of LOCAL_SNAPSHOT_CACHE_KEYS) {
      localStorage.removeItem(key);
    }
  } catch {
    // Storage availability is an enhancement; logout must always complete.
  }
}

export function readStaleCache<T>(key: string, maxAgeMs: number): StaleCacheReadResult<T> {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return { data: null, isFresh: false, ts: 0 };

    const parsed = JSON.parse(raw) as StaleCacheEnvelope<T>;
    if (!parsed || typeof parsed.ts !== 'number') {
      return { data: null, isFresh: false, ts: 0 };
    }

    const age = Date.now() - parsed.ts;
    return {
      data: parsed.data ?? null,
      isFresh: age <= maxAgeMs,
      ts: parsed.ts,
    };
  } catch {
    return { data: null, isFresh: false, ts: 0 };
  }
}

export function writeStaleCache<T>(key: string, data: T): void {
  try {
    const envelope: StaleCacheEnvelope<T> = { ts: Date.now(), data };
    sessionStorage.setItem(key, JSON.stringify(envelope));
  } catch {
    // Ignore session storage write failures.
  }
}

export function mergeStaleCacheRecord<T extends Record<string, unknown>>(
  key: string,
  patch: Partial<T>
): void {
  try {
    const current = readStaleCache<T>(key, Number.MAX_SAFE_INTEGER).data ?? ({} as T);
    writeStaleCache<T>(key, { ...current, ...patch } as T);
  } catch {
    // ignore merge failures
  }
}
