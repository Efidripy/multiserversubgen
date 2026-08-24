import React, { useState, useEffect, useRef, useCallback } from 'react';
import { activityLog } from './services/activityLog';
import { ActivityLogPanel } from './components/ActivityLogPanel';
import { useTranslation } from 'react-i18next';
import { API_BASE } from './api';
import { ServerStatus } from './components/ServerStatus';
import { NodeManager } from './components/NodeManager';
import { DashboardSummary } from './components/DashboardSummary';
import { RegisteredFleetPanel } from './components/RegisteredFleetPanel';
import { ToastProvider } from './components/Toast';
import { Sidebar, SidebarNavItem } from './components/Sidebar';
import { useTheme } from './contexts/ThemeContext';
import { useWebSocketMessages, wsManager } from './services/webSocketManager';
import { clearAuthCredentials, loadRememberedUsername, rememberUsername, setAuthCredentials, setWsTicket } from './auth';
import { clearBrowserSession, createBrowserSession, getMfaStatus, verifyCurrentAuth } from './api/authService';
import {
  getBackupHeaderSource,
  getMonitoringHeaderSource,
  getSubscriptionsHeaderSource,
} from './api/dashboard';
import { IconName, UIIcon } from './components/UIIcon';
import { requestActivityStore } from './services/requestActivity';
import { clearManagerSnapshotCaches, readStaleCache, writeStaleCache } from './services/staleCache';
import { DashboardDataProvider } from './services/DashboardDataContext';
import { AUTH_REQUIRED_EVENT, resetAuthRequiredEventGuard } from './api/client';
import type { NodeRecord } from './api/nodes';

const LazySubscriptionManager = React.lazy(() => import('./components/SubscriptionManager').then((module) => ({ default: module.SubscriptionManager })));
const LazyInboundManager = React.lazy(() => import('./components/InboundManager').then((module) => ({ default: module.InboundManager })));
const LazyClientManager = React.lazy(() => import('./components/ClientManager').then((module) => ({ default: module.ClientManager })));
const LazyTrafficStats = React.lazy(() => import('./components/TrafficStats').then((module) => ({ default: module.TrafficStats })));
const LazyMonitoringDashboard = React.lazy(() => import('./components/MonitoringDashboard').then((module) => ({ default: module.MonitoringDashboard })));
const LazyBackupManager = React.lazy(() => import('./components/BackupManager').then((module) => ({ default: module.BackupManager })));

type TabType = 'dashboard' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions';
type NoticeLevel = 'info' | 'success' | 'warning' | 'danger';
type HeaderStatTone = 'default' | 'accent' | 'success' | 'warning' | 'danger';

interface UiNotification {
  id: string;
  title: string;
  message: string;
  level: NoticeLevel;
  ts: number;
}

interface HeaderStat {
  label: string;
  value: string;
  tone?: HeaderStatTone;
}

interface HeaderSummary {
  description: string;
  stats: HeaderStat[];
}

const normalizeHeaderSummary = (raw: Partial<HeaderSummary> | null | undefined, fallbackDescription: string): HeaderSummary => ({
  description: typeof raw?.description === 'string' ? raw.description : fallbackDescription,
  stats: Array.isArray(raw?.stats) ? raw.stats : [],
});

const HEADER_SUMMARY_CACHE_KEY = 'sub_manager_header_summary_cache_v1';
const HEADER_SUMMARY_CACHE_MAX_AGE_MS = 15 * 60 * 1000;
const ACTIVE_TAB_CACHE_KEY = 'sub_manager_active_tab_v1';
const FLEET_RAIL_COLLAPSED_KEY = 'sub_manager_fleet_rail_collapsed_v1';

