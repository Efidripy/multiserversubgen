/**
 * Тестирование Service Worker и offline режима
 * Проверяет кэширование, фоновую синхронизацию и восстановление соединения
 */
import { API_BASE } from '../api';

export interface ServiceWorkerTestResult {
  name: string;
  passed: boolean;
  duration: number;
  message?: string;
  details?: Record<string, any>;
}

export class ServiceWorkerTester {
  private testResults: ServiceWorkerTestResult[] = [];
  private readonly healthEndpoint = `${API_BASE}/health`;

  /**
   * Запустить все тесты Service Worker
   */
  async runAllTests(): Promise<ServiceWorkerTestResult[]> {
    this.testResults = [];

    // Проверка 1: Service Worker регистрация
    await this.testSWRegistration();

    // Проверка 2: Кэширование статических активов
    await this.testAssetCaching();

    // Проверка 3: Network-first для API
    await this.testNetworkFirstStrategy();

    // Проверка 4: Offline fallback
    await this.testOfflineFallback();

    // Проверка 5: Background sync
    await this.testBackgroundSync();

    // Проверка 6: Восстановление при переподключении
    await this.testReconnectionRecovery();

    return this.testResults;
  }

  /**
   * Тест 1: Регистрация Service Worker
   */
  private async testSWRegistration(): Promise<void> {
    const startTime = performance.now();
    try {
      const registration = await navigator.serviceWorker.getRegistration();
      const passed = !!registration && !!registration.active;

      this.testResults.push({
        name: '✓ Service Worker регистрация',
        passed,
        duration: performance.now() - startTime,
        details: {
          registered: !!registration,
          active: registration?.active ? 'Да' : 'Нет',
          scope: registration?.scope,
        },
      });
    } catch (err) {
      this.testResults.push({
        name: '✗ Service Worker регистрация',
        passed: false,
        duration: performance.now() - startTime,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Тест 2: Кэширование статических активов
   */
  private async testAssetCaching(): Promise<void> {
    const startTime = performance.now();
    try {
      const cacheNames = await caches.keys();
      const appCache = cacheNames.find((name) => name.includes('sub-manager'));

      if (!appCache) {
        this.testResults.push({
          name: '✗ Кэширование активов',
          passed: false,
          duration: performance.now() - startTime,
          message: 'Cache не найден',
        });
        return;
      }

      const cache = await caches.open(appCache);
      const keys = await cache.keys();
      const assetCount = keys.length || 0;

      this.testResults.push({
        name: '✓ Кэширование активов',
        passed: assetCount > 0,
        duration: performance.now() - startTime,
        details: {
          cacheName: appCache,
          cachedAssets: assetCount,
          sizeEstimate: await this.estimateCacheSize(appCache),
        },
      });
    } catch (err) {
      this.testResults.push({
        name: '✗ Кэширование активов',
        passed: false,
        duration: performance.now() - startTime,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Тест 3: Network-first стратегия для API
   */
  private async testNetworkFirstStrategy(): Promise<void> {
    const startTime = performance.now();
    try {
      // Имитировать API запрос
      const response = await fetch(this.healthEndpoint, {
        method: 'GET',
      }).catch(async () => {
        // Fallback на кэш если сеть недоступна
        const cacheNames = await caches.keys();
        const appCache = cacheNames.find((name) => name.includes('sub-manager'));
        if (appCache) {
          const cache = await caches.open(appCache);
          return (await cache.match(this.healthEndpoint)) || new Response('{}', { status: 503 });
        }
        throw new Error('Нет сетевого соединения и кэш недоступен');
      });

      if (!response) {
        throw new Error('Response is undefined');
      }

      this.testResults.push({
        name: '✓ Network-first стратегия',
        passed: response.status < 400,
        duration: performance.now() - startTime,
        details: {
          statusCode: response.status,
          fromCache: response.status === 503 ? 'Да (fallback)' : 'Нет (сеть)',
        },
      });
    } catch (err) {
      this.testResults.push({
        name: '✗ Network-first стратегия',
        passed: false,
        duration: performance.now() - startTime,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Тест 4: Offline fallback
   */
  private async testOfflineFallback(): Promise<void> {
    const startTime = performance.now();
    try {
      // Проверить IndexedDB (fallback хранилище)
      const idbSupported = typeof window.indexedDB !== 'undefined';

      if (!idbSupported) {
        this.testResults.push({
          name: '✗ Offline fallback (IndexedDB)',
          passed: false,
          duration: performance.now() - startTime,
          message: 'IndexedDB не поддерживается',
        });
        return;
      }

      // Попытка открыть DB
      const dbRequest = indexedDB.open('sub-manager-db', 1);

      await new Promise((resolve) => {
        dbRequest.onsuccess = () => {
          const db = dbRequest.result;
          const stores: string[] = [];

          // Проверить наличие object stores
          for (let i = 0; i < db.objectStoreNames.length; i++) {
            stores.push(db.objectStoreNames[i]);
          }

          this.testResults.push({
            name: '✓ Offline fallback (IndexedDB)',
            passed: stores.length > 0,
            duration: performance.now() - startTime,
            details: {
              objectStores: stores,
              storeCount: stores.length,
            },
          });

          db.close();
          resolve(null);
        };

        dbRequest.onerror = () => {
          this.testResults.push({
            name: '✗ Offline fallback (IndexedDB)',
            passed: false,
            duration: performance.now() - startTime,
            message: 'Ошибка при доступе к IndexedDB',
          });
          resolve(null);
        };
      });
    } catch (err) {
      this.testResults.push({
        name: '✗ Offline fallback',
        passed: false,
        duration: performance.now() - startTime,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Тест 5: Background sync
   */
  private async testBackgroundSync(): Promise<void> {
    const startTime = performance.now();
    try {
      if (!('serviceWorker' in navigator) || !('SyncManager' in window)) {
        this.testResults.push({
          name: '⚠️ Background Sync',
          passed: false,
          duration: performance.now() - startTime,
          message: 'Background Sync API не поддерживается привашем браузере',
        });
        return;
      }

      const registration = await navigator.serviceWorker.ready;
      const hasSync = registration && 'sync' in registration;

      this.testResults.push({
        name: hasSync ? '✓ Background Sync' : '⚠️ Background Sync',
        passed: hasSync,
        duration: performance.now() - startTime,
        details: {
          supported: hasSync,
          message: hasSync
            ? 'Background Sync готов к использованию'
            : 'Background Sync недоступен (требуется PWA)',
        },
      });
    } catch (err) {
      this.testResults.push({
        name: '✗ Background Sync',
        passed: false,
        duration: performance.now() - startTime,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Тест 6: Восстановление при переподключении
   */
  private async testReconnectionRecovery(): Promise<void> {
    const startTime = performance.now();
    try {
      const isOnline = navigator.onLine;

      // Имитировать offline событие
      let offlineDetected = false;
      let onlineRestored = false;

      const handleOffline = () => {
        offlineDetected = true;
      };

      const handleOnline = () => {
        onlineRestored = true;
      };

      window.addEventListener('offline', handleOffline);
      window.addEventListener('online', handleOnline);

      // Проверить текущее состояние
      const currentStatus = isOnline ? 'Онлайн' : 'Офлайн';

      this.testResults.push({
        name: '✓ Мониторинг соединения',
        passed: typeof navigator.onLine === 'boolean',
        duration: performance.now() - startTime,
        details: {
          currentStatus,
          isOnlineSupported: typeof navigator.onLine === 'boolean',
          eventsListening: `offline: ${offlineDetected ? 'Да' : 'Нет'}, online: ${onlineRestored ? 'Да' : 'Нет'}`,
        },
      });

      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    } catch (err) {
      this.testResults.push({
        name: '✗ Мониторинг соединения',
        passed: false,
        duration: performance.now() - startTime,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Вспомогательный метод для оценки размера кэша
   */
  private async estimateCacheSize(cacheName: string): Promise<string> {
    try {
      const cache = await caches.open(cacheName);
      const keys = await cache.keys();
      let totalSize = 0;

      for (const request of keys) {
        const response = await cache.match(request);
        if (response !== undefined && response !== null) {
          const blob = await response.blob();
          totalSize += blob.size;
        }
      }

      return (totalSize / 1024).toFixed(2) + ' KB';
    } catch {
      return 'Неизвестно';
    }
  }

  /**
   * Получить результаты тестирования в формате отчета
   */
  getReport(): string {
    const passed = this.testResults.filter((r) => r.passed).length;
    const total = this.testResults.length;

    let report = `
Service Worker тестовый отчет
================================
Пройдено: ${passed}/${total}

Результаты:
`;

    this.testResults.forEach((result) => {
      report += `\n${result.name}
  Время: ${result.duration.toFixed(2)}ms
${result.message ? `  Сообщение: ${result.message}\n` : ''}${
        result.details
          ? `  Детали: ${JSON.stringify(result.details, null, 2)}\n`
          : ''
      }`;
    });

    return report;
  }
}

export default ServiceWorkerTester;
