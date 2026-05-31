/**
 * Error Boundary with Resilience & Graceful Degradation
 * Handles errors and provides offline fallback UI
 */

import React, { ReactNode, ErrorInfo, useState, useEffect } from 'react';
import i18n from '../i18n/config';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  isOnline: boolean;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      isOnline: typeof navigator !== 'undefined' ? navigator.onLine : true,
    };
  }

  componentDidMount() {
    window.addEventListener('online', this.handleOnline.bind(this));
    window.addEventListener('offline', this.handleOffline.bind(this));
  }

  componentWillUnmount() {
    window.removeEventListener('online', this.handleOnline.bind(this));
    window.removeEventListener('offline', this.handleOffline.bind(this));
  }

  handleOnline() {
    this.setState({ isOnline: true });
  }

  handleOffline() {
    this.setState({ isOnline: false });
  }

  static getDerivedStateFromError(_error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught error:', error?.message || 'Unknown');
    this.setState({
      error,
      errorInfo,
    });
  }

  resetError = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render() {
    const { hasError, error, isOnline } = this.state;

    if (hasError) {
      return (
        <div
          style={{
            padding: '20px',
            textAlign: 'center',
            backgroundColor: '#fff3cd',
            border: '1px solid #ffc107',
            borderRadius: '4px',
            margin: '20px',
          }}
        >
          <h2>⚠️ {i18n.t('errorBoundary.title')}</h2>
          <p>{error?.message}</p>
          {!isOnline && (
            <p style={{ color: '#d32f2f', fontWeight: 'bold' }}>
              📵 {i18n.t('errorBoundary.offlineHint')}
            </p>
          )}
          <button
            onClick={this.resetError}
            style={{
              padding: '8px 16px',
              marginTop: '10px',
              backgroundColor: '#007bff',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            {i18n.t('errorBoundary.tryAgain')}
          </button>
          <details style={{ marginTop: '20px', textAlign: 'left' }}>
            <summary>{i18n.t('errorBoundary.errorDetails')}</summary>
            <pre style={{ overflow: 'auto', backgroundColor: '#f5f5f5', padding: '10px' }}>
              {error?.stack}
            </pre>
          </details>
        </div>
      );
    }

    return this.props.children;
  }
}

/**
 * Resilience wrapper for API calls with retry logic
 */
export async function fetchWithRetry<T>(
  url: string,
  options: RequestInit & { maxRetries?: number; initialDelay?: number } = {},
): Promise<T> {
  const maxRetries = options.maxRetries ?? 3;
  const initialDelay = options.initialDelay ?? 1000;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetch(url, {
        ...options,
        signal: options.signal,
      });

      if (!response.ok) {
        if ([408, 429, 500, 502, 503, 504].includes(response.status) && attempt < maxRetries) {
          const delay = initialDelay * Math.pow(2, attempt) + Math.random() * 1000;
          await new Promise((resolve) => setTimeout(resolve, delay));
          continue;
        }
        throw new Error(`HTTP ${response.status}`);
      }

      return (await response.json()) as T;
    } catch (error) {
      if (attempt === maxRetries) throw error;
      const delay = initialDelay * Math.pow(2, attempt) + Math.random() * 1000;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  throw new Error('Max retries exceeded');
}

/**
 * Hook to detect online/offline state
 */
export function useOnlineStatus() {
  const [isOnline, setIsOnline] = useState(typeof navigator !== 'undefined' ? navigator.onLine : true);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  return isOnline;
}
