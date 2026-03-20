/**
 * IndexedDB for Large-Scale Cache
 * Stores historical data and large payloads without affecting localStorage
 */

export interface IndexedDBStore {
  name: string;
  keyPath: string;
}

class IndexedDBManager {
  private dbName = 'sub_manager_cache_v1';
  private dbVersion = 1;
  private db: IDBDatabase | null = null;
  private stores: IndexedDBStore[] = [
    { name: 'traffic_history', keyPath: 'id' },
    { name: 'client_snapshots', keyPath: 'email' },
    { name: 'node_health', keyPath: 'node_id' },
  ];

  async init(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!('indexedDB' in window)) {
        console.warn('IndexedDB not supported');
        reject(new Error('IndexedDB not supported'));
        return;
      }

      const request = indexedDB.open(this.dbName, this.dbVersion);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        this.db = request.result;
        resolve();
      };

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        for (const store of this.stores) {
          if (!db.objectStoreNames.contains(store.name)) {
            const os = db.createObjectStore(store.name, { keyPath: store.keyPath });
            os.createIndex('timestamp', 'timestamp', { unique: false });
          }
        }
      };
    });
  }

  async set<T>(storeName: string, data: T & { timestamp: number }): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        reject(new Error('IndexedDB not initialized'));
        return;
      }

      const tx = this.db.transaction([storeName], 'readwrite');
      const store = tx.objectStore(storeName);
      const request = store.put(data);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve();
    });
  }

  async get<T>(storeName: string, key: any): Promise<T | null> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        reject(new Error('IndexedDB not initialized'));
        return;
      }

      const tx = this.db.transaction([storeName], 'readonly');
      const store = tx.objectStore(storeName);
      const request = store.get(key);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        resolve(request.result ?? null);
      };
    });
  }

  async query<T>(
    storeName: string,
    options: {
      limit?: number;
      offset?: number;
      olderThan?: number;
      newerThan?: number;
    } = {},
  ): Promise<T[]> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        reject(new Error('IndexedDB not initialized'));
        return;
      }

      const tx = this.db.transaction([storeName], 'readonly');
      const store = tx.objectStore(storeName);
      const timestampIndex = store.index('timestamp');

      let range: IDBKeyRange | undefined;
      if (options.olderThan || options.newerThan) {
        if (options.olderThan && options.newerThan) {
          range = IDBKeyRange.bound(options.newerThan, options.olderThan);
        } else if (options.olderThan) {
          range = IDBKeyRange.upperBound(options.olderThan);
        } else if (options.newerThan) {
          range = IDBKeyRange.lowerBound(options.newerThan);
        }
      }

      const request = range ? timestampIndex.getAll(range) : store.getAll();

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        let results = (request.result ?? []) as T[];
        if (options.offset) results = results.slice(options.offset);
        if (options.limit) results = results.slice(0, options.limit);
        resolve(results);
      };
    });
  }

  async delete(storeName: string, key: any): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        reject(new Error('IndexedDB not initialized'));
        return;
      }

      const tx = this.db.transaction([storeName], 'readwrite');
      const store = tx.objectStore(storeName);
      const request = store.delete(key);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve();
    });
  }

  async clear(storeName: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        reject(new Error('IndexedDB not initialized'));
        return;
      }

      const tx = this.db.transaction([storeName], 'readwrite');
      const store = tx.objectStore(storeName);
      const request = store.clear();

      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve();
    });
  }

  async pruneOlderThan(storeName: string, ageMs: number): Promise<number> {
    const cutoff = Date.now() - ageMs;
    const results = await this.query<any>(storeName, { olderThan: cutoff });

    for (const item of results) {
      await this.delete(storeName, item[this.stores.find((s) => s.name === storeName)?.keyPath || 'id']);
    }

    return results.length;
  }
}

export const indexedDBManager = new IndexedDBManager();

// Initialize on first import
indexedDBManager.init().catch(() => {
  console.warn('Failed to initialize IndexedDB');
});
