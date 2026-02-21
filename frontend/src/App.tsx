import React, { useState, useEffect } from 'react';
import api, { API_BASE } from './api';
import { NodeManager } from './components/NodeManager';
import { SubscriptionManager } from './components/SubscriptionManager';
import { InboundManager } from './components/InboundManager';
import { ServerStatus } from './components/ServerStatus';
import { ClientManager } from './components/ClientManager';
import { TrafficStats } from './components/TrafficStats';
import { BackupManager } from './components/BackupManager';
import { useTheme } from './contexts/ThemeContext';

type TabType = 'dashboard' | 'servers' | 'inbounds' | 'clients' | 'traffic' | 'backup' | 'subscriptions';

export const App: React.FC = () => {
  const { theme, toggleTheme, colors } = useTheme();
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authError, setAuthError] = useState('');
  const [activeTab, setActiveTab] = useState<TabType>('dashboard');
  const [key, setKey] = useState(0);

  useEffect(() => {
    const saved = localStorage.getItem('sub_auth');
    if (saved) {
      const { user: u, password: p } = JSON.parse(saved);
      setUser(u);
      setPassword(p);
      setIsAuthenticated(true);
    }
  }, []);

  const handleLogin = async () => {
    setAuthError('');
    try {
      const res = await api.get('/v1/auth/verify', {
        auth: { username: user, password }
      });
      if (res.data.user) {
        setIsAuthenticated(true);
        localStorage.setItem('sub_auth', JSON.stringify({ user, password }));
        setPassword(''); // не хранить пароль в памяти
      }
    } catch (err: any) {
      setAuthError(err.response?.data?.detail || 'Authentication failed');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('sub_auth');
    setUser('');
    setPassword('');
    setIsAuthenticated(false);
  };

  const getApiUrl = () => {
    const host = typeof window !== 'undefined' ? window.location.host : '';
    const protocol = typeof window !== 'undefined' ? window.location.protocol : 'https:';
    // API_BASE may be relative (e.g. "/my-vpn/api") or absolute; build a full URL for display
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
            {authError && <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>{authError}</div>}
            <button type="submit" className="btn w-100" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}>
              Sign In
            </button>
          </form>
        </div>
      </div>
    );
  }

  const tabs: Array<{id: TabType, label: string, icon: string}> = [
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'servers', label: 'Servers', icon: '🖥️' },
    { id: 'inbounds', label: 'Inbounds', icon: '📡' },
    { id: 'clients', label: 'Clients', icon: '👥' },
    { id: 'traffic', label: 'Traffic', icon: '📈' },
    { id: 'backup', label: 'Backup', icon: '💾' },
    { id: 'subscriptions', label: 'Subscriptions', icon: '🔗' },
  ];

  const renderTabContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return (
          <div>
            <ServerStatus />
          </div>
        );
      case 'servers':
        return (
          <div>
            <h4 className="mb-4" style={{ color: colors.accent }}>🖥️ Server Management</h4>
            <NodeManager onReload={() => setKey(prev => prev + 1)} />
            <div className="mt-4">
              <ServerStatus />
            </div>
          </div>
        );
      case 'inbounds':
        return (
          <div>
            <InboundManager onReload={() => setKey(prev => prev + 1)} />
          </div>
        );
      case 'clients':
        return <ClientManager />;
      case 'traffic':
        return <TrafficStats />;
      case 'backup':
        return <BackupManager />;
      case 'subscriptions':
        return (
          <div>
            <h4 className="mb-4" style={{ color: colors.accent }}>🔗 Subscriptions</h4>
            <SubscriptionManager key={key} apiUrl={getApiUrl()} />
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="app-container min-vh-100" style={{ backgroundColor: colors.bg.primary, color: colors.text.primary, fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif' }}>
      <nav className="navbar border-bottom" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border + ' !important' }}>
        <div className="container-fluid">
          <a className="navbar-brand" href="#" style={{ fontSize: '1.2rem', color: colors.text.primary }}>
            📡 Multi-Server Manager <span className="badge ms-2" style={{ fontSize: '0.7rem', backgroundColor: colors.accent, color: '#ffffff' }}>v3.1</span>
          </a>
          <span className="navbar-text" style={{ color: colors.text.secondary }}>
            <button 
              className="btn btn-sm me-2"
              onClick={toggleTheme}
              title="Toggle theme"
              style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
            >
              {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
            </button>
            <span className="me-3">👤 <strong style={{ color: colors.text.primary }}>{user}</strong></span>
            <button className="btn btn-sm" style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }} onClick={handleLogout}>
              Logout
            </button>
          </span>
        </div>
      </nav>

      {/* Tab Navigation */}
      <div className="border-bottom" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="container-fluid">
          <ul className="nav nav-tabs border-0" style={{ borderBottom: 'none' }}>
            {tabs.map(tab => (
              <li className="nav-item" key={tab.id}>
                <button
                  className="nav-link border-0"
                  onClick={() => setActiveTab(tab.id)}
                  style={{
                    backgroundColor: activeTab === tab.id ? colors.bg.primary : 'transparent',
                    borderBottom: activeTab === tab.id ? `2px solid ${colors.accent}` : 'none',
                    fontWeight: activeTab === tab.id ? 'bold' : 'normal',
                    color: activeTab === tab.id ? colors.text.primary : colors.text.secondary,
                  }}
                >
                  {tab.icon} {tab.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Tab Content */}
      <div className="container-fluid py-4">
        {renderTabContent()}
      </div>
    </div>
  );
};
