import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../contexts/ThemeContext';
import { IconName, UIIcon } from './UIIcon';
import { MSM_ASCII_VARIANTS } from './msmAsciiVariants';

type TabType = 'dashboard' | 'servers' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions';

interface SidebarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  user: string;
  onLogout: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const navItems: Array<{ id: TabType; icon: IconName; labelKey: string }> = [
  { id: 'dashboard', icon: 'dashboard', labelKey: 'nav.dashboard' },
  { id: 'servers', icon: 'servers', labelKey: 'nav.nodes' },
  { id: 'inbounds', icon: 'inbounds', labelKey: 'nav.inbounds' },
  { id: 'clients', icon: 'clients', labelKey: 'nav.clients' },
  { id: 'traffic', icon: 'traffic', labelKey: 'nav.traffic' },
  { id: 'monitoring', icon: 'monitoring', labelKey: 'nav.monitoring' },
  { id: 'backup', icon: 'backup', labelKey: 'nav.backup' },
  { id: 'subscriptions', icon: 'subscriptions', labelKey: 'nav.subscriptions' },
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
  const asciiVariants = useMemo(() => MSM_ASCII_VARIANTS, []);
  const [asciiIndex, setAsciiIndex] = useState(() => Math.floor(Math.random() * asciiVariants.length));

  const handleNav = (tab: TabType) => {
    setActiveTab(tab);
    onMobileClose();
  };

  useEffect(() => {
    const timer = setInterval(() => {
      setAsciiIndex(prev => (prev + 1) % asciiVariants.length);
    }, 2600);
    return () => clearInterval(timer);
  }, [asciiVariants.length]);

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
          <pre className="sidebar__ascii-logo mb-0" aria-label="MSM logo">
            {asciiVariants[asciiIndex]}
          </pre>
          <span className="sidebar__version-badge">v3.1</span>
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
              <span className="sidebar__nav-icon"><UIIcon name={item.icon} size={17} /></span>
              <span>{t(item.labelKey)}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar__spacer" />

        <div className="sidebar__footer" style={{ borderTop: `1px solid ${colors.border}` }}>
          <div className="sidebar__user" style={{ color: colors.text.secondary }}>
            <span style={{ fontSize: '1.1rem' }}><UIIcon name="user" size={16} /></span>
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
              {theme === 'dark' ? <UIIcon name="sun" size={14} /> : <UIIcon name="moon" size={14} />}
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
