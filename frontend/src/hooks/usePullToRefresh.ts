import { useCallback, useEffect, useRef, useState, type TouchEvent } from 'react';

export const PULL_TO_REFRESH_THRESHOLD_PX = 72;
const PULL_TO_REFRESH_MAX_DISTANCE_PX = 112;

export type PullToRefreshState = 'idle' | 'pulling' | 'armed' | 'refreshing';

type UsePullToRefreshOptions = {
  onRefresh: () => Promise<void>;
  enabled?: boolean;
  getScrollTop?: () => number;
};

const defaultScrollTop = () => {
  if (typeof window === 'undefined') return 0;
  return Math.max(
    window.scrollY || 0,
    document.documentElement.scrollTop || 0,
    document.body.scrollTop || 0,
  );
};

const INTERACTIVE_TARGET_SELECTOR = [
  'a',
  'input',
  'select',
  'textarea',
  'summary',
  '[contenteditable="true"]',
  '[role="tab"]',
  '[role="menuitem"]',
  '[role="checkbox"]',
  '[role="switch"]',
].join(', ');

const EXCLUDED_CONTAINER_SELECTOR = [
  '[role="dialog"]',
  '[aria-modal="true"]',
  '.modal',
  '.drawer',
  '.drawer__panel',
  '.drawer__body',
  '[data-pull-to-refresh-exclude="true"]',
].join(', ');

const asElement = (target: EventTarget | null) => {
  if (target instanceof Element) return target;
  if (target instanceof Node) return target.parentElement;
  return null;
};

const isScrollableContainer = (element: Element) => {
  const overflowY = window.getComputedStyle(element).overflowY;
  return overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay';
};

/**
 * The primary app shell may acknowledge a pull only when the gesture started
 * in its own document flow. Nested scroll panes, drawers, dialogs and controls
 * own their touch interactions and must never bubble into this gesture.
 */
export const isPrimaryPullTarget = (target: EventTarget | null, currentTarget: EventTarget | null) => {
  const element = asElement(target);
  const boundary = asElement(currentTarget);
  if (!element || !boundary || !boundary.contains(element)) return false;

  for (let cursor: Element | null = element; cursor; cursor = cursor.parentElement) {
    if (cursor.matches(INTERACTIVE_TARGET_SELECTOR) || cursor.matches(EXCLUDED_CONTAINER_SELECTOR)) return false;
    if (cursor !== boundary && isScrollableContainer(cursor)) return false;
    if (cursor === boundary) return true;
  }
  return false;
};

/**
 * A light touch-only acknowledgement for the primary document scroll. It does
 * not suppress native scrolling or pinch zoom, and delegates the actual data
 * refresh to the active screen's existing refresh path.
 */
