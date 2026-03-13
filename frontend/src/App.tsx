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

const HEADER_SUMMARY_CACHE_KEY = 'sub_manager_header_summary_cache_v1';
const ACTIVE_TAB_CACHE_KEY = 'sub_manager_active_tab_v1';

const TAB_META: Record<TabType, { icon: IconName; labelKey: string; eyebrow: string; description: string }> = {
  dashboard: {
    icon: 'dashboard',
    labelKey: 'nav.dashboard',
    eyebrow: 'Mission Control',
    description: 'Local command overview for nodes, xray state and the most important operational checks.'
  },
  inbounds: {
    icon: 'inbounds',
    labelKey: 'nav.inbounds',
    eyebrow: 'Ingress Matrix',
    description: 'Inspect ports, remarks and protocol exposure without leaving the main control surface.'
  },
  clients: {
    icon: 'clients',
    labelKey: 'nav.clients',
    eyebrow: 'Client Directory',
    description: 'Search, sort and manage client records across the connected local panels.'
  },
  traffic: {
    icon: 'traffic',
    labelKey: 'nav.traffic',
    eyebrow: 'Usage Telemetry',
    description: 'Watch active sessions, heavy users and current transfer distribution in one place.'
  },
  monitoring: {
    icon: 'monitoring',
    labelKey: 'nav.monitoring',
    eyebrow: 'Signal Deck',
    description: 'Review stack health, historical charts and AdGuard metrics through the same visual language.'
  },
  backup: {
    icon: 'backup',
    labelKey: 'nav.backup',
    eyebrow: 'Recovery Operations',
    description: 'Operate backups and restores from grouped blocks without a scattered workflow.'
  },
  subscriptions: {
    icon: 'subscriptions',
    labelKey: 'nav.subscriptions',
    eyebrow: 'Link Delivery',
    description: 'Build filtered subscription output and copy delivery links from a tighter control layout.'
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
  const { theme, toggleTheme, colors } = useTheme();
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
  const [key, setKey] = useState(0);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [headerSummary, setHeaderSummary] = useState<HeaderSummary>({
    description: TAB_META.dashboard.description,
    stats: [],
  });
  const [headerLoading, setHeaderLoading] = useState(false);

  const [notifications, setNotifications] = useState<UiNotification[]>([]);
  const [notificationPanelOpen, setNotificationPanelOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [browserNotifySupported, setBrowserNotifySupported] = useState(false);
  const [browserNotifyPermission, setBrowserNotifyPermission] = useState<'default' | 'granted' | 'denied'>('default');

  const lastNotifyRef = useRef<Record<string, number>>({});
  const updateHeaderSummary = (summary: HeaderSummary) => {
    setHeaderSummary(summary);
    try {
      const raw = localStorage.getItem(HEADER_SUMMARY_CACHE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      parsed[activeTab] = summary;
      localStorage.setItem(HEADER_SUMMARY_CACHE_KEY, JSON.stringify(parsed));
    } catch {
      // Ignore cache failures.
    }
  };

  useEffect(() => {
    try {
      const raw = localStorage.getItem(HEADER_SUMMARY_CACHE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<Record<TabType, HeaderSummary>>;
      const cached = parsed?.[activeTab];
      if (cached?.description && Array.isArray(cached.stats)) {
        updateHeaderSummary(cached);
      }
    } catch {
      // Ignore malformed cache.
    }
  }, [activeTab]);

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVE_TAB_CACHE_KEY, activeTab);
    } catch {
      // Ignore localStorage write failures.
    }
  }, [activeTab]);

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

  useEffect(() => {
    if (!isAuthenticated) return;

    let cancelled = false;

    const buildSummary = async () => {
      const auth = getAuth();
      setHeaderLoading(true);

      try {
        switch (activeTab) {
          case 'dashboard': {
            const [nodesRes, snapshotRes] = await Promise.all([
              api.get('/v1/nodes', { auth }),
              api.get('/v1/snapshots/latest', { auth }),
            ]);
            const nodes = Array.isArray(nodesRes.data) ? nodesRes.data : [];
            const snapshotNodes = Array.isArray(snapshotRes.data?.nodes) ? snapshotRes.data.nodes : [];
            const online = snapshotNodes.filter((node: any) => node.available).length;
            const authBlocked = snapshotNodes.filter((node: any) => node.reason === 'auth_failed' || node.reason === 'two_factor_required').length;
            const down = snapshotNodes.filter((node: any) => !node.available).length;
            const xray = snapshotNodes.filter((node: any) => node.xray_running).length;
            const onlineClients = snapshotNodes.reduce((sum: number, node: any) => sum + (node.online_clients || 0), 0);
            if (!cancelled) {
              updateHeaderSummary({
                description: authBlocked > 0
                  ? `${online}/${nodes.length || snapshotNodes.length || 0} nodes answer polling. ${authBlocked} node${authBlocked === 1 ? '' : 's'} currently fail auth.`
                  : `${online}/${nodes.length || snapshotNodes.length || 0} nodes answer polling right now. Xray is up on ${xray} nodes.`,
                stats: [
                  { label: 'Registered nodes', value: String(nodes.length || snapshotNodes.length || 0) },
                  { label: 'Reachable now', value: String(online), tone: online > 0 ? 'success' : 'warning' },
                  { label: 'Auth issues', value: String(authBlocked), tone: authBlocked > 0 ? 'danger' : 'default' },
                  { label: 'Offline nodes', value: String(down), tone: down > 0 ? 'warning' : 'default' },
                  { label: 'Xray running', value: String(xray), tone: xray > 0 ? 'accent' : 'warning' },
                  { label: 'Online clients', value: formatCompactNumber(onlineClients) },
                ],
              });
            }
            break;
          }
          case 'inbounds': {
            const res = await api.get('/v1/inbounds', { auth });
            const inbounds = Array.isArray(res.data) ? res.data : [];
            const enabled = inbounds.filter((item: any) => item.enable).length;
            const protocols = new Set(inbounds.map((item: any) => item.protocol).filter(Boolean)).size;
            const nodesCovered = new Set(inbounds.map((item: any) => item.node_name).filter(Boolean)).size;
            if (!cancelled) {
              updateHeaderSummary({
                description: `Ports and remarks are now summarized directly in the page header instead of a decorative banner.`,
                stats: [
                  { label: 'Total inbounds', value: String(inbounds.length) },
                  { label: 'Enabled', value: String(enabled), tone: enabled > 0 ? 'success' : 'warning' },
                  { label: 'Protocols', value: String(protocols) },
                  { label: 'Covered nodes', value: String(nodesCovered) },
                ],
              });
            }
            break;
          }
          case 'clients': {
            const [clientsRes, nodesRes] = await Promise.all([
              api.get('/v1/clients', { auth }),
              api.get('/v1/nodes', { auth }),
            ]);
            const clients = Array.isArray(clientsRes.data) ? clientsRes.data : [];
            const nodes = Array.isArray(nodesRes.data) ? nodesRes.data : [];
            const enabled = clients.filter((item: any) => item.enable).length;
            const expiringSoon = clients.filter((item: any) => {
              const expiry = Number(item.expiryTime || 0);
              return expiry > Date.now() && expiry - Date.now() <= 7 * 24 * 60 * 60 * 1000;
            }).length;
            if (!cancelled) {
              updateHeaderSummary({
                description: `Client operations now surface the live fleet size, enabled accounts and upcoming expirations in the header.`,
                stats: [
                  { label: 'Client records', value: formatCompactNumber(clients.length) },
                  { label: 'Enabled', value: formatCompactNumber(enabled), tone: enabled > 0 ? 'success' : 'warning' },
                  { label: 'Expiring in 7d', value: String(expiringSoon), tone: expiringSoon > 0 ? 'warning' : 'default' },
                  { label: 'Available nodes', value: String(nodes.length) },
                ],
              });
            }
            break;
          }
          case 'traffic': {
            const [onlineRes, trafficRes] = await Promise.all([
              api.get('/v1/clients/online', { auth }),
              api.get('/v1/traffic/stats', { auth, params: { group_by: 'client' } }),
            ]);
            const onlineClients = Array.isArray(onlineRes.data?.online_clients) ? onlineRes.data.online_clients : [];
            const statsObj = trafficRes.data?.stats || {};
            const trafficEntries = Object.entries(statsObj) as Array<[string, { up?: number; down?: number; total?: number }]>;
            const totalTraffic = trafficEntries.reduce((sum, [, value]) => sum + (value.total || value.up || 0) + (value.total ? 0 : value.down || 0), 0);
            const heaviest = trafficEntries
              .map(([name, value]) => ({ name, total: value.total || (value.up || 0) + (value.down || 0) }))
              .sort((a, b) => b.total - a.total)[0];
            if (!cancelled) {
              updateHeaderSummary({
                description: `The traffic header now surfaces who is online, how much data moved and which client currently leads the table.`,
                stats: [
                  { label: 'Online now', value: formatCompactNumber(onlineClients.length), tone: onlineClients.length > 0 ? 'success' : 'default' },
                  { label: 'Tracked entries', value: formatCompactNumber(trafficEntries.length) },
                  { label: 'Total traffic', value: formatBytes(totalTraffic), tone: 'accent' },
                  { label: 'Heaviest client', value: heaviest ? heaviest.name : 'None' },
                ],
              });
            }
            break;
          }
          case 'monitoring': {
            const [depsRes, overviewRes, stackRes] = await Promise.allSettled([
              api.get('/v1/health/deps', { auth }),
              api.get('/v1/adguard/overview', { auth }),
              api.get('/v1/monitoring/stack', { auth }),
            ]);
            const deps = depsRes.status === 'fulfilled' ? depsRes.value.data : null;
            const overview = overviewRes.status === 'fulfilled' ? overviewRes.value.data : null;
            const stack = stackRes.status === 'fulfilled' ? stackRes.value.data : null;
            const services = stack?.services ? Object.values(stack.services) as any[] : [];
            const servicesUp = services.filter((service: any) => service.ok).length;
            const sourcesTotal = overview?.summary?.sources_total || 0;
            const sourcesOnline = overview?.summary?.sources_online || 0;
            if (!cancelled) {
              updateHeaderSummary({
                description: `Monitoring now summarizes stack probes and AdGuard collection directly in the first block instead of dead filler text.`,
                stats: [
                  { label: 'Stack probes', value: `${servicesUp}/${services.length || 0}`, tone: servicesUp === services.length && services.length > 0 ? 'success' : 'warning' },
                  { label: 'AdGuard sources', value: `${sourcesOnline}/${sourcesTotal}`, tone: sourcesOnline > 0 ? 'success' : 'warning' },
                  { label: 'Blocked rate', value: formatPercent(overview?.summary?.blocked_rate || 0), tone: 'accent' },
                  { label: 'Collector', value: deps?.collector_running ? 'Running' : 'Idle', tone: deps?.collector_running ? 'success' : 'warning' },
                ],
              });
            }
            break;
          }
          case 'backup': {
            const res = await api.get('/v1/nodes', { auth });
            const nodes = Array.isArray(res.data) ? res.data : [];
            const readOnly = nodes.filter((node: any) => Boolean(node.read_only)).length;
            if (!cancelled) {
              updateHeaderSummary({
                description: `Recovery operations now expose fleet coverage and writable targets before you touch import or restore actions.`,
                stats: [
                  { label: 'Known nodes', value: String(nodes.length) },
                  { label: 'Writable', value: String(nodes.length - readOnly), tone: nodes.length - readOnly > 0 ? 'success' : 'warning' },
                  { label: 'Read-only', value: String(readOnly) },
                  { label: 'Restore targets', value: String(nodes.length) },
                ],
              });
            }
            break;
          }
          case 'subscriptions': {
            const [emailsRes, nodesRes] = await Promise.all([
              api.get('/v1/emails', { auth }),
              api.get('/v1/nodes', { auth }),
            ]);
            const emails = Array.isArray(emailsRes.data?.emails) ? emailsRes.data.emails : [];
            const stats = emailsRes.data?.stats || {};
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
            const nodes = Array.isArray(nodesRes.data) ? nodesRes.data : [];
            if (!cancelled) {
              updateHeaderSummary({
                description: `Subscription delivery now promotes real output volume and grouping signals instead of a generic hero statement.`,
                stats: [
                  { label: 'Email links', value: formatCompactNumber(emails.length) },
                  { label: 'Total downloads', value: formatCompactNumber(downloads), tone: downloads > 0 ? 'accent' : 'default' },
                  { label: 'Reusable groups', value: String(groups) },
                  { label: 'Nodes in filter', value: String(nodes.length) },
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
            description: TAB_META[activeTab].description,
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
            <button type="submit" className="btn w-100" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}>
              {t('auth.signIn')}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const tabMeta = Object.fromEntries(
    Object.entries(TAB_META).map(([key, value]) => [
      key,
      { ...value, label: t(value.labelKey) },
    ])
  ) as Record<TabType, { icon: IconName; labelKey: string; label: string; eyebrow: string; description: string }>;

  const renderTabContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return (
          <div className="d-grid gap-3">
            <NodeManager onReload={() => setKey((prev) => prev + 1)} showFleet={false} />
            <div className="dashboard-main-grid">
              <div className="dashboard-main-grid__status">
                <ServerStatus />
              </div>
              <div className="dashboard-main-grid__fleet">
                <NodeManager onReload={() => setKey((prev) => prev + 1)} showIntake={false} />
              </div>
            </div>
          </div>
        );
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
                  {headerLoading && <div className="app-shell-header__live-note">Updating data in background...</div>}
                </div>

                <div className="app-shell-header__stats">
                  {headerSummary.stats.map((stat) => (
                    <article key={stat.label} className={`app-shell-stat app-shell-stat--${stat.tone || 'default'}`}>
                      <span className="app-shell-stat__label">{stat.label}</span>
                      <span className="app-shell-stat__value">{stat.value}</span>
                    </article>
                  ))}
                  {headerLoading && headerSummary.stats.length === 0 && (
                    <article className="app-shell-stat app-shell-stat--default">
                      <span className="app-shell-stat__label">Sync</span>
                      <span className="app-shell-stat__value">Loading...</span>
                    </article>
                  )}
                </div>
              </div>
            </div>
          </section>

          <div className="tab-panel">
            {renderTabContent()}
          </div>
        </main>
      </div>
    </div>
  );
};
