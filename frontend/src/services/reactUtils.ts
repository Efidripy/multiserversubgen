/**
 * React Utilities for Performance Optimization
 * Custom hooks and utilities for memoization and optimization
 */

import React, { useMemo, useCallback, useRef } from 'react';

/**
 * Deep comparison for props (for React.memo)
 */
export function shallowEqual<T extends Record<string, any>>(obj1: T, obj2: T): boolean {
  const keys1 = Object.keys(obj1);
  const keys2 = Object.keys(obj2);

  if (keys1.length !== keys2.length) {
    return false;
  }

  for (const key of keys1) {
    if (obj1[key] !== obj2[key]) {
      return false;
    }
  }

  return true;
}

/**
 * Custom hook for sorted/filtered data with memoization
 */
export function useSortedFilteredData<T extends Record<string, any>>(
  data: T[],
  filters: Record<string, any>,
  sortBy: keyof T,
  sortOrder: 'asc' | 'desc' = 'asc',
): T[] {
  return useMemo(() => {
    let filtered = data;

    // Apply filters
    for (const [key, value] of Object.entries(filters)) {
      if (!value) continue;
      if (typeof value === 'string') {
        filtered = filtered.filter((item) =>
          String(item[key]).toLowerCase().includes(String(value).toLowerCase()),
        );
      } else if (typeof value === 'function') {
        filtered = filtered.filter(value);
      } else {
        filtered = filtered.filter((item) => item[key] === value);
      }
    }

    // Sort
    return filtered.sort((a, b) => {
      const aVal = a[sortBy];
      const bVal = b[sortBy];

      if (aVal === bVal) return 0;

      const cmp = aVal < bVal ? -1 : 1;
      return sortOrder === 'asc' ? cmp : -cmp;
    });
  }, [data, filters, sortBy, sortOrder]);
}

/**
 * Hook to track previous value
 */
export function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T>();
  React.useEffect(() => {
    ref.current = value;
  }, [value]);
  return ref.current;
}

/**
 * Hook for debounced callbacks
 */
export function useDebouncedCallback<T extends (...args: any[]) => any>(
  callback: T,
  delay: number,
): (...args: Parameters<T>) => void {
  const timeoutRef = useRef<number | null>(null);

  return useCallback(
    (...args: Parameters<T>) => {
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = window.setTimeout(() => {
        callback(...args);
      }, delay);
    },
    [callback, delay],
  );
}

/**
 * Hook for throttled callbacks
 */
export function useThrottledCallback<T extends (...args: any[]) => any>(
  callback: T,
  intervalMs: number,
): (...args: Parameters<T>) => void {
  const lastRunRef = useRef(0);

  return useCallback(
    (...args: Parameters<T>) => {
      const now = Date.now();
      if (now - lastRunRef.current >= intervalMs) {
        lastRunRef.current = now;
        callback(...args);
      }
    },
    [callback, intervalMs],
  );
}

/**
 * Export a higher-order component for creating memoized list items
 */
export function createMemoListItem<T extends Record<string, any>>(
  Component: React.ComponentType<{ item: T; index: number }>
) {
  return React.memo(Component, (prevProps, nextProps) => {
    return prevProps.item === nextProps.item && prevProps.index === nextProps.index;
  });
}

/**
 * Virtual scrolling for large lists
 * Renders only visible items
 */
export function useVirtualScroll(
  items: any[],
  containerHeight: number,
  itemHeight: number,
  options: { overscan?: number } = {},
) {
  const overscan = options.overscan ?? 3;
  const [scrollTop, setScrollTop] = React.useState(0);

  const visibleStartIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
  const visibleEndIndex = Math.min(
    items.length,
    Math.ceil((scrollTop + containerHeight) / itemHeight) + overscan,
  );

  const visibleItems = items.slice(visibleStartIndex, visibleEndIndex);
  const offsetY = visibleStartIndex * itemHeight;

  return {
    visibleItems,
    visibleStartIndex,
    visibleEndIndex,
    offsetY,
    onScroll: (e: React.UIEvent<HTMLDivElement>) => {
      setScrollTop((e.target as HTMLDivElement).scrollTop);
    },
    totalHeight: items.length * itemHeight,
  };
}

/**
 * Hook to measure component performance
 */
export function usePerformanceMeasure(componentName: string, enabled = false) {
  const renderStartRef = useRef(0);
  const renderCountRef = useRef(0);

  React.useEffect(() => {
    if (enabled) {
      renderStartRef.current = performance.now();
    }
  });

  React.useLayoutEffect(() => {
    if (enabled && renderStartRef.current > 0) {
      const renderTime = performance.now() - renderStartRef.current;
      renderCountRef.current++;
      console.log(
        `[Perf] ${componentName} render #${renderCountRef.current}: ${renderTime.toFixed(2)}ms`,
      );
    }
  });
}
