// Public Service Worker (sw.js)
// Place this file in public/sw.js

const CACHE_NAME = 'sub-manager-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/index.html',
];

// Install: cache critical assets
self.addEventListener('install', (event) => {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Caching assets');
      return cache.addAll(ASSETS_TO_CACHE).catch(() => {
        // Silently fail if offline during install
        console.warn('[SW] Failed to cache all assets during install');
      });
    })
  );
  self.skipWaiting();
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('[SW] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch: network-first strategy for API, cache-first for assets
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // API calls: network first, fallback to nearest stale cache
  if (url.pathname.startsWith('/api/')) {
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
        if (networkResponse.ok) {
          const clone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, clone);
          });
        }
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
          // Get pending mutations from IndexedDB
          const db = await new Promise((resolve, reject) => {
            const request = indexedDB.open('sub_manager_mutations', 1);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });

          console.log('[SW] Background sync for mutations triggered');
          // Mutations will be queued in IndexedDB and synced here
        } catch (err) {
          console.error('[SW] Background sync failed:', err);
          throw err;
        }
      })()
    );
  }
});

console.log('[SW] Service Worker loaded');