export function usePullToRefresh({ onRefresh, enabled = true, getScrollTop = defaultScrollTop }: UsePullToRefreshOptions) {
  const [state, setState] = useState<PullToRefreshState>('idle');
  const [pullDistance, setPullDistance] = useState(0);
  const [gestureRoot, setGestureRoot] = useState<HTMLElement | null>(null);
  const startPointRef = useRef<{ x: number; y: number } | null>(null);
  const pullDistanceRef = useRef(0);
  const refreshingRef = useRef(false);
  const mountedRef = useRef(true);
  const enabledRef = useRef(enabled);
  const getScrollTopRef = useRef(getScrollTop);
  enabledRef.current = enabled;
  getScrollTopRef.current = getScrollTop;

  const resetPull = useCallback(() => {
    startPointRef.current = null;
    pullDistanceRef.current = 0;
    if (!refreshingRef.current && mountedRef.current) {
      setPullDistance(0);
      setState('idle');
    }
  }, []);

  useEffect(() => {
    // React StrictMode runs effect cleanup before its development remount.
    // Restore this flag here so a legitimate later refresh still updates UI.
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      startPointRef.current = null;
      pullDistanceRef.current = 0;
    };
  }, []);

  useEffect(() => {
    if (!enabled && !refreshingRef.current) resetPull();
  }, [enabled, resetPull]);

  useEffect(() => {
    if (!gestureRoot) return;

    const preventNativeRefreshAfterThreshold = (event: globalThis.TouchEvent) => {
      const start = startPointRef.current;
      if (!start || !enabledRef.current || refreshingRef.current || event.touches.length !== 1 || getScrollTopRef.current() > 0) return;
      const touch = event.touches[0];
      const deltaY = touch.clientY - start.y;
      const deltaX = touch.clientX - start.x;
      if (deltaY >= PULL_TO_REFRESH_THRESHOLD_PX && Math.abs(deltaX) <= deltaY) event.preventDefault();
    };

    // React delegates touch listeners as passive on mobile browsers. This one
    // stays local and non-passive, and only suppresses the already-armed,
    // eligible single-touch gesture; pinch and ordinary scrolling stay native.
    gestureRoot.addEventListener('touchmove', preventNativeRefreshAfterThreshold, { passive: false });
    return () => gestureRoot.removeEventListener('touchmove', preventNativeRefreshAfterThreshold);
  }, [gestureRoot]);

  const onTouchStart = useCallback((event: TouchEvent<HTMLElement>) => {
    if (event.touches.length !== 1) {
      resetPull();
      return;
    }
    if (
      !enabled
      || refreshingRef.current
      || getScrollTop() > 0
      || !isPrimaryPullTarget(event.target, event.currentTarget)
    ) return;
    const touch = event.touches[0];
    startPointRef.current = { x: touch.clientX, y: touch.clientY };
  }, [enabled, getScrollTop, resetPull]);

  const onTouchMove = useCallback((event: TouchEvent<HTMLElement>) => {
    const start = startPointRef.current;
    if (!start || refreshingRef.current) return;
    if (!enabled || event.touches.length !== 1 || getScrollTop() > 0) {
      resetPull();
      return;
    }

    const touch = event.touches[0];
    const deltaY = touch.clientY - start.y;
    const deltaX = touch.clientX - start.x;
    if (deltaY <= 0 || Math.abs(deltaX) > deltaY) {
      resetPull();
      return;
    }

    const nextDistance = Math.min(deltaY, PULL_TO_REFRESH_MAX_DISTANCE_PX);
    pullDistanceRef.current = nextDistance;
    setPullDistance(nextDistance);
    setState(nextDistance >= PULL_TO_REFRESH_THRESHOLD_PX ? 'armed' : 'pulling');
  }, [enabled, getScrollTop, resetPull]);

  const onTouchEnd = useCallback(async () => {
    const shouldRefresh = !refreshingRef.current && pullDistanceRef.current >= PULL_TO_REFRESH_THRESHOLD_PX;
    startPointRef.current = null;
    pullDistanceRef.current = 0;
    if (!shouldRefresh) {
      resetPull();
      return;
    }

    refreshingRef.current = true;
    if (mountedRef.current) {
      setPullDistance(PULL_TO_REFRESH_THRESHOLD_PX);
      setState('refreshing');
    }
    try {
      await onRefresh();
    } finally {
      refreshingRef.current = false;
      if (mountedRef.current) {
        setPullDistance(0);
        setState('idle');
      }
    }
  }, [onRefresh, resetPull]);

  const onTouchCancel = useCallback(() => {
    if (!refreshingRef.current) resetPull();
  }, [resetPull]);

  return {
    state,
    pullDistance,
    rootRef: setGestureRoot,
    // Capture the gesture before a Dashboard card/button can stop propagation.
    // iOS standalone may dispatch the first touch through an interactive child.
    handlers: {
      onTouchStartCapture: onTouchStart,
      onTouchMoveCapture: onTouchMove,
      onTouchEndCapture: onTouchEnd,
      onTouchCancelCapture: onTouchCancel,
    },
  };
}
