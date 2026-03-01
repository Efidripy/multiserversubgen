import React from 'react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../contexts/ThemeContext';

type TabType = 'dashboard' | 'servers' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions';

interface SidebarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  user: string;
  onLogout: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const navItems: Array<{ id: TabType; icon: string; labelKey: string }> = [
  { id: 'dashboard', icon: '📊', labelKey: 'nav.dashboard' },
  { id: 'servers', icon: '🖥️', labelKey: 'nav.nodes' },
  { id: 'inbounds', icon: '🔌', labelKey: 'nav.inbounds' },
  { id: 'clients', icon: '👥', labelKey: 'nav.clients' },
  { id: 'traffic', icon: '📈', labelKey: 'nav.traffic' },
  { id: 'monitoring', icon: '📉', labelKey: 'nav.monitoring' },
  { id: 'backup', icon: '💾', labelKey: 'nav.backup' },
  { id: 'subscriptions', icon: '📜', labelKey: 'nav.subscriptions' },
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
  const { t, i18n } = useTranslation();
  const currentLang = (i18n.resolvedLanguage || i18n.language || 'en').toLowerCase();

  const handleNav = (tab: TabType) => {
    setActiveTab(tab);
    onMobileClose();
  };

  return (
    <>
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
        <div className="sidebar__logo" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <span style={{ color: colors.text.primary, fontWeight: 700, fontSize: '1rem' }}>
            📡 {t('app.title')}
          </span>
          <span
            className="badge ms-2"
            style={{ backgroundColor: colors.accent, color: '#fff', fontSize: '0.65rem' }}
          >
            v3.1
          </span>
        </div>

        <nav className="sidebar__nav" role="navigation" aria-label="Main navigation">
          {navItems.map(item => (
            <button
              key={item.id}
              className={`sidebar__nav-item${activeTab === item.id ? ' sidebar__nav-item--active' : ''}`}
              onClick={() => handleNav(item.id)}
              style={{
                color: activeTab === item.id ? colors.accent : colors.text.secondary,
                backgroundColor: activeTab === item.id ? colors.accent + '18' : 'transparent',
                borderLeft: activeTab === item.id
                  ? `3px solid ${colors.accent}`
                  : '3px solid transparent',
              }}
            >
              <span className="sidebar__nav-icon">{item.icon}</span>
              <span>{t(item.labelKey)}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar__spacer" />

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

          <div className="mt-2">
            <label className="form-label small mb-1" style={{ color: colors.text.secondary }}>
              {t('language.title')}
            </label>
            <select
              className="form-select form-select-sm"
              value={currentLang.startsWith('ru') ? 'ru' : 'en'}
              onChange={(e) => i18n.changeLanguage(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="en">{t('language.en')}</option>
              <option value="ru">{t('language.ru')}</option>
            </select>
          </div>

          <div className="sidebar__footer-actions mt-2">
            <button
              className="sidebar__footer-btn"
              onClick={toggleTheme}
              title={t('theme.toggle')}
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
              {t('auth.logout')}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
};
