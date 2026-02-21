import React from 'react';
import { useTheme } from '../contexts/ThemeContext';

type TabType = 'dashboard' | 'servers' | 'inbounds' | 'clients' | 'traffic' | 'backup' | 'subscriptions';

interface SidebarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  user: string;
  onLogout: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const navItems: Array<{ id: TabType; label: string; icon: string }> = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'servers', label: 'Servers', icon: '🖥️' },
  { id: 'inbounds', label: 'Inbounds', icon: '🔌' },
  { id: 'clients', label: 'Clients', icon: '👥' },
  { id: 'traffic', label: 'Traffic', icon: '📈' },
  { id: 'backup', label: 'Backup', icon: '💾' },
  { id: 'subscriptions', label: 'Subscriptions', icon: '📜' },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  user,
  onLogout,
  mobileOpen,
  onMobileClose,
}) => {
  const { colors, theme, toggleTheme } = useTheme();

  const handleNav = (tab: TabType) => {
    setActiveTab(tab);
    onMobileClose();
  };

  return (
    <>
      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="sidebar-overlay"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`sidebar${mobileOpen ? ' sidebar--open' : ''}`}
        style={{ backgroundColor: colors.bg.secondary, borderRight: `1px solid ${colors.border}` }}
      >
        {/* Logo */}
        <div className="sidebar__logo" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <span style={{ color: colors.text.primary, fontWeight: 700, fontSize: '1rem' }}>
            📡 Multi-Server Manager
          </span>
          <span
            className="badge ms-2"
            style={{ backgroundColor: colors.accent, color: '#fff', fontSize: '0.65rem' }}
          >
            v3.1
          </span>
        </div>

        {/* Navigation */}
        <nav className="sidebar__nav" role="navigation" aria-label="Main navigation">
          {navItems.map(item => (
            <button
              key={item.id}
              className={`sidebar__nav-item${activeTab === item.id ? ' sidebar__nav-item--active' : ''}`}
              onClick={() => handleNav(item.id)}
              style={{
                color: activeTab === item.id ? colors.accent : colors.text.secondary,
                backgroundColor:
                  activeTab === item.id ? colors.accent + '18' : 'transparent',
                borderLeft: activeTab === item.id
                  ? `3px solid ${colors.accent}`
                  : '3px solid transparent',
              }}
            >
              <span className="sidebar__nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {/* Spacer */}
        <div className="sidebar__spacer" />

        {/* User + controls */}
        <div className="sidebar__footer" style={{ borderTop: `1px solid ${colors.border}` }}>
          <div className="sidebar__user" style={{ color: colors.text.secondary }}>
            <span style={{ fontSize: '1.1rem' }}>👤</span>
            <span
              className="sidebar__username"
              style={{ color: colors.text.primary, fontWeight: 600 }}
            >
              {user}
            </span>
          </div>
          <div className="sidebar__footer-actions">
            <button
              className="sidebar__footer-btn"
              onClick={toggleTheme}
              title="Toggle theme"
              style={{
                backgroundColor: colors.bg.tertiary,
                border: `1px solid ${colors.border}`,
                color: colors.text.primary,
              }}
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <button
              className="sidebar__footer-btn sidebar__logout"
              onClick={onLogout}
              style={{
                backgroundColor: colors.danger + '18',
                border: `1px solid ${colors.danger}40`,
                color: colors.danger,
              }}
            >
              Logout
            </button>
          </div>
        </div>
      </aside>
    </>
  );
};
