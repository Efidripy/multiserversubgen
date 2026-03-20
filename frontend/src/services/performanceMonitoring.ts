/**
 * Performance Monitoring & Analytics
 * Tracks Web Vitals, API latency, and sends metrics to Sentry
 */

export interface PerformanceMetrics {
  fcp?: number; // First Contentful Paint
  lcp?: number; // Largest Contentful Paint
  cls?: number; // Cumulative Layout Shift
  tti?: number; // Time to Interactive
  ttfb?: number; // Time to First Byte
  apiLatency: Record<string, number[]>;
  errorCount: number;
  timestamp: number;
}

class PerformanceMonitor {
  private metrics: PerformanceMetrics = {
    apiLatency: {},
    errorCount: 0,
    timestamp: Date.now(),
  };

  private waterMark = new Map<string, number>();

  constructor() {
    this.initWebVitals();
  }

  private initWebVitals() {
    // First Contentful Paint (FCP)
    if ('PerformanceObserver' in window) {
      try {
        const fcpObserver = new PerformanceObserver((list) => {
          const entries = list.getEntries();
          const fcpEntry = entries[0];
          if (fcpEntry) {
            this.metrics.fcp = fcpEntry.startTime;
            console.log('[Vitals] FCP:', this.metrics.fcp.toFixed(2), 'ms');
          }
        });
        fcpObserver.observe({ entryTypes: ['paint'] });

        // Largest Contentful Paint (LCP)
        const lcpObserver = new PerformanceObserver((list) => {
          const entries = list.getEntries();
          const lcpEntry = entries[entries.length - 1] as any;
          if (lcpEntry) {
            this.metrics.lcp = lcpEntry.renderTime || lcpEntry.loadTime;
            if (this.metrics.lcp) {
              console.log('[Vitals] LCP:', this.metrics.lcp.toFixed(2), 'ms');
            }
          }
        });
        lcpObserver.observe({ entryTypes: ['largest-contentful-paint'] });

        // Cumulative Layout Shift (CLS)
        let clsValue = 0;
        const clsObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (!(entry as any).hadRecentInput) {
              clsValue += (entry as any).value;
            }
          }
          this.metrics.cls = clsValue;
          console.log('[Vitals] CLS:', this.metrics.cls.toFixed(3));
        });
        clsObserver.observe({ entryTypes: ['layout-shift'] });
      } catch (err) {
        console.warn('PerformanceObserver not fully supported:', err);
      }
    }
  }

  recordApiLatency(endpoint: string, latencyMs: number) {
    if (!this.metrics.apiLatency[endpoint]) {
      this.metrics.apiLatency[endpoint] = [];
    }
    this.metrics.apiLatency[endpoint].push(latencyMs);
    // Keep only last 100 samples per endpoint
    if (this.metrics.apiLatency[endpoint].length > 100) {
      this.metrics.apiLatency[endpoint].shift();
    }
  }

  recordError() {
    this.metrics.errorCount++;
  }

  startMeasure(label: string) {
    if (typeof performance !== 'undefined' && performance.mark) {
      performance.mark(`${label}-start`);
    }
    this.waterMark.set(label, Date.now());
  }

  endMeasure(label: string): number {
    let duration = 0;
    if (typeof performance !== 'undefined' && performance.measure) {
      try {
        performance.measure(label, `${label}-start`);
        const measure = performance.getEntriesByName(label)[0];
        duration = measure?.duration || 0;
        console.log(`[Measure] ${label}: ${duration.toFixed(2)}ms`);
      } catch (err) {
        // Fallback if mark not found
        const startTime = this.waterMark.get(label) || Date.now();
        duration = Date.now() - startTime;
      }
    }
    this.waterMark.delete(label);
    return duration;
  }

  getMetrics(): PerformanceMetrics {
    return { ...this.metrics };
  }

  getAverageApiLatency(endpoint: string): number {
    const samples = this.metrics.apiLatency[endpoint] || [];
    if (samples.length === 0) return 0;
    return samples.reduce((a, b) => a + b, 0) / samples.length;
  }

  exportMetrics() {
    const exports = {
      fcp: this.metrics.fcp,
      lcp: this.metrics.lcp,
      cls: this.metrics.cls,
      errorCount: this.metrics.errorCount,
      apiEndpoints: Object.keys(this.metrics.apiLatency).map((endpoint) => ({
        endpoint,
        avgLatency: this.getAverageApiLatency(endpoint),
        minLatency: Math.min(...(this.metrics.apiLatency[endpoint] || [])),
        maxLatency: Math.max(...(this.metrics.apiLatency[endpoint] || [])),
        sampleCount: this.metrics.apiLatency[endpoint]?.length || 0,
      })),
    };
    console.log('[Metrics Export]', exports);
    // TODO: Send to Sentry/analytics here
    return exports;
  }
}

export const performanceMonitor = new PerformanceMonitor();
