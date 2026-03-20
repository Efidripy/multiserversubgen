/**
 * Delta Updates Protocol
 * Only send/receive changed fields instead of full objects
 */

export interface DeltaUpdatePayload<T> {
  id: string;
  type: 'full' | 'delta';
  data: T | Partial<T>;
  timestamp: number;
}

/**
 * Calculate delta between old and new objects
 */
export function calculateDelta<T extends Record<string, any>>(oldData: T, newData: T): Partial<T> {
  const delta: Partial<T> = {};

  for (const key in newData) {
    const oldValue = oldData[key];
    const newValue = newData[key];

    // Deep comparison for objects
    if (typeof newValue === 'object' && newValue !== null && typeof oldValue === 'object' && oldValue !== null) {
      if (JSON.stringify(oldValue) !== JSON.stringify(newValue)) {
        delta[key] = newValue;
      }
    } else if (oldValue !== newValue) {
      delta[key] = newValue;
    }
  }

  return delta;
}

/**
 * Merge delta update into existing data
 */
export function mergeDelta<T extends Record<string, any>>(base: T, delta: Partial<T>): T {
  return { ...base, ...delta };
}

/**
 * Determine if update should be sent as full or delta
 */
export function shouldSendAsDelta<T extends Record<string, any>>(delta: Partial<T>, threshold = 0.3): boolean {
  if (Object.keys(delta).length === 0) return false;

  // If more than threshold % of fields changed, send full update
  const changeRate = Object.keys(delta).length / Object.keys(delta).length;
  return changeRate < threshold;
}

/**
 * Track object changes for efficient delta calculation
 */
export class DeltaTracker<T extends Record<string, any>> {
  private snapshot: T | null = null;

  track(data: T): DeltaUpdatePayload<T> {
    if (this.snapshot === null) {
      // First time: send full object
      this.snapshot = JSON.parse(JSON.stringify(data));
      return {
        id: data.id || 'unknown',
        type: 'full',
        data,
        timestamp: Date.now(),
      };
    }

    const delta = calculateDelta(this.snapshot, data);
    const isDelta = shouldSendAsDelta(delta);

    this.snapshot = JSON.parse(JSON.stringify(data));

    if (isDelta) {
      return {
        id: data.id || 'unknown',
        type: 'delta',
        data: delta,
        timestamp: Date.now(),
      };
    }

    return {
      id: data.id || 'unknown',
      type: 'full',
      data,
      timestamp: Date.now(),
    };
  }

  reset() {
    this.snapshot = null;
  }
}

/**
 * Batch delta updates to reduce network traffic
 */
export class DeltaBatcher {
  private batch: Map<string, DeltaUpdatePayload<any>> = new Map();
  private flushTimer: number | null = null;
  private flushCallback: (batch: DeltaUpdatePayload<any>[]) => void;
  private flushIntervalMs = 100; // Flush every 100ms

  constructor(flushCallback: (batch: DeltaUpdatePayload<any>[]) => void, flushIntervalMs = 100) {
    this.flushCallback = flushCallback;
    this.flushIntervalMs = flushIntervalMs;
  }

  add<T extends Record<string, any>>(update: DeltaUpdatePayload<T>) {
    this.batch.set(update.id, update);
    this.scheduleFlush();
  }

  private scheduleFlush() {
    if (this.flushTimer !== null) return;

    this.flushTimer = window.setTimeout(() => {
      this.flush();
    }, this.flushIntervalMs);
  }

  flush() {
    if (this.flushTimer !== null) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }

    if (this.batch.size === 0) return;

    const updates = Array.from(this.batch.values());
    this.batch.clear();

    this.flushCallback(updates);
  }

  destroy() {
    if (this.flushTimer !== null) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    this.batch.clear();
  }
}
