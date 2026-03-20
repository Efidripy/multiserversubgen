export type StaleCacheEnvelope<T> = {
  ts: number;
  data: T;
};

export type StaleCacheReadResult<T> = {
  data: T | null;
  isFresh: boolean;
  ts: number;
};

export function readStaleCache<T>(key: string, maxAgeMs: number): StaleCacheReadResult<T> {
  try {
    const raw = localStorage.getItem(key);
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
    localStorage.setItem(key, JSON.stringify(envelope));
  } catch {
    // ignore localStorage write failures
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
