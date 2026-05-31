/**
 * Service Worker Registration & Management
 * Handles offline support, asset caching, and background sync
 */
import { devLog } from '../utils/devLogger';

export interface ServiceWorkerOptions {
  workerPath?: string;
  onReady?: () => void;
  onUpdate?: () => void;
  onOffline?: () => void;
}

class ServiceWorkerManager {
  private registration: ServiceWorkerRegistration | null = null;
  private isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true;

  async register(options: ServiceWorkerOptions = {}): Promise<void> {
    if (!('serviceWorker' in navigator)) {
      console.warn('Service Workers not supported');
      return;
    }

    const baseUrl = import.meta.env.BASE_URL || '/';
    const workerPath = options.workerPath || `${baseUrl.replace(/\/?$/, '/')}sw.js`;

    try {
      this.registration = await navigator.serviceWorker.register(workerPath, {
        scope: baseUrl,
      });

      // Check for updates periodically
      setInterval(() => {
        this.registration?.update();
      }, 60000); // Check every 60 seconds

      // Listen for updates
      this.registration.addEventListener('updatefound', () => {
        const newWorker = this.registration!.installing;
        newWorker?.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            devLog('[SW] Update available');
            options.onUpdate?.();
          }
        });
      });

      devLog('[SW] Registered successfully');
      options.onReady?.();
    } catch (error) {
      console.error('[SW] Registration failed:', error);
    }

    // Monitor online/offline state
    window.addEventListener('online', () => {
      this.isOnline = true;
      devLog('[SW] Back online');
    });

    window.addEventListener('offline', () => {
      this.isOnline = false;
      devLog('[SW] Offline');
      options.onOffline?.();
    });
  }

  async unregister(): Promise<void> {
    if (this.registration) {
      await this.registration.unregister();
      this.registration = null;
    }
  }

  async skipWaiting(): Promise<void> {
    if (this.registration?.waiting) {
      this.registration.waiting.postMessage({ type: 'SKIP_WAITING' });
    }
  }

  isOnlineStatus(): boolean {
    return this.isOnline;
  }
}

export const swManager = new ServiceWorkerManager();

/**
 * Content of the Service Worker file (sw.js)
 * This code should be served as /public/sw.js
 */
export const SERVICE_WORKER_CONTENT = `
const CACHE_NAME = 'sub-manager-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/index.html',
  '/styles.css',
];

// Install: cache critical assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    }).catch(() => {
      // Silently fail if offline
    })
  );
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Fetch: network-first strategy for API, cache-first for assets
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  const basePath = self.registration && self.registration.scope
    ? new URL(self.registration.scope).pathname.replace(/\/$/, '')
    : '';
  const apiPrefix = basePath + '/' + 'api' + '/';

  // API calls: network first, fallback to nearest stale cache
  if (url.pathname.startsWith(apiPrefix)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Cache successful API responses
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, clone);
            });
          }
          return response;
        })
        .catch(() => {
          // Return cached response if offline
          return caches.match(request).then((cachedResponse) => {
            return cachedResponse || new Response('Offline - no cache available', {
              status: 503,
              statusText: 'Service Unavailable',
            });
          });
        })
    );
    return;
  }

  // Static assets: cache first, fallback to network
  event.respondWith(
    caches.match(request).then((response) => {
      return response || fetch(request).then((networkResponse) => {
        // Cache new responses
        const clone = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(request, clone);
        });
        return networkResponse;
      }).catch(() => {
        // Return a fallback response
        return new Response('Not found', { status: 404 });
      });
    })
  );
});

// Background sync for offline mutations
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-mutations') {
    event.waitUntil(
      (async () => {
        try {
          const db = await new Promise((resolve, reject) => {
            const request = indexedDB.open('sub_manager_mutations');
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });

          // Process pending mutations here
        } catch (err) {
          console.error('[SW] Background sync failed:', err);
          throw err;
        }
      })()
    );
  }
});
`;
