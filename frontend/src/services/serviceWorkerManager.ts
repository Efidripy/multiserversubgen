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
  private updateTimer: number | null = null;

  private appScopeUrl(): URL {
    const baseUrl = import.meta.env.BASE_URL || '/';
    return new URL(baseUrl, window.location.href);
  }

  private ownedWorkerUrl(): URL {
    return new URL('sw.js', this.appScopeUrl());
  }

  async register(options: ServiceWorkerOptions = {}): Promise<void> {
    if (!('serviceWorker' in navigator)) {
      console.warn('Service Workers not supported');
      return;
    }

    const scopeUrl = this.appScopeUrl();
    const workerPath = options.workerPath || this.ownedWorkerUrl().href;

    try {
      this.registration = await navigator.serviceWorker.register(workerPath, {
        scope: scopeUrl.pathname,
      });

      // Check for updates periodically
      if (this.updateTimer !== null) window.clearInterval(this.updateTimer);
      this.updateTimer = window.setInterval(() => {
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
    if (this.updateTimer !== null) {
      window.clearInterval(this.updateTimer);
      this.updateTimer = null;
    }
    const expectedScope = this.appScopeUrl().href;
    const expectedWorker = this.ownedWorkerUrl().href;
    if (this.registration) {
      if (this.registration.scope === expectedScope) {
        await this.registration.unregister();
      }
      this.registration = null;
      return;
    }

    if ('serviceWorker' in navigator && navigator.serviceWorker.getRegistrations) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      const owned = registrations.filter((registration) => {
        const scriptUrl = registration.active?.scriptURL
          || registration.installing?.scriptURL
          || registration.waiting?.scriptURL;
        return registration.scope === expectedScope && scriptUrl === expectedWorker;
      });
      await Promise.all(owned.map((registration) => registration.unregister()));
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
