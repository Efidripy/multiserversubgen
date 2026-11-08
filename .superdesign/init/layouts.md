# Layouts

App shell = `.app-layout` flex row: `Sidebar` (collapsible, mobile drawer) + `.app-main` with sticky `.app-topbar` (menu button, section title with network-activity dot, notifications bell, LOG button, fleet pill on dashboard) and `.app-content` rendering the active tab.

### `frontend/src/components/Sidebar.tsx`

```tsx
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, ChevronLeft, ChevronRight, ClipboardList, Home, Keyboard, LogOut } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext';
import { ChoiceChips } from './ChoiceChips';
import { IconName, UIIcon } from './UIIcon';
import { API_BASE } from '../api/client';

type TabType = 'dashboard' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions' | 'telegram';

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
    '  Alt+8 -> Telegram',
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

```

### `frontend/src/App.tsx` (render section, lines 915-1062)

```tsx
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

      <div ref={pullToRefresh.rootRef} className="app-main min-w-0 flex-1 overflow-hidden" {...pullToRefresh.handlers}>
        <div
          className={`app-pull-refresh is-${pullToRefresh.state}`}
          role="status"
          aria-live="polite"
          aria-busy={pullToRefresh.state === 'refreshing'}
          style={{ '--pull-distance': `${pullToRefresh.pullDistance}px` } as React.CSSProperties}
        >
          <UIIcon name="refresh" size={14} />
          <span>{pullRefreshLabel}</span>
        </div>
        <header className="app-topbar">
          <button
            className="app-topbar__menu-btn"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label={t('main.openMenu')}
          >
            <UIIcon name="menu" size={16} />
          </button>
          <h1 className="app-topbar__title">
            <span className="app-topbar__title-content">
              <UIIcon name={tabMeta[activeTab].icon} size={16} />
              <span className="app-topbar__title-label">{tabMeta[activeTab].label}</span>
            </span>
            <SectionNetworkActivity
              active={pendingRequests > 0}
              label={t('app.networkActivity')}
            />
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

```
