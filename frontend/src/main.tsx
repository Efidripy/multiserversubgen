import React from 'react';
import ReactDOM from 'react-dom/client';
import 'bootstrap/dist/css/bootstrap.min.css';
import './default_shadcn_theme.css';
import './App.css';
import './styles/theme-dark.css';
import './styles/theme-light.css';
import './i18n/config';
import i18next from 'i18next';
import { App } from './App';
import { ThemeProvider } from './contexts/ThemeContext';

// Performance & Optimization Initialization
import { performanceMonitor } from './services/performanceMonitoring';
import { swManager } from './services/serviceWorkerManager';
import { indexedDBManager } from './services/indexedDBManager';
import { devLog } from './utils/devLogger';

type ErrorBoundaryState = { hasError: boolean; message: string };

class RootErrorBoundary extends React.Component<React.PropsWithChildren, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, message: '' };

  private handleUnhandledRejection = (event: PromiseRejectionEvent) => {
    if (this.state.hasError) return;
    const reason = event.reason;
    const message =
      reason instanceof Error
        ? reason.message
        : typeof reason === 'string'
        ? reason
        : i18next.t('main.unhandledRejection');
    this.setState({ hasError: true, message });
  };

  private handleWindowError = (event: ErrorEvent) => {
    if (this.state.hasError) return;
    const message = event.error?.message || event.message || i18next.t('main.windowError');
    this.setState({ hasError: true, message });
  };

  componentDidMount() {
    window.addEventListener('unhandledrejection', this.handleUnhandledRejection);
    window.addEventListener('error', this.handleWindowError);
  }

  componentWillUnmount() {
    window.removeEventListener('unhandledrejection', this.handleUnhandledRejection);
    window.removeEventListener('error', this.handleWindowError);
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, message: error?.message || i18next.t('main.unknownUiError') };
  }

  componentDidCatch(error: Error) {
    console.error('Root UI crash:', error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ minHeight: '100vh', background: '#0f172a', color: '#f1f5f9', padding: '24px' }}>
          <h3 style={{ marginBottom: '12px' }}>{i18next.t('main.uiErrorTitle')}</h3>
          <p style={{ marginBottom: '8px' }}>{this.state.message}</p>
          <p style={{ opacity: 0.8 }}>{i18next.t('main.uiErrorHint')}</p>
          <button
            style={{
              marginTop: '10px',
              padding: '8px 12px',
              borderRadius: '8px',
              border: '1px solid rgba(148,163,184,0.45)',
              background: 'rgba(30,41,59,0.75)',
              color: '#f1f5f9',
              cursor: 'pointer',
            }}
            onClick={() => window.location.reload()}
          >
            {i18next.t('main.reloadPage')}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <RootErrorBoundary>
        <App />
      </RootErrorBoundary>
    </ThemeProvider>
  </React.StrictMode>
);

// Initialize optimizations after app renders
(async () => {
  // Performance monitoring
  devLog('[Init] Starting performance monitoring...');
  performanceMonitor.startMeasure('app-initial-load');

  // Service Worker registration
  devLog('[Init] Registering Service Worker...');
  await swManager.register({
    onReady: () => devLog('[SW] Ready for offline support'),
    onUpdate: () => devLog('[SW] Update available!'),
    onOffline: () => devLog('[SW] Offline mode activated'),
  }).catch((err) => {
    console.warn('[SW] Registration failed (non-critical):', err);
  });

  // IndexedDB initialization
  devLog('[Init] Initializing IndexedDB...');
  try {
    await indexedDBManager.init();
    devLog('[IndexedDB] Initialized successfully');
  } catch (err) {
    console.warn('[IndexedDB] Initialization failed (non-critical):', err);
  }

  // Optional: Prune old data from IndexedDB (90+ days old traffic history)
  try {
    const pruned = await indexedDBManager.pruneOlderThan('traffic_history', 90 * 24 * 60 * 60 * 1000);
    devLog(`[IndexedDB] Pruned ${pruned} old records`);
  } catch (err) {
    console.warn('[IndexedDB] Prune failed:', err);
  }

  const loadTime = performanceMonitor.endMeasure('app-initial-load');
  devLog(`[Init] App initialization complete in ${loadTime.toFixed(2)}ms`);

  // Export metrics after a delay to allow data collection
  setTimeout(() => {
    devLog(performanceMonitor.exportMetrics());
  }, 5000);
})();
