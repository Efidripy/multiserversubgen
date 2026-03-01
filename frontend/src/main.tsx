import React from 'react';
import ReactDOM from 'react-dom/client';
import 'bootstrap/dist/css/bootstrap.min.css';
import './App.css';
import './i18n/config';
import { App } from './App';
import { ThemeProvider } from './contexts/ThemeContext';

type ErrorBoundaryState = { hasError: boolean; message: string };

class RootErrorBoundary extends React.Component<React.PropsWithChildren, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, message: '' };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, message: error?.message || 'Unknown UI error' };
  }

  componentDidCatch(error: Error) {
    console.error('Root UI crash:', error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ minHeight: '100vh', background: '#0f172a', color: '#f1f5f9', padding: '24px' }}>
          <h3 style={{ marginBottom: '12px' }}>UI error</h3>
          <p style={{ marginBottom: '8px' }}>{this.state.message}</p>
          <p style={{ opacity: 0.8 }}>Open browser console (F12) and send the latest error.</p>
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
