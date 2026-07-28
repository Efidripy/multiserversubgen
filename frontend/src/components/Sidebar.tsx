import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, ChevronLeft, ChevronRight, ClipboardList, Home, Keyboard, LogOut } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext';
import { ChoiceChips } from './ChoiceChips';
import { IconName, UIIcon } from './UIIcon';
import { API_BASE } from '../api/client';

type TabType = 'dashboard' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions';

export interface SidebarNavItem {
  id: TabType;
  icon: IconName;
  labelKey: string;
}

interface SidebarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  items: SidebarNavItem[];
  user: string;
  onLogout: () => void;
  onOpenLog: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  items,
  user,
  onLogout,
  onOpenLog,
  mobileOpen,
  onMobileClose,
}) => {
  const { colors } = useTheme();
  const { t, i18n } = useTranslation();
  const currentLang = (i18n.resolvedLanguage || i18n.language || 'en').toLowerCase();
  const safeItems = Array.isArray(items) ? items : [];
  const [collapsed, setCollapsed] = useState(false);
  const effectiveCollapsed = collapsed && !mobileOpen;
  const renderExpandedFooter = !effectiveCollapsed;
  const renderCollapsedFooter = effectiveCollapsed;

  const handleNav = (tab: TabType) => {
    setActiveTab(tab);
    onMobileClose();
  };

  const handleHome = () => {
    setActiveTab('dashboard');
    onMobileClose();
  };

  const handleCollapseClick = () => {
    if (mobileOpen && window.matchMedia('(max-width: 1024px)').matches) {
      onMobileClose();
      return;
    }
    setCollapsed((value) => !value);
  };

  const shortcutText = [
    'Tab navigation:',
    '  Alt+1 -> Dashboard',
    '  Alt+2 -> Inbounds',
    '  Alt+3 -> Clients',
    '  Alt+4 -> Traffic',
    '  Alt+5 -> Monitoring',
    '  Alt+6 -> Backup',
    '  Alt+7 -> Subscriptions',
    '',
    'Dashboard:',
    '  Click stat tiles -> go to relevant tab',
    '  Click top client email -> filter clients',
  ].join('\n');

  return (
    <>
      {mobileOpen && (
        <div
          className={`sidebar-overlay${mobileOpen ? ' is-visible' : ''}`}
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`sidebar${mobileOpen ? ' sidebar--open' : ''}${effectiveCollapsed ? ' sidebar--collapsed' : ''}`}
      >
        <div className="sidebar__logo">
          <div className="sidebar__brand-lockup" aria-label={t('sidebar.logoAria')}>
            <span className="sidebar__version-badge">v3.1</span>
          </div>
          <button
            className="sidebar__collapse-btn"
            type="button"
            onClick={handleCollapseClick}
            title={effectiveCollapsed ? t('common.expand', 'Expand') : t('common.close')}
            aria-label={effectiveCollapsed ? t('common.expand', 'Expand') : t('common.close')}
          >
            {effectiveCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>

        <nav className="sidebar__nav" role="navigation" aria-label={t('sidebar.navAria')}>
          {safeItems.map((item) => (
            <button
              key={item.id}
              className={`sidebar__nav-item${activeTab === item.id ? ' sidebar__nav-item--active' : ''}`}
              onClick={() => handleNav(item.id)}
              aria-current={activeTab === item.id ? 'page' : undefined}
              title={effectiveCollapsed ? t(item.labelKey) : undefined}
            >
              <span className="sidebar__nav-icon"><UIIcon name={item.icon} size={16} /></span>
              <span className="sidebar__nav-label">{t(item.labelKey)}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar__spacer" />

        <div className="sidebar__footer">
          {renderExpandedFooter && (
            <div className="sidebar__footer-expanded">
              <div className="sidebar__user" style={{ color: colors.text.secondary }}>
                <span className="sidebar__user-icon"><UIIcon name="user" size={16} /></span>
                <span className="sidebar__username" style={{ color: colors.text.primary, fontWeight: 600 }}>
                  {user}
                </span>
              </div>

              <div className="sidebar__language">
                <label className="sidebar__language-label" style={{ color: colors.text.secondary }}>
                  {t('language.title')}
                </label>
                <ChoiceChips
                  className="sidebar__language-tabs"
                  options={[
                    { value: 'en', label: t('language.en') },
                    { value: 'ru', label: t('language.ru') },
                  ]}
                  value={currentLang.startsWith('ru') ? 'ru' : 'en'}
                  onChange={(value) => i18n.changeLanguage(value)}
                />
              </div>

              <div className="sidebar__footer-actions">
                <button
                  className="sidebar__footer-btn"
                  title={t('sidebar.keyboardShortcutsTitle')}
                  onClick={() => alert(shortcutText)}
                >
                  <span className="sidebar__footer-icon"><Keyboard className="w-3.5 h-3.5 opacity-60" /></span>
                  <span className="sidebar__footer-label">{t('sidebar.shortcuts')}</span>
                </button>
                <button
                  className="sidebar__footer-btn"
                  onClick={onOpenLog}
                  title={t('sidebar.activityLog')}
                >
                  <span className="sidebar__footer-icon"><ClipboardList className="w-3.5 h-3.5 opacity-60" /></span>
                  <span className="sidebar__footer-label">{t('sidebar.activityLog', 'Activity Log')}</span>
                </button>
                <a
                  href={`${API_BASE}/docs`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="sidebar__footer-btn"
                  title={t('sidebar.apiDocsTitle')}
                >
                  <span className="sidebar__footer-icon"><BookOpen className="w-3.5 h-3.5 opacity-60" /></span>
                  <span className="sidebar__footer-label">{t('sidebar.apiDocs')}</span>
                </a>
                <button
                  className="sidebar__footer-btn sidebar__logout"
                  onClick={onLogout}
                >
                  <span className="sidebar__footer-icon"><LogOut className="w-3.5 h-3.5 opacity-60" /></span>
                  <span className="sidebar__footer-label">{t('auth.logout')}</span>
                </button>
              </div>

              <button
                className="sidebar__back-selector"
                type="button"
                title={t('sidebar.backToSelector')}
                onClick={handleHome}
              >
                <Home className="w-3.5 h-3.5" />
                <span>{t('sidebar.backToSelector')}</span>
              </button>
            </div>
          )}

          {renderCollapsedFooter && (
            <div className="sidebar__footer-collapsed">
              <div className="sidebar__collapsed-card sidebar__collapsed-card--user" title={user} aria-label={user}>
                <UIIcon name="user" size={18} />
              </div>
              <button
                className="sidebar__collapsed-card sidebar__collapsed-card--logout"
                onClick={onLogout}
                title={t('auth.logout')}
                aria-label={t('auth.logout')}
              >
                <LogOut className="w-4 h-4" />
              </button>
              <button
                className="sidebar__collapsed-back"
                type="button"
                title={t('sidebar.backToSelector')}
                aria-label={t('sidebar.backToSelector')}
                onClick={handleHome}
              >
                <Home className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
};
