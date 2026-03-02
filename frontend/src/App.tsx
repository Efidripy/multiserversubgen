import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import api, { API_BASE } from './api';
import { NodeManager } from './components/NodeManager';
import { ServerStatus } from './components/ServerStatus';
import { SubscriptionManager } from './components/SubscriptionManager';
import { InboundManager } from './components/InboundManager';
import { ClientManager } from './components/ClientManager';
import { TrafficStats } from './components/TrafficStats';
import { BackupManager } from './components/BackupManager';
import { MonitoringDashboard } from './components/MonitoringDashboard';
import { Sidebar } from './components/Sidebar';
import { useTheme } from './contexts/ThemeContext';
import { useWebSocket } from './hooks/useWebSocket';
import { clearAuthCredentials, getAuth, loadRememberedUsername, rememberUsername, setAuthCredentials } from './auth';
import { IconName, UIIcon } from './components/UIIcon';

type TabType = 'dashboard' | 'servers' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions';
type NoticeLevel = 'info' | 'success' | 'warning' | 'danger';

interface UiNotification {
  id: string;
  title: string;
  message: string;
  level: NoticeLevel;
  ts: number;
}

export const App: React.FC = () => {
  const { theme, toggleTheme, colors } = useTheme();
  const { t } = useTranslation();

  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authBootstrapDone, setAuthBootstrapDone] = useState(false);
  const [authError, setAuthError] = useState('');
  const [activeTab, setActiveTab] = useState<TabType>('dashboard');
  const [key, setKey] = useState(0);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  const [notifications, setNotifications] = useState<UiNotification[]>([]);
  const [notificationPanelOpen, setNotificationPanelOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [browserNotifySupported, setBrowserNotifySupported] = useState(false);
  const [browserNotifyPermission, setBrowserNotifyPermission] = useState<'default' | 'granted' | 'denied'>('default');

  const lastNotifyRef = useRef<Record<string, number>>({});

  useEffect(() => {
    const bootstrap = async () => {
      const remembered = loadRememberedUsername();
      setUser(remembered);

      try {
        const mfaRes = await api.get('/v1/auth/mfa-status');
        setMfaEnabled(Boolean(mfaRes.data?.enabled));
      } catch {
        setMfaEnabled(false);
      }

      const auth = getAuth();
      if (auth.username && auth.password) {
        try {
          const headers: Record<string, string> = {};
          if (auth.totpCode) headers['X-TOTP-Code'] = auth.totpCode;
          const res = await api.get('/v1/auth/verify', {
            auth: { username: auth.username, password: auth.password },
            headers,
          });
          if (res.data?.user) {
            setUser(auth.username);
            setIsAuthenticated(true);
          }
        } catch {
          clearAuthCredentials();
        }
      }
      setAuthBootstrapDone(true);
    };
    bootstrap();

    const supported = typeof window !== 'undefined' && 'Notification' in window;
    setBrowserNotifySupported(supported);
    if (supported) {
      setBrowserNotifyPermission(Notification.permission);
    }
  }, []);

  useEffect(() => {
    if (notificationPanelOpen) {
      setUnreadCount(0);
    }
  }, [notificationPanelOpen]);

  const pushUiNotification = (title: string, message: string, level: NoticeLevel = 'info', dedupeKey?: string) => {
    const now = Date.now();
    if (dedupeKey) {
      const prev = lastNotifyRef.current[dedupeKey] || 0;
      if (now - prev < 5000) return;
      lastNotifyRef.current[dedupeKey] = now;
    }

    const item: UiNotification = {
      id: `${now}-${Math.random().toString(36).slice(2, 8)}`,
      title,
      message,
      level,
      ts: now,
    };

    setNotifications((prev) => [item, ...prev].slice(0, 30));
    if (!notificationPanelOpen) {
      setUnreadCount((prev) => prev + 1);
    }

    if (browserNotifySupported && browserNotifyPermission === 'granted' && typeof document !== 'undefined') {
      if (document.hidden) {
        new Notification(title, { body: message });
      }
    }
  };

  const requestBrowserNotifications = async () => {
    if (!browserNotifySupported) return;
    const permission = await Notification.requestPermission();
    setBrowserNotifyPermission(permission);
    if (permission === 'granted') {
      pushUiNotification(t('push.title'), t('push.enabled'), 'success');
    }
  };

  useWebSocket({
    url: '',
    channels: ['inbounds', 'snapshot_delta'],
    enabled: isAuthenticated,
    onMessage: (msg) => {
      if (msg.type === 'inbound_update') {
        const action = msg.data?.action || 'update';
        const successful = msg.data?.result?.successful ?? 0;
        const total = msg.data?.result?.total ?? 0;

        let actionLabel = t('push.inboundUpdated');
        if (action === 'batch_enable') actionLabel = t('push.inboundBatchEnable');
        if (action === 'batch_update') actionLabel = t('push.inboundBatchUpdate');
        if (action === 'batch_delete') actionLabel = t('push.inboundBatchDelete');

        pushUiNotification(
          t('push.title'),
          `${actionLabel}: ${successful}/${total}`,
          successful === total ? 'success' : 'warning',
          `inbound:${action}:${successful}:${total}`
        );
      }

      if (msg.type === 'snapshot_delta') {
        const node = msg.data?.node || 'node';
        const changes = msg.data?.changes || {};

        if (changes.available) {
          const isUp = Boolean(changes.available.new);
          pushUiNotification(
            t('push.title'),
            isUp ? t('push.nodeOnline', { node }) : t('push.nodeOffline', { node }),
            isUp ? 'success' : 'danger',
            `node-availability:${node}:${String(isUp)}`
          );
        }

        if (changes.xray_running) {
          const running = Boolean(changes.xray_running.new);
          pushUiNotification(
            t('push.title'),
            running ? t('push.xrayRunning', { node }) : t('push.xrayStopped', { node }),
            running ? 'success' : 'warning',
            `node-xray:${node}:${String(running)}`
          );
        }
      }
    },
  });

  const handleLogin = async () => {
    setAuthError('');
    try {
      const headers: Record<string, string> = {};
      if (totpCode.trim()) headers['X-TOTP-Code'] = totpCode.trim();
      const res = await api.get('/v1/auth/verify', {
        auth: { username: user, password },
        headers,
      });
      if (res.data.user) {
        setAuthCredentials(user, password, totpCode.trim());
        setIsAuthenticated(true);
        rememberUsername(user);
        setPassword('');
        setTotpCode('');
      }
    } catch (err: any) {
      setAuthError(err.response?.data?.detail || t('auth.failed'));
    }
  };

  const handleLogout = () => {
    clearAuthCredentials();
    setUser('');
    setPassword('');
    setIsAuthenticated(false);
  };

  const getApiUrl = () => {
    const host = typeof window !== 'undefined' ? window.location.host : '';
    const protocol = typeof window !== 'undefined' ? window.location.protocol : 'https:';
    const fullApiUrl = API_BASE.startsWith('http') ? API_BASE : `${protocol}//${host}${API_BASE}`;
    return fullApiUrl;
  };

  if (!authBootstrapDone) {
    return (
      <div className="login-wrapper min-vh-100 d-flex align-items-center justify-content-center" style={{ backgroundColor: colors.bg.primary }}>
        <div className="card p-4 text-center" style={{ maxWidth: '400px', width: '100%', backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
          <div style={{ color: colors.text.primary }}>{t('app.loading')}</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="login-wrapper min-vh-100 d-flex align-items-center justify-content-center" style={{ backgroundColor: colors.bg.primary }}>
        <div className="card p-4" style={{ maxWidth: '400px', width: '100%', backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
          <div className="d-flex justify-content-between align-items-center mb-4">
            <h5 className="mb-0 d-flex align-items-center gap-2" style={{ color: colors.text.primary }}>
              <UIIcon name="logo" size={18} />
              {t('app.title')}
            </h5>
            <button
              className="btn btn-sm btn-outline-secondary"
              onClick={toggleTheme}
              title={t('theme.toggle')}
            >
              {theme === 'dark' ? <UIIcon name="sun" size={16} /> : <UIIcon name="moon" size={16} />}
            </button>
          </div>
          <form onSubmit={(e) => { e.preventDefault(); handleLogin(); }}>
            <div className="mb-3">
              <label className="form-label" style={{ color: colors.text.secondary }}>{t('auth.username')}</label>
              <input
                type="text"
                className="form-control"
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                value={user}
                onChange={(e) => setUser(e.target.value)}
                required
                autoFocus
                autoComplete="username"
              />
            </div>
            <div className="mb-3">
              <label className="form-label" style={{ color: colors.text.secondary }}>{t('auth.password')}</label>
              <input
                type="password"
                className="form-control"
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            {mfaEnabled && (
              <div className="mb-3">
                <label className="form-label" style={{ color: colors.text.secondary }}>{t('auth.totpCode')}</label>
                <input
                  type="text"
                  className="form-control"
                  style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                  required
                  inputMode="numeric"
                  placeholder="123456"
                />
              </div>
            )}
            {authError && <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{authError}</div>}
            <button type="submit" className="btn w-100" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}>
              {t('auth.signIn')}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const tabMeta: Record<TabType, { icon: IconName; label: string }> = {
    dashboard: { icon: 'dashboard', label: t('nav.dashboard') },
    servers: { icon: 'servers', label: t('nav.nodes') },
    inbounds: { icon: 'inbounds', label: t('nav.inbounds') },
    clients: { icon: 'clients', label: t('nav.clients') },
    traffic: { icon: 'traffic', label: t('nav.traffic') },
    monitoring: { icon: 'monitoring', label: t('nav.monitoring') },
    backup: { icon: 'backup', label: t('nav.backup') },
    subscriptions: { icon: 'subscriptions', label: t('nav.subscriptions') },
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return <ServerStatus />;
      case 'servers':
        return <NodeManager onReload={() => setKey((prev) => prev + 1)} />;
      case 'inbounds':
        return <InboundManager onReload={() => setKey((prev) => prev + 1)} />;
      case 'clients':
        return <ClientManager />;
      case 'traffic':
        return <TrafficStats />;
      case 'monitoring':
        return <MonitoringDashboard />;
      case 'backup':
        return <BackupManager />;
      case 'subscriptions':
        return <SubscriptionManager key={key} apiUrl={getApiUrl()} />;
      default:
        return null;
    }
  };

  const levelColor = (level: NoticeLevel) => {
    if (level === 'success') return colors.success;
    if (level === 'warning') return colors.warning;
    if (level === 'danger') return colors.danger;
    return colors.info;
  };

  return (
    <div
      className="app-layout"
      style={{
        backgroundColor: colors.bg.primary,
        color: colors.text.primary,
        fontFamily: 'var(--font-sans)',
      }}
    >
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        user={user}
        onLogout={handleLogout}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
      />

      <div className="app-main" style={{ position: 'relative' }}>
        <header
          className="app-topbar"
          style={{ backgroundColor: colors.bg.secondary, borderBottom: `1px solid ${colors.border}` }}
        >
          <button
            className="app-topbar__menu-btn"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="Open menu"
            style={{ color: colors.text.primary, backgroundColor: colors.bg.tertiary, border: `1px solid ${colors.border}` }}
          >
            <UIIcon name="menu" size={16} />
          </button>
          <h1 className="app-topbar__title" style={{ color: colors.text.primary }}>
            <span className="d-inline-flex align-items-center gap-2">
              <UIIcon name={tabMeta[activeTab].icon} size={16} />
              {tabMeta[activeTab].label}
            </span>
          </h1>

          <div className="d-flex align-items-center gap-2">
            {browserNotifySupported && browserNotifyPermission !== 'granted' && (
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                onClick={requestBrowserNotifications}
              >
                {t('push.enableBrowser')}
              </button>
            )}

            <button
              className="btn btn-sm position-relative"
              style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
              onClick={() => setNotificationPanelOpen((v) => !v)}
              title={t('push.title')}
            >
              <UIIcon name="bell" size={15} />
              {unreadCount > 0 && (
                <span
                  className="position-absolute top-0 start-100 translate-middle badge rounded-pill"
                  style={{ backgroundColor: colors.danger }}
                >
                  {unreadCount > 99 ? '99+' : unreadCount}
                </span>
              )}
            </button>
          </div>
        </header>

        {notificationPanelOpen && (
          <div
            className="card"
            style={{
              position: 'absolute',
              top: '56px',
              right: '16px',
              width: '360px',
              maxHeight: '420px',
              overflowY: 'auto',
              zIndex: 50,
              backgroundColor: colors.bg.secondary,
              borderColor: colors.border,
            }}
          >
            <div className="card-header d-flex justify-content-between align-items-center" style={{ borderColor: colors.border }}>
              <strong style={{ color: colors.text.primary }}>{t('push.title')}</strong>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                onClick={() => setNotifications([])}
              >
                {t('push.clear')}
              </button>
            </div>
            <div className="card-body p-2">
              {notifications.length === 0 && (
                <div className="small" style={{ color: colors.text.secondary }}>{t('push.empty')}</div>
              )}
              {notifications.map((item) => (
                <div
                  key={item.id}
                  className="p-2 mb-2 rounded"
                  style={{ backgroundColor: colors.bg.primary, border: `1px solid ${colors.border}` }}
                >
                  <div className="d-flex justify-content-between align-items-center">
                    <strong style={{ color: levelColor(item.level) }}>{item.title}</strong>
                    <small style={{ color: colors.text.secondary }}>
                      {new Date(item.ts).toLocaleTimeString()}
                    </small>
                  </div>
                  <div className="small" style={{ color: colors.text.primary }}>{item.message}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <main className="app-content">
          <div className="tab-panel">
            {renderTabContent()}
          </div>
        </main>
      </div>
    </div>
  );
};
