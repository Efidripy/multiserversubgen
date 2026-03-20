/**
 * Code Splitting & Lazy Loading Utilities
 * Enables dynamic imports and route-based code splitting
 */

import React from 'react';

/**
 * Lazy load a component with fallback UI
 */
export function lazyComponent<T extends React.ComponentType<any>>(
  importFunc: () => Promise<{ default: T }>,
  _fallback: React.ReactNode = <div>Loading...</div>,
): React.LazyExoticComponent<T> {
  return React.lazy(() => importFunc());
}

/**
 * Suspense wrapper component
 */
export const SuspenseBoundary: React.FC<{
  children: React.ReactNode;
  fallback?: React.ReactNode;
  onError?: (error: Error) => void;
}> = ({ children, fallback = <div>Loading...</div> }) => {
  return (
    <React.Suspense fallback={fallback}>
      {children}
    </React.Suspense>
  );
};

/**
 * Preload a component before it's needed
 */
export function preloadComponent<T extends React.ComponentType<any>>(
  importFunc: () => Promise<{ default: T }>,
): Promise<{ default: T }> {
  return importFunc();
}

/**
 * Hook to preload multiple components on idle
 */
export function useIdlePreload(importFuncs: Array<() => Promise<any>>) {
  React.useEffect(() => {
    if ('requestIdleCallback' in window) {
      requestIdleCallback(() => {
        importFuncs.forEach((importFunc) => {
          importFunc().catch(() => {
            console.warn('Failed to preload component');
          });
        });
      });
    } else {
      // Fallback to setTimeout
      setTimeout(() => {
        importFuncs.forEach((importFunc) => {
          importFunc().catch(() => {
            console.warn('Failed to preload component');
          });
        });
      }, 2000);
    }
  }, [importFuncs]);
}

/**
 * Code splitting strategy: split by route
 * These routes should be imported on-demand using React.lazy()
 */
export const CODE_SPLIT_ROUTES: Record<string, () => Promise<any>> = {
  // Configure your lazy-loaded routes here
  // Example: Dashboard: () => import(/* webpackChunkName: "dashboard" */ './pages/Dashboard'),
};

/**
 * Predictive preload based on user interaction
 */
export function usePredictivePreload(currentRoute: string) {
  React.useEffect(() => {
    // Predict next routes based on navigation patterns
    const predictedRoutes: Record<string, string[]> = {
      '/dashboard': ['/analytics', '/clients'],
      '/clients': ['/traffic-stats', '/dashboard'],
      '/settings': ['/dashboard'],
    };

    const nextRoutes = predictedRoutes[currentRoute] || [];

    // Preload likely next route on idle
    nextRoutes.forEach((route) => {
      const importFunc = Object.values(CODE_SPLIT_ROUTES).find(() => {
        // Match route to import function
        const name = route.split('/')[1];
        return Object.keys(CODE_SPLIT_ROUTES).some((key) => key.toLowerCase().includes(name));
      });

      if (importFunc && 'requestIdleCallback' in window) {
        requestIdleCallback(() => {
          importFunc().catch(() => {
            // Silently fail
          });
        });
      }
    });
  }, [currentRoute]);
}

/**
 * Monitor chunk loading performance
 */
export function onChunkLoad(chunkName: string, duration: number) {
  console.log(`[CodeSplit] Loaded chunk "${chunkName}" in ${duration.toFixed(2)}ms`);
  // TODO: Send to analytics
}

/**
 * Wrap lazy component with chunk load tracking
 */
export function trackedLazyComponent<T extends React.ComponentType<any>>(
  chunkName: string,
  importFunc: () => Promise<{ default: T }>,
  _fallback: React.ReactNode = <div>Loading {chunkName}...</div>,
): React.LazyExoticComponent<T> {
  const startTime = performance.now();

  return React.lazy(async () => {
    const result = await importFunc();
    const duration = performance.now() - startTime;
    onChunkLoad(chunkName, duration);
    return result;
  });
}
