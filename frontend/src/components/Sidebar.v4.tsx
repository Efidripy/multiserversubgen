import React, { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  LayoutDashboard,
  Server,
  Users,
  Activity,
  Database,
  Shield,
  HardDrive,
  User,
  LogOut,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { MSM_ASCII_VARIANTS } from './msmAsciiVariants';

type TabType = 'dashboard' | 'inbounds' | 'clients' | 'traffic' | 'monitoring' | 'backup' | 'subscriptions';

export interface SidebarNavItem {
  id: TabType;
  labelKey: string;
  disabled?: boolean;
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
  currentLang: string;
  onLanguageChange: (lang: string) => void;
}

// Tab grouping configuration
const TAB_GROUPS: Record<TabType, { group: string; groupLabel: string } | null> = {
  dashboard: null,
  inbounds: { group: 'data', groupLabel: 'nav.groupData' },
  clients: { group: 'data', groupLabel: 'nav.groupData' },
  traffic: { group: 'data', groupLabel: 'nav.groupData' },
  monitoring: { group: 'system', groupLabel: 'nav.groupSystem' },
  backup: { group: 'system', groupLabel: 'nav.groupSystem' },
  subscriptions: { group: 'settings', groupLabel: 'nav.groupSettings' },
};

// Icon mapping
const TAB_ICONS: Record<TabType, React.ReactNode> = {
  dashboard: <LayoutDashboard className="w-4 h-4" />,
  inbounds: <Server className="w-4 h-4" />,
  clients: <Users className="w-4 h-4" />,
  traffic: <Activity className="w-4 h-4" />,
  monitoring: <Shield className="w-4 h-4" />,
  backup: <HardDrive className="w-4 h-4" />,
  subscriptions: <Database className="w-4 h-4" />,
};

export const SidebarV4: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  items,
  user,
  onLogout,
  onOpenLog,
  mobileOpen,
  onMobileClose,
  currentLang,
  onLanguageChange,
}) => {
  const { t } = useTranslation();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const asciiVariants = useMemo(() => MSM_ASCII_VARIANTS, []);
  const [asciiIndex, setAsciiIndex] = useState(() => Math.floor(Math.random() * asciiVariants.length));

  useEffect(() => {
    const timer = setInterval(() => {
      setAsciiIndex(prev => (prev + 1) % asciiVariants.length);
    }, 2600);
    return () => clearInterval(timer);
  }, [asciiVariants.length]);

  const handleNav = (tabId: TabType) => {
    setActiveTab(tabId);
    onMobileClose();
  };

  // Group items by category
  const groupedItems = items.reduce((acc, item) => {
    const groupInfo = TAB_GROUPS[item.id];
    const groupKey = groupInfo?.group ?? 'main';
    if (!acc[groupKey]) acc[groupKey] = [];
    acc[groupKey].push(item);
    return acc;
  }, {} as Record<string, SidebarNavItem[]>);

  const groupOrder = ['main', 'data', 'system', 'settings'];

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 lg:hidden z-30"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`bg-[#0f1420] backdrop-blur-sm border-r border-cyan-500/20 flex flex-col h-screen fixed lg:relative top-0 left-0 z-40 lg:z-auto transition-all duration-300 ${
          isCollapsed ? 'w-16' : 'w-60'
        } ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}
      >
        {/* Neon border effect */}
        <div className="absolute inset-y-0 right-0 w-[1px] bg-gradient-to-b from-transparent via-cyan-400/30 to-transparent pointer-events-none" />

        {/* Header with logo and collapse button */}
        <div className="p-4 border-b border-cyan-500/20 flex items-center justify-between relative z-10">
          {!isCollapsed && (
            <div className="flex-1 mr-2">
              <pre className="text-[10px] leading-tight font-mono text-cyan-300 whitespace-pre-wrap break-words overflow-hidden max-h-12">
                {asciiVariants[asciiIndex]}
              </pre>
              <span className="inline-block px-2 py-0.5 bg-magenta-500/20 text-magenta-300 border border-magenta-500/40 rounded text-xs font-mono font-bold mt-2">
                v3.1
              </span>
            </div>
          )}
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className={`w-8 h-8 bg-[#0a0e1a] border border-cyan-500/20 rounded hover:border-cyan-400/30 hover:shadow-lg hover:shadow-cyan-400/20 transition-all flex items-center justify-center flex-shrink-0`}
            title={isCollapsed ? t('sidebar.expand', 'Expand') : t('sidebar.collapse', 'Collapse')}
          >
            {isCollapsed ? (
              <ChevronRight className="w-4 h-4 text-cyan-300" />
            ) : (
              <ChevronLeft className="w-4 h-4 text-cyan-300" />
            )}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <div className="space-y-1">
            {groupOrder.map(groupKey => {
              const groupItems = groupedItems[groupKey] || [];
              if (groupItems.length === 0) return null;

              const groupInfo = groupKey !== 'main' ? TAB_GROUPS[groupItems[0].id] : null;

              return (
                <div key={groupKey}>
                  {groupInfo && !isCollapsed && (
                    <div className="text-[10px] text-gray-600 font-mono uppercase tracking-wider mb-2 mt-3 first:mt-0">
                      {t(groupInfo.groupLabel)}
                    </div>
                  )}

                  {groupItems.map(item => {
                    const isActive = activeTab === item.id;
                    const isDisabled = item.disabled;

                    const baseClasses = `flex items-center gap-2 rounded-lg transition-all font-mono text-xs relative group ${
                      isCollapsed ? 'justify-center px-2 py-2' : 'px-3 py-2'
                    }`;

                    const stateClasses = isDisabled
                      ? 'text-gray-600 cursor-not-allowed border border-transparent'
                      : isActive
                      ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 shadow-lg shadow-cyan-500/5'
                      : 'text-gray-400 hover:text-cyan-300 hover:bg-cyan-500/5 border border-transparent hover:border-cyan-500/20';

                    return (
                      <button
                        key={item.id}
                        onClick={() => !isDisabled && handleNav(item.id)}
                        disabled={isDisabled}
                        className={`w-full text-left ${baseClasses} ${stateClasses}`}
                        title={isCollapsed ? t(item.labelKey) : undefined}
                        aria-current={isActive ? 'page' : undefined}
                      >
                        <div className="relative z-10 flex items-center gap-2 flex-1">
                          {TAB_ICONS[item.id]}
                          {!isCollapsed && (
                            <span className="truncate">{t(item.labelKey).toUpperCase()}</span>
                          )}
                        </div>
                        {isActive && !isCollapsed && (
                          <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-6 bg-gradient-to-b from-cyan-400 to-magenta-400 rounded-r" />
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </nav>

        {/* Footer */}
        <div className="p-3 border-t border-cyan-500/20 space-y-3 relative z-10">
          {!isCollapsed ? (
            <>
              {/* User section */}
              <div className="flex items-center gap-2 text-gray-400">
                <User className="w-4 h-4 flex-shrink-0" />
                <span className="text-sm font-bold text-white font-mono truncate">{user}</span>
              </div>

              {/* Language selector */}
              <div>
                <label className="text-[10px] text-gray-500 font-mono uppercase tracking-wider mb-1.5 block">
                  {t('language.title', 'Language')}
                </label>
                <div className="flex gap-1">
                  <button
                    onClick={() => onLanguageChange('en')}
                    className={`px-2 py-1 rounded text-[10px] font-mono transition-all ${
                      currentLang === 'en'
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                        : 'text-gray-400 hover:text-cyan-300 border border-transparent hover:bg-cyan-500/5'
                    }`}
                  >
                    {t('language.en')}
                  </button>
                  <button
                    onClick={() => onLanguageChange('ru')}
                    className={`px-2 py-1 rounded text-[10px] font-mono transition-all ${
                      currentLang === 'ru'
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                        : 'text-gray-400 hover:text-cyan-300 border border-transparent hover:bg-cyan-500/5'
                    }`}
                  >
                    {t('language.ru')}
                  </button>
                </div>
              </div>

              {/* Action buttons */}
              <div className="space-y-1.5 pt-1">
                <button
                  onClick={onOpenLog}
                  className="w-full px-3 py-1.5 bg-[#0a0e1a] border border-cyan-500/20 rounded text-gray-400 hover:text-cyan-300 hover:border-cyan-400/30 transition-all font-mono text-[10px] text-left"
                  title={t('sidebar.activityLog', 'Activity Log')}
                >
                  📋 {t('sidebar.activityLog', 'Activity Log')}
                </button>
                <a
                  href="/api/docs"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block w-full px-3 py-1.5 bg-[#0a0e1a] border border-cyan-500/20 rounded text-gray-400 hover:text-cyan-300 hover:border-cyan-400/30 transition-all font-mono text-[10px]"
                  title={t('sidebar.apiDocs', 'API Docs')}
                >
                  📖 {t('sidebar.apiDocs', 'API Docs')}
                </a>
                <button
                  onClick={onLogout}
                  className="w-full px-3 py-1.5 bg-red-400/10 border border-red-400/30 rounded text-red-400 hover:bg-red-400/20 transition-all font-mono text-[10px] text-left flex items-center gap-2"
                  title={t('auth.logout', 'Logout')}
                >
                  <LogOut className="w-3 h-3 flex-shrink-0" />
                  {t('auth.logout', 'Logout')}
                </button>
              </div>
            </>
          ) : (
            <>
              {/* Collapsed state - icons only */}
              <button
                className="w-full p-2 bg-[#0a0e1a] border border-cyan-500/20 rounded text-gray-400 hover:text-cyan-300 hover:border-cyan-400/30 transition-all flex items-center justify-center"
                title={`${t('label.user', 'User')}: ${user}`}
              >
                <User className="w-4 h-4" />
              </button>
              <button
                onClick={onOpenLog}
                className="w-full p-2 bg-[#0a0e1a] border border-cyan-500/20 rounded text-gray-400 hover:text-cyan-300 hover:border-cyan-400/30 transition-all flex items-center justify-center"
                title={t('sidebar.activityLog', 'Activity Log')}
              >
                <Activity className="w-4 h-4" />
              </button>
              <button
                onClick={onLogout}
                className="w-full p-2 bg-red-400/10 border border-red-400/30 rounded text-red-400 hover:bg-red-400/20 transition-all flex items-center justify-center"
                title={t('auth.logout', 'Logout')}
              >
                <LogOut className="w-4 h-4" />
              </button>
            </>
          )}
        </div>
      </aside>
    </>
  );
};
