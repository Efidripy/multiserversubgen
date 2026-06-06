import React, { useState, useEffect, useRef } from 'react';
import { activityLog } from './services/activityLog';
import { ActivityLogPanel } from './components/ActivityLogPanel';
import { useTranslation } from 'react-i18next';
import { API_BASE } from './api';
import { ServerStatus } from './components/ServerStatus';
import { SubscriptionManager } from './components/SubscriptionManager';
import { InboundManager } from './components/InboundManager';
import { ClientManager } from './components/ClientManager';
import { TrafficStats } from './components/TrafficStats';
import { BackupManager } from './components/BackupManager';
import { MonitoringDashboard } from './components/MonitoringDashboard';
import { DashboardSummary } from './components/DashboardSummary';
import { RegisteredFleetPanel } from './components/RegisteredFleetPanel';
import { ToastProvider } from './components/Toast';
import { Sidebar, SidebarNavItem } from './components/Sidebar';
import { useTheme } from './contexts/ThemeContext';
import { useWebSocket } from './hooks/useWebSocket';
import { clearAuthCredentials, getAuth, loadRememberedUsername, rememberUsername, setAuthCredentials } from './auth';
import { getFeatureFlags, getMfaStatus, verifyCurrentAuth, verifyLoginCredentials } from './api/authService';
import {
  getBackupHeaderSource,
  getClientsHeaderSource,
  getDashboardHeaderMetrics,
  getInboundsHeaderSource,
  getMonitoringHeaderSource,
  getSubscriptionsHeaderSource,
  getTrafficHeaderSource,
} from './api/dashboard';
import { IconName, UIIcon } from './components/UIIcon';
import { requestActivityStore } from './services/requestActivity';
import { readStaleCache, writeStaleCache } from './services/staleCache';

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