const TAB_META: Record<TabType, { icon: IconName; labelKey: string; eyebrowKey: string; descriptionKey: string }> = {
  dashboard: {
    icon: 'dashboard',
    labelKey: 'nav.dashboard',
    eyebrowKey: 'tabEyebrow.dashboard',
    descriptionKey: 'tabDescription.dashboard',
  },
  inbounds: {
    icon: 'inbounds',
    labelKey: 'nav.inbounds',
    eyebrowKey: 'tabEyebrow.inbounds',
    descriptionKey: 'tabDescription.inbounds',
  },
  clients: {
    icon: 'clients',
    labelKey: 'nav.clients',
    eyebrowKey: 'tabEyebrow.clients',
    descriptionKey: 'tabDescription.clients',
  },
  traffic: {
    icon: 'traffic',
    labelKey: 'nav.traffic',
    eyebrowKey: 'tabEyebrow.traffic',
    descriptionKey: 'tabDescription.traffic',
  },
  monitoring: {
    icon: 'monitoring',
    labelKey: 'nav.monitoring',
    eyebrowKey: 'tabEyebrow.monitoring',
    descriptionKey: 'tabDescription.monitoring',
  },
  backup: {
    icon: 'backup',
    labelKey: 'nav.backup',
    eyebrowKey: 'tabEyebrow.backup',
    descriptionKey: 'tabDescription.backup',
  },
  subscriptions: {
    icon: 'subscriptions',
    labelKey: 'nav.subscriptions',
    eyebrowKey: 'tabEyebrow.subscriptions',
    descriptionKey: 'tabDescription.subscriptions',
  },
};

const formatCompactNumber = (value: number) =>
  new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: value >= 100 ? 0 : 1 }).format(value);

const formatPercent = (value: number) => `${Number.isFinite(value) ? value.toFixed(value >= 10 ? 0 : 1) : '0'}%`;

