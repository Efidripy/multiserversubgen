/**
 * Memory-based cache with TTL (Time-To-Live) support.
 * Provides hit/miss statistics and selective cache invalidation.
 */

interface CacheEntry<T> {
  data: T;
  expiresAt: number;
  tags: string[];
}

interface CacheStats {
  hits: number;
  misses: number;
  size: number;
}

class CacheService {
  private store = new Map<string, CacheEntry<unknown>>();
  private tagIndex = new Map<string, Set<string>>();
  private stats: CacheStats = { hits: 0, misses: 0, size: 0 };
  private setCount = 0;
  private static readonly SWEEP_INTERVAL = 50; // sweep every 50 set() calls
  private static readonly MAX_ENTRIES = 1000;

  private removeEntry(key: string): void {
    const existing = this.store.get(key);
    if (existing) {
      for (const tag of existing.tags) {
        const keys = this.tagIndex.get(tag);
        if (!keys) continue;
        keys.delete(key);
        if (keys.size === 0) {
          this.tagIndex.delete(tag);
        }
      }
    }
    this.store.delete(key);
  }

  /** Retrieve a cached value, or undefined if missing/expired. */
  get<T>(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) {
      this.stats.misses++;
      return undefined;
    }
    if (Date.now() > entry.expiresAt) {
      this.removeEntry(key);
      this.stats.misses++;
      return undefined;
    }
    this.stats.hits++;
    return entry.data as T;
  }

  /** Store a value with a TTL (in milliseconds). Periodically sweeps expired entries. */
  set<T>(key: string, data: T, ttlMs: number, tags: string[] = []): void {
    this.removeEntry(key);

    const normalizedTags = Array.from(new Set(tags.filter(Boolean)));
    this.store.set(key, { data, expiresAt: Date.now() + ttlMs, tags: normalizedTags });

    normalizedTags.forEach((tag) => {
      const keys = this.tagIndex.get(tag) ?? new Set<string>();
      keys.add(key);
      this.tagIndex.set(tag, keys);
    });

    while (this.store.size > CacheService.MAX_ENTRIES) {
      const oldestKey = this.store.keys().next().value as string | undefined;
      if (!oldestKey) break;
      this.removeEntry(oldestKey);
    }

    this.setCount++;
    if (this.setCount % CacheService.SWEEP_INTERVAL === 0) {
      this.sweepExpired();
    }
    this.stats.size = this.store.size;
  }

  /**
   * Invalidate cache entries whose keys contain the given pattern.
   * If no pattern is provided, the entire cache is cleared.
   */
  invalidate(pattern?: string): void {
    if (!pattern) {
      this.store.clear();
      this.tagIndex.clear();
    } else {
      for (const key of this.store.keys()) {
        if (key.includes(pattern)) {
          this.removeEntry(key);
        }
      }
    }
    this.stats.size = this.store.size;
  }

  /** Invalidate all entries associated with the provided cache tag. */
  invalidateByTag(tag: string): void {
    const keys = this.tagIndex.get(tag);
    if (!keys || keys.size === 0) return;

    Array.from(keys).forEach((key) => this.removeEntry(key));
    this.tagIndex.delete(tag);
    this.stats.size = this.store.size;
  }

  /** Remove all entries that have passed their expiry time. */
  private sweepExpired(): void {
    const now = Date.now();
    for (const [key, entry] of this.store.entries()) {
      if (now > entry.expiresAt) {
        this.removeEntry(key);
      }
    }
    this.stats.size = this.store.size;
  }

  /** Return a snapshot of cache hit/miss statistics. */
  getStats(): Readonly<CacheStats> {
    return { ...this.stats };
  }
}

export const cacheService = new CacheService();

if (typeof window !== 'undefined') {
  window.addEventListener('sub-manager:cache-clear', () => cacheService.invalidate());
}