const formatBytes = (bytes: number) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[unitIndex]}`;
};

const formatPercent = (value: number) => `${Number.isFinite(value) ? value.toFixed(value >= 10 ? 0 : 1) : '0'}%`;

export const App: React.FC = () => {
  const { colors } = useTheme();
  const { t } = useTranslation();

  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
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
  const [mountedTabs, setMountedTabs] = useState<TabType[]>(() => [activeTab]);
  const [key, setKey] = useState(0);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [headerSummary, setHeaderSummary] = useState<HeaderSummary>({
    description: t(TAB_META.dashboard.descriptionKey),
    stats: [],
  });
  const [headerLoading, setHeaderLoading] = useState(false);
  const [pendingRequests, setPendingRequests] = useState(0);
  const [monitoringEnabled, setMonitoringEnabled] = useState(true);

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
  });

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
    setMountedTabs((prev) => (prev.includes(activeTab) ? prev : [...prev, activeTab]));
  }, [activeTab]);

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    let cancelled = false;
    const loadFeatures = async () => {
      try {
        const payload = await getFeatureFlags();
        if (!cancelled) {
          setMonitoringEnabled(payload.monitoringEnabled !== false);
        }
      } catch {
        if (!cancelled) {
          setMonitoringEnabled(true);
        }
      }
    };
    loadFeatures();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (!monitoringEnabled && activeTab === 'monitoring') {
      setActiveTab('dashboard');
    }
  }, [monitoringEnabled, activeTab]);

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
          setMountedTabs(prev => prev.includes(tab) ? prev : [...prev, tab]);
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

      // Demo mode: skip auth if no credentials stored
      const auth = getAuth();
      if (!auth.username && !auth.password) {
        setUser('root');
        setIsAuthenticated(true);
        setAuthBootstrapDone(true);
        return;
      }

      if (auth.username && auth.password) {
        try {
          const verified = await verifyCurrentAuth();
          if (verified.user) {
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

  useEffect(() => {
    if (!isAuthenticated) return;

    let cancelled = false;

    const buildSummary = async () => {
      setHeaderLoading(true);

      try {
        switch (activeTab) {
          case 'dashboard': {
            const metrics = await getDashboardHeaderMetrics();
            if (!cancelled) {
              updateHeaderSummary({
                description: metrics.authIssues > 0
                  ? t('header.dashboard.descAuthIssue', {
                      online: metrics.reachableNow,
                      total: metrics.registeredNodes,
                      authBlocked: metrics.authIssues,
                    })
                  : t('header.dashboard.descHealthy', {
                      online: metrics.reachableNow,
                      total: metrics.registeredNodes,
                      xray: metrics.xrayRunning,
                    }),
                stats: [
                  { label: t('header.dashboard.registeredNodes'), value: String(metrics.registeredNodes) },
                  { label: t('header.dashboard.reachableNow'), value: String(metrics.reachableNow), tone: metrics.reachableNow > 0 ? 'success' : 'warning' },
                  { label: t('header.dashboard.authIssues'), value: String(metrics.authIssues), tone: metrics.authIssues > 0 ? 'danger' : 'default' },
                  { label: t('header.dashboard.offlineNodes'), value: String(metrics.offlineNodes), tone: metrics.offlineNodes > 0 ? 'warning' : 'default' },
                  { label: t('header.dashboard.xrayRunning'), value: String(metrics.xrayRunning), tone: metrics.xrayRunning > 0 ? 'accent' : 'warning' },
                  { label: t('header.dashboard.onlineClients'), value: formatCompactNumber(metrics.onlineClients) },
                ],
              });
            }
            break;
          }
          case 'inbounds': {
            const inbounds = await getInboundsHeaderSource();
            const enabled = inbounds.filter((item: any) => item.enable).length;
            const protocols = new Set(inbounds.map((item: any) => item.protocol).filter(Boolean)).size;
            const nodesCovered = new Set(inbounds.map((item: any) => item.node_name).filter(Boolean)).size;
            if (!cancelled) {
              updateHeaderSummary({
                description: t('header.inbounds.description'),
                stats: [
                  { label: t('header.inbounds.totalInbounds'), value: String(inbounds.length) },
                  { label: t('header.inbounds.enabled'), value: String(enabled), tone: enabled > 0 ? 'success' : 'warning' },
                  { label: t('header.inbounds.protocols'), value: String(protocols) },
                  { label: t('header.inbounds.coveredNodes'), value: String(nodesCovered) },
                ],
              });
            }
            break;
          }
          case 'clients': {
            const { clients, nodes } = await getClientsHeaderSource();
            const enabled = clients.filter((item: any) => item.enable).length;
            const expiringSoon = clients.filter((item: any) => {
              const expiry = Number(item.expiryTime || 0);
              return expiry > Date.now() && expiry - Date.now() <= 7 * 24 * 60 * 60 * 1000;
            }).length;
            if (!cancelled) {
              updateHeaderSummary({
                description: t('header.clients.description'),
                stats: [
                  { label: t('header.clients.clientRecords'), value: formatCompactNumber(clients.length) },
                  { label: t('header.clients.enabled'), value: formatCompactNumber(enabled), tone: enabled > 0 ? 'success' : 'warning' },
                  { label: t('header.clients.expiringIn7d'), value: String(expiringSoon), tone: expiringSoon > 0 ? 'warning' : 'default' },
                  { label: t('header.clients.availableNodes'), value: String(nodes.length) },
                ],
              });
            }
            break;
          }
          case 'traffic': {
            const { onlineClients, stats: statsObj } = await getTrafficHeaderSource();
            const trafficEntries = Object.entries(statsObj) as Array<[string, { up?: number; down?: number; total?: number }]>;
            const totalTraffic = trafficEntries.reduce((sum, [, value]) => sum + (value.total || value.up || 0) + (value.total ? 0 : value.down || 0), 0);
            const heaviest = trafficEntries
              .map(([name, value]) => ({ name, total: value.total || (value.up || 0) + (value.down || 0) }))
              .sort((a, b) => b.total - a.total)[0];
            if (!cancelled) {
              updateHeaderSummary({
                description: t('header.traffic.description'),
                stats: [
                  { label: t('header.traffic.onlineNow'), value: formatCompactNumber(onlineClients.length), tone: onlineClients.length > 0 ? 'success' : 'default' },
                  { label: t('header.traffic.trackedEntries'), value: formatCompactNumber(trafficEntries.length) },
                  { label: t('header.traffic.totalTraffic'), value: formatBytes(totalTraffic), tone: 'accent' },
                  { label: t('header.traffic.heaviestClient'), value: heaviest ? heaviest.name : t('header.common.none') },
                ],
              });
            }
            break;
          }
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

  useWebSocket({
    url: '',
    channels: ['inbounds', 'snapshot_delta'],
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
      const verified = await verifyLoginCredentials(user, password, totpCode.trim());
      if (verified.user) {
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
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
          <div className="spinner-border" style={{ color: colors.accent, width: '1.8rem', height: '1.8rem', borderWidth: '0.15em' }} />
          <span style={{ color: colors.text.tertiary, fontSize: '0.8rem' }}>{t('app.loading')}</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="login-wrapper min-vh-100 d-flex align-items-center justify-content-center" style={{ backgroundColor: colors.bg.primary }}>
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
              Multi-server VPN panel manager
            </p>
          </div>

          {/* Login card */}
          <div style={{
            background: colors.bg.secondary,
            border: `1px solid ${colors.border}`,
            borderRadius: '16px',
            padding: '24px',
            boxShadow: `0 8px 32px rgba(0,0,0,0.18), 0 1px 0 rgba(255,255,255,0.04)`,
          }}>
            <form onSubmit={(e) => { e.preventDefault(); handleLogin(); }}>
              <div className="mb-3">
                <label className="form-label" style={{ color: colors.text.secondary, fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                  {t('auth.username')}
                </label>
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
                <label className="form-label" style={{ color: colors.text.secondary, fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                  {t('auth.password')}
                </label>
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
                  <label className="form-label" style={{ color: colors.text.secondary, fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                    {t('auth.totpCode')}
                  </label>
                  <input
                    type="text"
                    className="form-control text-tabular"
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, letterSpacing: '0.2em' }}
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                    required
                    inputMode="numeric"
                    placeholder="000000"
                  />
                </div>
              )}
              {authError && (
                <div style={{
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
                  <span>✕</span>
                  <span>{authError}</span>
                </div>
              )}
              <button
                type="submit"
                className="btn w-100"
                style={{
                  backgroundColor: colors.accent,
                  borderColor: colors.accent,
                  color: colors.accentText,
                  fontWeight: 700,
                  fontSize: '0.85rem',
                  padding: '0.54rem 1rem',
                  marginTop: '4px',
                }}
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

  const visibleTabs: TabType[] = (monitoringEnabled
    ? ['dashboard', 'inbounds', 'clients', 'traffic', 'monitoring', 'backup', 'subscriptions']
    : ['dashboard', 'inbounds', 'clients', 'traffic', 'backup', 'subscriptions']);

  const sidebarItems: SidebarNavItem[] = visibleTabs.map((tabId) => ({
    id: tabId,
    icon: TAB_META[tabId].icon,
    labelKey: TAB_META[tabId].labelKey,
  }));
  const safeSidebarItems = Array.isArray(sidebarItems) ? sidebarItems : [];
  const safeNotifications = Array.isArray(notifications) ? notifications : [];
  const safeHeaderStats = Array.isArray(headerSummary.stats) ? headerSummary.stats : [];
  const safeMountedTabs = Array.isArray(mountedTabs) ? mountedTabs : [];

  const renderTabContent = (tab: TabType) => {
    switch (tab) {
      case 'dashboard':
        return (
          <div className={`dashboard-command-grid dashboard-shell p-6 min-h-screen transition-all duration-300 ease-in-out ${registeredFleetCollapsed ? 'pr-6' : 'xl:pr-[429px] pr-6'}`}>
            <div className="dashboard-command-grid__main min-w-0">
              <DashboardSummary onNavigate={(tab) => {
                const t = tab as TabType;
                if (t in TAB_META) {
                  setActiveTab(t);
                  setMountedTabs(prev => prev.includes(t) ? prev : [...prev, t]);
                }
              }}
              heroDescription={headerSummary.description}
              heroStats={headerSummary.stats}
              fleetSummary={fleetSummary}
              />
              <section className="mb-6 bg-[#0f1420] rounded-lg p-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-bold text-cyan-300 font-mono uppercase tracking-wider">{t('nodes.intakeTitle').toUpperCase()}</h3>
                    <p className="text-[10px] text-gray-500 font-mono mt-1">{t('nodes.intakeHint')}</p>
                  </div>
                  <button
                    className="px-3 py-1.5 bg-gradient-to-r from-cyan-400/90 to-fuchsia-400/90 text-white rounded-lg font-mono font-bold text-xs flex items-center gap-1"
                    type="button"
                    onClick={() => {
                      setActiveTab('inbounds');
                      setMountedTabs(prev => prev.includes('inbounds') ? prev : [...prev, 'inbounds']);
                    }}
                  >
                    {`+ ${t('nodes.addNode')}`}
                  </button>
                </div>
              </section>
              <section className="dashboard-server-deck min-w-0">
                <ServerStatus
                  dashboardMode
                  includeCounts={false}
                  includeCollectorStatus={false}
                  includePanelUpdateChecks={false}
                  fleetSummary={fleetSummary}
                  fleetCollapsed={registeredFleetCollapsed}
                  onToggleFleet={() => setRegisteredFleetCollapsed((value) => !value)}
                />
              </section>
            </div>
            <RegisteredFleetPanel
              collapsed={registeredFleetCollapsed}
              setCollapsed={setRegisteredFleetCollapsed}
              onSummaryChange={setFleetSummary}
              onOpenNodes={() => {
                setActiveTab('inbounds');
                setMountedTabs(prev => prev.includes('inbounds') ? prev : [...prev, 'inbounds']);
                setRegisteredFleetCollapsed(true);
              }}
            />
          </div>
        );
      case 'inbounds':
        return <InboundManager
          onReload={() => setKey((prev) => prev + 1)}
          onNavigateToClients={(inboundId, inboundRemark) => {
            try { sessionStorage.setItem('sm_nav_inbound_filter', JSON.stringify({ id: inboundId, remark: inboundRemark })); } catch {}
            setActiveTab('clients');
            setMountedTabs(prev => prev.includes('clients') ? prev : [...prev, 'clients']);
          }}
          onAddClientToInbound={(inboundId, _nodeName) => {
            try { sessionStorage.setItem('sm_nav_add_to_inbound', String(inboundId)); } catch {}
            setActiveTab('clients');
            setMountedTabs(prev => prev.includes('clients') ? prev : [...prev, 'clients']);
          }}
        />;
      case 'clients':
        return <ClientManager />;
      case 'traffic':
        return <TrafficStats onNavigateToClient={(email) => {
          try { sessionStorage.setItem('sm_nav_client_search', email); } catch {}
          setActiveTab('clients');
          setMountedTabs(prev => prev.includes('clients') ? prev : [...prev, 'clients']);
        }} />;
      case 'monitoring':
        return monitoringEnabled ? <MonitoringDashboard /> : null;
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
      className={`app-layout${activeTab === 'dashboard' ? ' dashboard-shell app-layout--dashboard-shell' : ''}`}
      style={{
        backgroundColor: activeTab === 'dashboard' ? '#0a0e1a' : colors.bg.primary,
        color: activeTab === 'dashboard' ? '#f8fafc' : colors.text.primary,
        fontFamily: activeTab === 'dashboard'
          ? 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace'
          : 'var(--font-sans)',
      }}
    >
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

      <div className={`app-main${activeTab === 'dashboard' ? ' app-main--dashboard-shell' : ''}`} style={{ position: 'relative' }}>
        <header
          className={`app-topbar${activeTab === 'dashboard' ? ' app-topbar--dashboard-shell' : ''}`}
          style={activeTab === 'dashboard' ? undefined : { backgroundColor: colors.bg.secondary, borderBottom: `1px solid ${colors.border}` }}
        >
          <button
            className="app-topbar__menu-btn"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label={t('main.openMenu')}
            style={activeTab === 'dashboard' ? undefined : { color: colors.text.primary, backgroundColor: colors.bg.tertiary, border: `1px solid ${colors.border}` }}
          >
            <UIIcon name="menu" size={16} />
          </button>
          <h1 className="app-topbar__title" style={activeTab === 'dashboard' ? undefined : { color: colors.text.primary }}>
            <span className="d-inline-flex align-items-center gap-2">
              <UIIcon name={tabMeta[activeTab].icon} size={16} />
              {tabMeta[activeTab].label}
            </span>
          </h1>

          <div className={`d-flex align-items-center gap-2${activeTab === 'dashboard' ? ' app-topbar__actions' : ''}`}>
            {browserNotifySupported && browserNotifyPermission !== 'granted' && (
              <button
                className={`btn btn-sm topbar-push-btn${activeTab === 'dashboard' ? ' app-topbar__command-btn' : ''}`}
                style={activeTab === 'dashboard' ? undefined : { backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                onClick={requestBrowserNotifications}
              >
                {t('push.enableBrowser')}
              </button>
            )}

            <button
              className={`btn btn-sm position-relative${activeTab === 'dashboard' ? ' app-topbar__command-btn app-topbar__icon-command' : ''}`}
              style={activeTab === 'dashboard' ? undefined : { backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
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

            <button
              className={`btn btn-sm${activeTab === 'dashboard' ? ` app-topbar__command-btn${logPanelOpen ? ' is-active' : ''}` : ''}`}
              style={activeTab === 'dashboard' ? undefined : { backgroundColor: logPanelOpen ? '#1f6feb' : colors.bg.tertiary, borderColor: logPanelOpen ? '#1f6feb' : colors.border, color: logPanelOpen ? '#fff' : colors.text.primary, fontFamily: 'monospace', fontSize: '0.72rem' }}
              onClick={() => setLogPanelOpen(v => !v)}
              title="Activity Log"
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
            className="card notif-panel"
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
              {safeNotifications.map((item) => (
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

        <main className={`app-content${activeTab === 'dashboard' ? ' app-content--dashboard-shell' : ''}`}>
          {activeTab !== 'dashboard' && (
            <section className="app-shell-header">
              <div className="app-shell-header__hero card p-4">
                <div className="app-shell-header__main">
                  <div className="app-shell-header__intro">
                    <div className="app-shell-header__eyebrow">{tabMeta[activeTab].eyebrow}</div>
                    <h1 className="app-shell-header__title">
                      <span className="d-inline-flex align-items-center gap-2">
                        <UIIcon name={tabMeta[activeTab].icon} size={18} />
                        {tabMeta[activeTab].label}
                      </span>
                    </h1>
                    <p className="app-shell-header__copy">{headerSummary.description}</p>
                    {(headerLoading || pendingRequests > 0) && <div className="app-shell-header__live-note">{t('header.updating')}</div>}
                  </div>

                  <div className="app-shell-header__stats">
                    {safeHeaderStats.map((stat) => (
                      <article key={stat.label} className={`app-shell-stat app-shell-stat--${stat.tone || 'default'}`}>
                        <span className="app-shell-stat__label">{stat.label}</span>
                        <span className="app-shell-stat__value">{stat.value}</span>
                      </article>
                    ))}
                    {headerLoading && safeHeaderStats.length === 0 && (
                      <article className="app-shell-stat app-shell-stat--default">
                        <span className="app-shell-stat__label">{t('header.sync')}</span>
                        <span className="app-shell-stat__value">{t('app.loading')}</span>
                      </article>
                    )}
                  </div>
                </div>
              </div>
            </section>
          )}

          <div className="tab-panel">
            {safeMountedTabs.map((tabId) => (
              <section
                key={tabId}
                style={{ display: activeTab === tabId ? 'block' : 'none' }}
                aria-hidden={activeTab !== tabId}
              >
                {renderTabContent(tabId)}
              </section>
            ))}
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
