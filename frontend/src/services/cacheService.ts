/**
 * Memory-based cache with TTL (Time-To-Live) support.
 * Provides hit/miss statistics and selective cache invalidation.
 */

interface CacheEntry<T> {
  data: T;
  expiresAt: number;
}

interface CacheStats {
  hits: number;
  misses: number;
  size: number;
}

class CacheService {
  private store = new Map<string, CacheEntry<unknown>>();
  private stats: CacheStats = { hits: 0, misses: 0, size: 0 };
  private setCount = 0;
  private static readonly SWEEP_INTERVAL = 50; // sweep every 50 set() calls

  /** Retrieve a cached value, or undefined if missing/expired. */
  get<T>(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) {
      this.stats.misses++;
      return undefined;
    }
    if (Date.now() > entry.expiresAt) {
      this.store.delete(key);
      this.stats.misses++;
      return undefined;
    }
    this.stats.hits++;
    return entry.data as T;
  }

  /** Store a value with a TTL (in milliseconds). Periodically sweeps expired entries. */
  set<T>(key: string, data: T, ttlMs: number): void {
    this.store.set(key, { data, expiresAt: Date.now() + ttlMs });
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
    } else {
      for (const key of this.store.keys()) {
        if (key.includes(pattern)) {
          this.store.delete(key);
        }
      }
    }
    this.stats.size = this.store.size;
  }

  /** Remove all entries that have passed their expiry time. */
  private sweepExpired(): void {
    const now = Date.now();
    for (const [key, entry] of this.store.entries()) {
      if (now > entry.expiresAt) {
        this.store.delete(key);
      }
    }
  }

  /** Return a snapshot of cache hit/miss statistics. */
  getStats(): Readonly<CacheStats> {
    return { ...this.stats };
  }
}

export const cacheService = new CacheService();
