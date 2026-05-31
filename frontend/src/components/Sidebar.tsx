import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../contexts/ThemeContext';
import { ChoiceChips } from './ChoiceChips';
import { IconName, UIIcon } from './UIIcon';
import { MSM_ASCII_VARIANTS } from './msmAsciiVariants';

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
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const NAV_GROUPS: Record<string, string | null> = {
  dashboard:     null,
  inbounds:      'nav.groupData',
  clients:       null,
  traffic:       null,
  monitoring:    'nav.groupSystem',
  backup:        null,
  subscriptions: 'nav.groupSettings',
};

function getNavGroupLabel(id: string, prevId?: string): string | null {
  const labelKey = NAV_GROUPS[id] ?? null;
  if (!labelKey) return null;
  const prevLabelKey = prevId ? (NAV_GROUPS[prevId] ?? null) : null;
  return labelKey !== prevLabelKey ? labelKey : null;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  items,
  user,
  onLogout,
  mobileOpen,
  onMobileClose,
}) => {
  const { colors } = useTheme();
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
          <pre className="sidebar__ascii-logo mb-0" aria-label={t('sidebar.logoAria')}>
            {asciiVariants[asciiIndex]}
          </pre>
          <span className="sidebar__version-badge">v3.1</span>
        </div>

        <nav className="sidebar__nav" role="navigation" aria-label={t('sidebar.navAria')}>
          {items.map((item, idx) => {
            const prev = items[idx - 1];
            const groupLabel = getNavGroupLabel(item.id, prev?.id);
            return (
              <React.Fragment key={item.id}>
                {groupLabel && (
                  <div className="sidebar__nav-group-label">{t(groupLabel)}</div>
                )}
                <button
                  className={`sidebar__nav-item${activeTab === item.id ? ' sidebar__nav-item--active' : ''}`}
                  onClick={() => handleNav(item.id)}
                  aria-current={activeTab === item.id ? 'page' : undefined}
                >
                  <span className="sidebar__nav-icon"><UIIcon name={item.icon} size={16} /></span>
                  <span>{t(item.labelKey)}</span>
                </button>
              </React.Fragment>
            );
          })}
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
            <ChoiceChips
              options={[
                { value: 'en', label: t('language.en') },
                { value: 'ru', label: t('language.ru') },
              ]}
              value={currentLang.startsWith('ru') ? 'ru' : 'en'}
              onChange={(value) => i18n.changeLanguage(value)}
            />
          </div>


          <div className="sidebar__footer-actions mt-2">
            <button
              className="sidebar__footer-btn"
              style={{
                backgroundColor: colors.bg.tertiary,
                border: `1px solid ${colors.border}`,
                color: colors.text.secondary,
                width: '100%',
                marginBottom: '4px',
              }}
              title={t('sidebar.keyboardShortcutsTitle')}
              onClick={() => {
                const shortcuts = [
                  'Tab navigation:',
                  '  Alt+1 → Dashboard',
                  '  Alt+2 → Inbounds',
                  '  Alt+3 → Clients',
                  '  Alt+4 → Traffic',
                  '  Alt+5 → Monitoring',
                  '  Alt+6 → Backup',
                  '  Alt+7 → Subscriptions',
                  '',
                  'In Clients tab:',
                  '  Ctrl+/ → focus search',
                  '  Click stats chips → quick filter',
                  '  Click node/protocol badges → filter',
                  '  Click ▸ email → expand row details',
                  '  Click ∞ limit cell → set GB limit',
                  '  Click expiry date → set new date',
                  '',
                  'In Inbounds tab:',
                  '  Click protocol badge → filter',
                  '  Click security badge → filter',
                  '  Click node name badge → filter',
                  '  Click client count badge → go to clients',
                  '  Click + button → add client to inbound',
                  '',
                  'Dashboard:',
                  '  Click stat tiles → go to relevant tab',
                  '  Click top client email → filter clients',
                ].join('\n');
                alert(shortcuts);
              }}
            >
              ⌨ {t('sidebar.shortcuts')}
            </button>
            <a
              href="/api/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="sidebar__footer-btn"
              style={{
                backgroundColor: colors.bg.tertiary,
                border: `1px solid ${colors.border}`,
                color: colors.text.secondary,
                display: 'block',
                textDecoration: 'none',
                textAlign: 'center',
                marginBottom: '4px',
              }}
              title={t('sidebar.apiDocsTitle')}
            >
              📖 {t('sidebar.apiDocs')}
            </a>
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
