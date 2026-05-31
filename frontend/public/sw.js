// Public Service Worker (sw.js)
// CACHE_VER is stamped at build time by build-and-publish-frontend.sh
// so every deploy gets a fresh cache name and stale assets are evicted.
const CACHE_VER = '__CACHE_VER__';
const CACHE_NAME = `sub-manager-${CACHE_VER}`;
const scopeUrl = new URL(self.registration.scope);
const basePath = scopeUrl.pathname.replace(/\/$/, '');
const withBase = (path) => `${basePath}${path}`;
const ASSETS_TO_CACHE = [
  withBase('/'),
  withBase('/index.html'),
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

/**
 * Returns true when the response content-type matches what the URL implies.
 * Prevents caching nginx's HTML SPA-fallback when an asset file is temporarily
 * missing after a deploy (root cause of the white-screen-on-first-visit bug).
 */
function isResponseTypeValid(request, response) {
  const ct = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
  const url = request.url.toLowerCase();
  if (url.includes('.css')) return ct === 'text/css';
  if (url.includes('.js') || url.includes('.mjs')) {
    return ct === 'application/javascript' || ct === 'text/javascript';
  }
  return true;
}

// Fetch: network-first strategy for API, cache-first for assets
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  const apiPrefix = withBase('/api/');

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // API calls: network first, fallback to nearest stale cache
  if (url.pathname.startsWith(apiPrefix)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, clone);
            });
          }
          return response;
        })
        .catch(() => {
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

  // Static assets: cache-first, but only cache responses whose content-type
  // actually matches the resource type — never cache an HTML fallback as CSS/JS.
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((networkResponse) => {
        if (networkResponse.ok && isResponseTypeValid(request, networkResponse)) {
          const clone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, clone);
          });
        }
        return networkResponse;
      }).catch(() => {
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
