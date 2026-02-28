import React, { useState, useEffect } from 'react';
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
import { clearAuthCredentials, loadRememberedUsername, rememberUsername, setAuthCredentials } from './auth';

type TabType = 'dashboard' | 'servers' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions';

export const App: React.FC = () => {
  const { theme, toggleTheme, colors } = useTheme();
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authError, setAuthError] = useState('');
  const [activeTab, setActiveTab] = useState<TabType>('dashboard');
  const [key, setKey] = useState(0);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  useEffect(() => {
    setUser(loadRememberedUsername());
    api.get('/v1/auth/mfa-status')
      .then((res) => setMfaEnabled(Boolean(res.data?.enabled)))
      .catch(() => setMfaEnabled(false));
  }, []);

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
      setAuthError(err.response?.data?.detail || 'Authentication failed');
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
    // API_BASE may be relative (e.g. "/my-panel/api") or absolute; build a full URL for display
    const fullApiUrl = API_BASE.startsWith('http') ? API_BASE : `${protocol}//${host}${API_BASE}`;
    return fullApiUrl;
  };

  if (!isAuthenticated) {
    return (
      <div className="login-wrapper min-vh-100 d-flex align-items-center justify-content-center" style={{ backgroundColor: colors.bg.primary }}>
        <div className="card p-4" style={{ maxWidth: '400px', width: '100%', backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
          <div className="d-flex justify-content-between align-items-center mb-4">
            <h5 className="mb-0" style={{ color: colors.text.primary }}>📡 Multi-Server Manager</h5>
            <button 
              className="btn btn-sm btn-outline-secondary"
              onClick={toggleTheme}
              title="Toggle theme"
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
          </div>
          <form onSubmit={(e) => { e.preventDefault(); handleLogin(); }}>
            <div className="mb-3">
              <label className="form-label" style={{ color: colors.text.secondary }}>Username</label>
              <input
                type="text"
                className="form-control"
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                value={user}
                onChange={(e) => setUser(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="mb-3">
              <label className="form-label" style={{ color: colors.text.secondary }}>Password</label>
              <input
                type="password"
                className="form-control"
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {mfaEnabled && (
              <div className="mb-3">
                <label className="form-label" style={{ color: colors.text.secondary }}>TOTP Code</label>
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
              Sign In
            </button>
          </form>
        </div>
      </div>
    );
  }

  const tabTitles: Record<TabType, string> = {
    dashboard: '📊 Dashboard',
    servers: '🖥️ Server Management',
    inbounds: '🔌 Inbounds',
    clients: '👥 Clients',
    traffic: '📈 Traffic',
    monitoring: '📉 Monitoring',
    backup: '💾 Backup',
    subscriptions: '📜 Subscriptions',
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return <ServerStatus />;
      case 'servers':
        return <NodeManager onReload={() => setKey(prev => prev + 1)} />;
      case 'inbounds':
        return <InboundManager onReload={() => setKey(prev => prev + 1)} />;
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

  return (
    <div
      className="app-layout"
      style={{
        backgroundColor: colors.bg.primary,
        color: colors.text.primary,
        fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif',
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

      <div className="app-main">
        {/* Mobile top bar */}
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
            ☰
          </button>
          <h1 className="app-topbar__title" style={{ color: colors.text.primary }}>
            {tabTitles[activeTab]}
          </h1>
        </header>

        {/* Main content */}
        <main className="app-content">
          <div className="tab-panel">
            {renderTabContent()}
          </div>
        </main>
      </div>
    </div>
  );
};