export const App: React.FC = () => {
  const { colors } = useTheme();
  const { t } = useTranslation();

  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [role, setRole] = useState('viewer');
  const [authBootstrapDone, setAuthBootstrapDone] = useState(false);
  const [authError, setAuthError] = useState('');
  const [activeTab, setActiveTab] = useState<TabType>(() => {
    try {
      const raw = localStorage.getItem(ACTIVE_TAB_CACHE_KEY);
      if (raw && raw in TAB_META) {
        return raw as TabType;
      }
    } catch {
      // Ignore localStorage read failures.
    }
    return 'dashboard';
  });
  const [key, setKey] = useState(0);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [headerSummary, setHeaderSummary] = useState<HeaderSummary>({
    description: t(TAB_META.dashboard.descriptionKey),
    stats: [],
  });
  const [headerLoading, setHeaderLoading] = useState(false);
  const [pendingRequests, setPendingRequests] = useState(0);
  const [nodeIntakeOpenSignal, setNodeIntakeOpenSignal] = useState(0);
  const [nodeEditOpenSignal, setNodeEditOpenSignal] = useState(0);
  const [nodeEditTarget, setNodeEditTarget] = useState<NodeRecord | null>(null);

  const [notifications, setNotifications] = useState<UiNotification[]>([]);
  const [notificationPanelOpen, setNotificationPanelOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [browserNotifySupported, setBrowserNotifySupported] = useState(false);
  const [browserNotifyPermission, setBrowserNotifyPermission] = useState<'default' | 'granted' | 'denied'>('default');
  const [logPanelOpen, setLogPanelOpen] = useState(false);
  const [registeredFleetCollapsed, setRegisteredFleetCollapsed] = useState(() => {
    try {
      const raw = localStorage.getItem(FLEET_RAIL_COLLAPSED_KEY);
      if (raw === 'true') return true;
      if (raw === 'false') return false;
    } catch {
      // Ignore localStorage read failures.
    }
    if (typeof window !== 'undefined') {
      return window.innerWidth < 1400;
    }
    return false;
  });
  const [fleetSummary, setFleetSummary] = useState({
    total: 0,
    online: 0,
    offline: 0,
    checking: 0,
    loading: true,
    onlineClients: null as number | null,
  });

  const handleOnlineClientsChange = useCallback((onlineClients: number | null) => {
    setFleetSummary((previous) => ({ ...previous, onlineClients }));
  }, []);

  const handleFleetSummaryChange = useCallback((summary: {
    total: number;
    online: number;
    offline: number;
    checking: number;
    loading: boolean;
  }) => {
    setFleetSummary((previous) => ({ ...previous, ...summary }));
  }, []);

  const lastNotifyRef = useRef<Record<string, number>>({});

  useEffect(() => {
    try {
      localStorage.setItem(FLEET_RAIL_COLLAPSED_KEY, String(registeredFleetCollapsed));
    } catch {
      // Ignore localStorage write failures.
    }
  }, [registeredFleetCollapsed]);
  const updateHeaderSummary = (summary: HeaderSummary) => {
    const normalized = normalizeHeaderSummary(summary, t(TAB_META[activeTab].descriptionKey));
    setHeaderSummary(normalized);
    const parsed = readStaleCache<Partial<Record<TabType, HeaderSummary>>>(
      HEADER_SUMMARY_CACHE_KEY,
      Number.MAX_SAFE_INTEGER,
    ).data || {};
    parsed[activeTab] = normalized;
    writeStaleCache(HEADER_SUMMARY_CACHE_KEY, parsed);
  };

  useEffect(() => {
    const cachedStore = readStaleCache<Partial<Record<TabType, HeaderSummary>>>(
      HEADER_SUMMARY_CACHE_KEY,
      HEADER_SUMMARY_CACHE_MAX_AGE_MS,
    ).data;
    const cached = cachedStore?.[activeTab];
    setHeaderSummary(normalizeHeaderSummary(cached, t(TAB_META[activeTab].descriptionKey)));
  }, [activeTab]);

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVE_TAB_CACHE_KEY, activeTab);
    } catch {
      // Ignore localStorage write failures.
    }
  }, [activeTab]);

  useEffect(() => {
    const unsubscribe = requestActivityStore.subscribe((pending) => {
      setPendingRequests(pending);
    });
    return unsubscribe;
  }, []);

  // Global keyboard shortcuts for tab navigation
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!user || e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.altKey) {
        const keyMap: Record<string, TabType> = {
          '1': 'dashboard', '2': 'inbounds', '3': 'clients',
          '4': 'traffic', '5': 'monitoring', '6': 'backup', '7': 'subscriptions',
        };
        const tab = keyMap[e.key];
        if (tab && tab in TAB_META) {
          e.preventDefault();
          setActiveTab(tab);
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [user]);

  useEffect(() => {
    const bootstrap = async () => {
      const remembered = loadRememberedUsername();
      setUser(remembered);

      try {
        const mfaStatus = await getMfaStatus();
        setMfaEnabled(mfaStatus.enabled);
      } catch {
        setMfaEnabled(false);
      }

      try {
        const verified = await verifyCurrentAuth();
        if (verified.user) {
          setAuthCredentials(verified.user, '', '', verified.ws_ticket || '', verified.role || 'viewer');
          setUser(verified.user);
          if (verified.ws_ticket) setWsTicket(verified.ws_ticket);
          setRole(verified.role || 'viewer');
          wsManager.resumeAfterAuth();
          setIsAuthenticated(true);
        }
      } catch {
        clearAuthCredentials();
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

  const endSession = () => {
    wsManager.close();
    clearManagerSnapshotCaches();
    clearAuthCredentials();
    window.dispatchEvent(new Event('sub-manager:cache-clear'));
    setUser('');
    setPassword('');
    setTotpCode('');
    setRole('viewer');
    setIsAuthenticated(false);
  };

  useEffect(() => {
    const handleAuthRequired = () => {
      endSession();
      setAuthError(t('auth.failed'));
    };

    window.addEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);
  }, [t]);

  useEffect(() => {
    if (role !== 'admin' && (activeTab === 'backup' || activeTab === 'subscriptions')) {
      setActiveTab('dashboard');
    }
  }, [activeTab, role]);

  useEffect(() => {
    if (notificationPanelOpen) {
      setUnreadCount(0);
    }
  }, [notificationPanelOpen]);

  useEffect(() => {
    if (!isAuthenticated) return;

    let cancelled = false;

    const buildSummary = async () => {
      setHeaderLoading(true);

      try {
        switch (activeTab) {
          case 'dashboard': {
            // DashboardDataProvider owns the single aggregate read.  The
            // header must not recreate /nodes + /snapshots/latest on every
            // tab entry just to decorate values already rendered below.
            if (!cancelled) {
              updateHeaderSummary({
                description: t(TAB_META.dashboard.descriptionKey),
                stats: [],
              });
            }
            break;
          }
          case 'inbounds':
          case 'clients':
          case 'traffic':
            // The active tab owns its projection. Do not issue a second
            // remote fetch merely to decorate the shared header.
            if (!cancelled) {
              updateHeaderSummary({
                description: t(TAB_META[activeTab].descriptionKey),
                stats: [],
              });
            }
            break;
          case 'monitoring': {
            const { deps, overview, stack } = await getMonitoringHeaderSource();
            const services = stack?.services ? Object.values(stack.services) as any[] : [];
            const servicesUp = services.filter((service: any) => service.ok).length;
            const sourcesTotal = overview?.summary?.sources_total || 0;
            const sourcesOnline = overview?.summary?.sources_online || 0;
            if (!cancelled) {
              updateHeaderSummary({
                description: t('header.monitoring.description'),
                stats: [
                  { label: t('header.monitoring.stackProbes'), value: `${servicesUp}/${services.length || 0}`, tone: servicesUp === services.length && services.length > 0 ? 'success' : 'warning' },
                  { label: t('header.monitoring.adguardSources'), value: `${sourcesOnline}/${sourcesTotal}`, tone: sourcesOnline > 0 ? 'success' : 'warning' },
                  { label: t('header.monitoring.blockedRate'), value: formatPercent(overview?.summary?.blocked_rate || 0), tone: 'accent' },
                  { label: t('header.monitoring.collector'), value: deps?.collector_running ? t('header.monitoring.collectorRunning') : t('header.monitoring.collectorIdle'), tone: deps?.collector_running ? 'success' : 'warning' },
                ],
              });
            }
            break;
          }
          case 'backup': {
            const { nodes } = await getBackupHeaderSource();
            const readOnly = nodes.filter((node: any) => Boolean(node.read_only)).length;
            if (!cancelled) {
              updateHeaderSummary({
                description: t('header.backup.description'),
                stats: [
                  { label: t('header.backup.knownNodes'), value: String(nodes.length) },
                  { label: t('header.backup.writable'), value: String(nodes.length - readOnly), tone: nodes.length - readOnly > 0 ? 'success' : 'warning' },
                  { label: t('header.backup.readOnly'), value: String(readOnly) },
                  { label: t('header.backup.restoreTargets'), value: String(nodes.length) },
                ],
              });
            }
            break;
          }
          case 'subscriptions': {
            const { emails, stats, nodes } = await getSubscriptionsHeaderSource();
            const domains = new Map<string, number>();
            let downloads = 0;
            let latest = 0;
            emails.forEach((email: string) => {
              const domain = email.split('@')[1] || 'unknown';
              domains.set(domain, (domains.get(domain) || 0) + 1);
              downloads += stats[email]?.count || 0;
              latest = Math.max(latest, Date.parse(stats[email]?.last || '') || 0);
            });
            const groups = Array.from(domains.values()).filter((count) => count >= 2).length;
            if (!cancelled) {
              updateHeaderSummary({
                description: t('header.subscriptions.description'),
                stats: [
                  { label: t('header.subscriptions.emailLinks'), value: formatCompactNumber(emails.length) },
                  { label: t('header.subscriptions.totalDownloads'), value: formatCompactNumber(downloads), tone: downloads > 0 ? 'accent' : 'default' },
                  { label: t('header.subscriptions.reusableGroups'), value: String(groups) },
                  { label: t('header.subscriptions.nodesInFilter'), value: String(nodes.length) },
                ],
              });
            }
            break;
          }
          default:
            break;
        }
      } catch {
        if (!cancelled && headerSummary.stats.length === 0) {
          updateHeaderSummary({
            description: t(TAB_META[activeTab].descriptionKey),
            stats: [],
          });
        }
      } finally {
        if (!cancelled) {
          setHeaderLoading(false);
        }
      }
    };

    buildSummary();

    return () => {
      cancelled = true;
    };
  }, [activeTab, isAuthenticated, key]);

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

  useWebSocketMessages({
    channels: role === 'viewer' ? ['snapshot_delta'] : ['inbounds', 'snapshot_delta'],
    enabled: isAuthenticated,
    onMessage: (msg) => {
      if (msg.type === 'snapshot_delta') {
        const node = msg.data?.data?.node || msg.data?.node || '';
        const changes = msg.data?.data?.changes || msg.data?.changes || {};
        const keys = Object.keys(changes);
        if (keys.length > 0) {
          activityLog.debug('WebSocket', `snapshot_delta: ${node}`, { changes: keys });
        }
      }
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
      const verified = await createBrowserSession(user, password, totpCode.trim());
      if (verified.user) {
        setAuthCredentials(verified.user, '', '', verified.ws_ticket || '', verified.role || 'viewer');
        setRole(verified.role || 'viewer');
        wsManager.resumeAfterAuth();
        resetAuthRequiredEventGuard();
        setIsAuthenticated(true);
        rememberUsername(user);
        setPassword('');
        setTotpCode('');
      }
    } catch (err: any) {
      setAuthError(err.response?.data?.detail || t('auth.failed'));
    }
  };

  const handleLogout = async () => {
    try {
      await clearBrowserSession();
    } finally {
      endSession();
      resetAuthRequiredEventGuard();
    }
  };

  const getApiUrl = () => {
    const host = typeof window !== 'undefined' ? window.location.host : '';
    const protocol = typeof window !== 'undefined' ? window.location.protocol : 'https:';
    const fullApiUrl = API_BASE.startsWith('http') ? API_BASE : `${protocol}//${host}${API_BASE}`;
    return fullApiUrl;
  };

  if (!authBootstrapDone) {
    return (
      <div className="login-wrapper flex min-h-screen items-center justify-center bg-[#0a0e1a]">
        <div className="flex flex-col items-center gap-3">
          <div className="h-7 w-7 animate-spin rounded-full border-2 border-cyan-500/20 border-t-cyan-300" />
          <span className="text-xs text-slate-500">{t('app.loading')}</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="login-wrapper flex min-h-screen items-center justify-center bg-[#0a0e1a]">
        <div style={{
          width: '100%',
          maxWidth: '380px',
          padding: '0 16px',
          animation: 'appFadeIn 0.3s ease both',
        }}>
          {/* Brand header */}
          <div style={{ textAlign: 'center', marginBottom: '28px' }}>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '52px',
              height: '52px',
              borderRadius: '14px',
              background: `linear-gradient(135deg, ${colors.accent}33, ${colors.accent}18)`,
              border: `1px solid ${colors.accent}44`,
              marginBottom: '14px',
              color: colors.accent,
            }}>
              <UIIcon name="logo" size={24} />
            </div>
            <h4 style={{ margin: 0, fontWeight: 700, color: colors.text.primary, fontSize: '1.15rem' }}>
              {t('app.title')}
            </h4>
            <p style={{ margin: '6px 0 0', fontSize: '0.78rem', color: colors.text.tertiary }}>
              {t('app.subtitle')}
            </p>
          </div>

          {/* Login card */}
          <div style={{
            background: '#0f1420',
            border: '1px solid rgba(34, 211, 238, 0.20)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: `0 8px 32px rgba(0,0,0,0.18), 0 1px 0 rgba(255,255,255,0.04)`,
          }}>
            <form aria-label={t('auth.signIn')} onSubmit={(e) => { e.preventDefault(); handleLogin(); }}>
              <div className="mb-3">
                <label htmlFor="login-username" className="mb-1.5 block text-xs font-semibold text-slate-400">
                  {t('auth.username')}
                </label>
                <input
                  id="login-username"
                  type="text"
                  className="block w-full rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10"
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                  required
                  autoFocus
                  autoComplete="username"
                />
              </div>
              <div className="mb-3">
                <label htmlFor="login-password" className="mb-1.5 block text-xs font-semibold text-slate-400">
                  {t('auth.password')}
                </label>
                <input
                  id="login-password"
                  type="password"
                  className="block w-full rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                />
              </div>
              {mfaEnabled && (
                <div className="mb-3">
                  <label htmlFor="login-totp" className="mb-1.5 block text-xs font-semibold text-slate-400">
                    {t('auth.totpCode')}
                  </label>
                  <input
                    id="login-totp"
                    type="text"
                    className="block w-full rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 font-mono text-sm tabular-nums text-slate-100 tracking-[0.2em] whitespace-nowrap outline-none focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10"
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                    required
                    inputMode="numeric"
                    placeholder="000000"
                  />
                </div>
              )}
              {authError && (
                <div role="alert" aria-live="assertive" style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: `1px solid ${colors.danger}44`,
                  borderLeft: `3px solid ${colors.danger}`,
                  background: `${colors.danger}12`,
                  color: colors.danger,
                  fontSize: '0.8rem',
                  marginBottom: '14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}>
                  <span>X</span>
                  <span>{authError}</span>
                </div>
              )}
              <button
                type="submit"
                className="mt-1 flex h-10 w-full items-center justify-center rounded-md bg-cyan-300 px-4 text-sm font-medium tracking-wide text-[#06111f] transition hover:bg-cyan-200"
              >
                {t('auth.signIn')}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  const tabMeta = Object.fromEntries(
    Object.entries(TAB_META).map(([key, value]) => [
      key,
      {
        ...value,
        label: t(value.labelKey),
        eyebrow: t(value.eyebrowKey),
        description: t(value.descriptionKey),
      },
    ])
  ) as Record<TabType, { icon: IconName; labelKey: string; label: string; eyebrowKey: string; descriptionKey: string; eyebrow: string; description: string }>;

  const visibleTabs: TabType[] = role === 'admin'
    ? ['dashboard', 'inbounds', 'clients', 'traffic', 'monitoring', 'backup', 'subscriptions']
    : ['dashboard', 'inbounds', 'clients', 'traffic', 'monitoring'];

  const sidebarItems: SidebarNavItem[] = visibleTabs.map((tabId) => ({
    id: tabId,
    icon: TAB_META[tabId].icon,
    labelKey: TAB_META[tabId].labelKey,
  }));
  const safeSidebarItems = Array.isArray(sidebarItems) ? sidebarItems : [];
  const safeNotifications = Array.isArray(notifications) ? notifications : [];

  const renderTabContent = (tab: TabType) => {
    switch (tab) {
      case 'dashboard':
        return (
          <DashboardDataProvider>
          <div className="dashboard-command-grid min-w-0 overflow-hidden p-6 min-h-screen transition-all duration-300 ease-in-out xl:grid xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start xl:gap-6">
            <div className="dashboard-command-grid__main min-w-0 overflow-hidden">
              <DashboardSummary onNavigate={(tab) => {
                const t = tab as TabType;
                if (t in TAB_META) {
                  setActiveTab(t);
                }
              }}
              onOnlineClientsChange={handleOnlineClientsChange}
              fleetSummary={fleetSummary}
              />
              <section className="mb-6 rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04)]">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">{t('nodes.intakeTitle').toUpperCase()}</h3>
                    <p className="mt-1 text-[10px] font-light leading-4 text-slate-500">{t('nodes.intakeHint')}</p>
                  </div>
                  <button
                    className="flex items-center gap-1 rounded-md border border-cyan-300/25 bg-gradient-to-r from-cyan-400/90 to-fuchsia-400/90 px-3 py-1.5 text-xs font-medium tracking-wide text-white shadow-[0_10px_24px_rgba(34,211,238,0.16)]"
                    type="button"
                    onClick={() => setNodeIntakeOpenSignal((value) => value + 1)}
                  >
                    {`+ ${t('nodes.addNode')}`}
                  </button>
                </div>
              </section>
              <NodeManager
                onReload={() => setKey((prev) => prev + 1)}
                showIntake={false}
                openIntakeSignal={nodeIntakeOpenSignal}
                editNode={nodeEditTarget}
                openEditSignal={nodeEditOpenSignal}
              />
              <section className="dashboard-server-deck min-w-0">
                <ServerStatus
                  dashboardMode
                  includeCounts={false}
                  includeCollectorStatus={false}
                  includePanelUpdateChecks={false}
                  includeLiveStatus={false}
                  fleetSummary={fleetSummary}
                  fleetCollapsed={registeredFleetCollapsed}
                  onToggleFleet={() => setRegisteredFleetCollapsed((value) => !value)}
                />
              </section>
            </div>
            <RegisteredFleetPanel
              collapsed={registeredFleetCollapsed}
              setCollapsed={setRegisteredFleetCollapsed}
              onSummaryChange={handleFleetSummaryChange}
              onOpenNodes={() => {
                setNodeIntakeOpenSignal((value) => value + 1);
                setRegisteredFleetCollapsed(true);
              }}
              onEditNode={(node) => {
                setNodeEditTarget(node);
                setNodeEditOpenSignal((value) => value + 1);
                setRegisteredFleetCollapsed(true);
              }}
            />
          </div>
          </DashboardDataProvider>
        );
      case 'inbounds':
        return <LazyInboundManager
          onReload={() => setKey((prev) => prev + 1)}
          onNavigateToClients={(inboundId, inboundRemark) => {
            try { sessionStorage.setItem('sm_nav_inbound_filter', JSON.stringify({ id: inboundId, remark: inboundRemark })); } catch {}
            setActiveTab('clients');
          }}
          onAddClientToInbound={(inboundId, _nodeName) => {
            try { sessionStorage.setItem('sm_nav_add_to_inbound', String(inboundId)); } catch {}
            setActiveTab('clients');
          }}
        />;
      case 'clients':
        return <LazyClientManager />;
      case 'traffic':
        return <LazyTrafficStats onNavigateToClient={(email) => {
          try { sessionStorage.setItem('sm_nav_client_search', email); } catch {}
          setActiveTab('clients');
        }} />;
      case 'monitoring':
        return <LazyMonitoringDashboard />;
      case 'backup':
        return <LazyBackupManager />;
      case 'subscriptions':
        return <LazySubscriptionManager key={key} apiUrl={getApiUrl()} />;
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
    <div className="app-layout">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        items={safeSidebarItems}
        user={user}
        onLogout={handleLogout}
        onOpenLog={() => setLogPanelOpen(v => !v)}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
      />

      <div className="app-main min-w-0 flex-1 overflow-hidden">
        <header className="app-topbar">
          <button
            className="app-topbar__menu-btn"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label={t('main.openMenu')}
          >
            <UIIcon name="menu" size={16} />
          </button>
          <h1 className="app-topbar__title">
            <span className="inline-flex items-center gap-2">
              <UIIcon name={tabMeta[activeTab].icon} size={16} />
              {tabMeta[activeTab].label}
            </span>
          </h1>

          <div className="app-topbar__actions flex items-center gap-2">
            {browserNotifySupported && browserNotifyPermission !== 'granted' && (
              <button
                className="topbar-push-btn app-topbar__command-btn inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium tracking-wide"
                onClick={requestBrowserNotifications}
              >
                {t('push.enableBrowser')}
              </button>
            )}

            <button
              className="app-topbar__command-btn app-topbar__icon-command relative inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium tracking-wide"
              onClick={() => setNotificationPanelOpen((v) => !v)}
              title={t('push.title')}
            >
              <UIIcon name="bell" size={15} />
              {unreadCount > 0 && (
                <span
                  className="absolute left-full top-0 -translate-x-1/2 -translate-y-1/2 rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none text-white"
                  style={{ backgroundColor: colors.danger }}
                >
                  {unreadCount > 99 ? '99+' : unreadCount}
                </span>
              )}
            </button>

            <button
              className={`app-topbar__command-btn inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium tracking-wide${logPanelOpen ? ' is-active' : ''}`}
              onClick={() => setLogPanelOpen(v => !v)}
              title={t('common.activityLogTitle')}
            >
              LOG
            </button>

            {activeTab === 'dashboard' && (
              <button
                className={`app-topbar__fleet-pill${registeredFleetCollapsed ? '' : ' is-open'}`}
                type="button"
                onClick={() => setRegisteredFleetCollapsed((value) => !value)}
                title={t('nodes.registeredFleet')}
              >
                <span className="app-topbar__fleet-kicker">{t('nodes.registeredFleet')}</span>
                <span className="app-topbar__fleet-meta">
                  {fleetSummary.loading
                    ? t('nodes.statusSyncing')
                    : `${fleetSummary.online}/${fleetSummary.total} ${t('nodes.online')}`}
                </span>
                <span className="app-topbar__fleet-count">{fleetSummary.total}</span>
              </button>
            )}
          </div>
        </header>

        {notificationPanelOpen && (
          <div
            className="notif-panel absolute left-4 right-4 top-14 z-50 max-h-[420px] overflow-y-auto rounded-lg border border-cyan-500/20 bg-[#0f1420] shadow-2xl sm:left-auto sm:w-full sm:max-w-[22.5rem]"
          >
            <div className="flex items-center justify-between border-b border-cyan-500/20 px-4 py-3">
              <strong className="text-sm font-medium uppercase tracking-wider text-slate-300">{t('push.title')}</strong>
              <button
                className="inline-flex h-8 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs font-medium text-slate-300 transition hover:text-cyan-200"
                onClick={() => setNotifications([])}
              >
                {t('push.clear')}
              </button>
            </div>
            <div className="p-2">
              {notifications.length === 0 && (
                <div className="text-xs text-slate-500">{t('push.empty')}</div>
              )}
              {safeNotifications.map((item) => (
                <div
                  key={item.id}
                  className="mb-2 rounded-md border border-cyan-500/20 bg-[#0a0e1a] p-2"
                >
                  <div className="flex items-center justify-between gap-3">
                    <strong className="min-w-0 truncate text-xs font-medium" style={{ color: levelColor(item.level) }}>{item.title}</strong>
                    <span className="font-mono tabular-nums whitespace-nowrap text-[11px] text-slate-500">
                      {new Date(item.ts).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-slate-300">{item.message}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <main
          className="app-content min-w-0 overflow-hidden"
          aria-busy={headerLoading || pendingRequests > 0}
        >
          <div className="tab-panel">
            <React.Suspense fallback={<div className="p-6 text-sm text-slate-400">{t('app.loading')}</div>}>
              <section key={activeTab} aria-label={TAB_META[activeTab].labelKey}>
                {renderTabContent(activeTab)}
              </section>
            </React.Suspense>
          </div>
        </main>
      </div>

      <ActivityLogPanel open={logPanelOpen} onClose={() => setLogPanelOpen(false)} />
    </div>
  );
};

const AppWithToast: React.FC = () => (
  <ToastProvider>
    <App />
  </ToastProvider>
);

export default AppWithToast;
