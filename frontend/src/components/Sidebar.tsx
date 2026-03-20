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

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  items,
  user,
  onLogout,
  mobileOpen,
  onMobileClose,
}) => {
  const { colors, themeMode, stylePreset, setThemeMode } = useTheme();
  const { t, i18n } = useTranslation();
  const currentLang = (i18n.resolvedLanguage || i18n.language || 'en').toLowerCase();
  const asciiVariants = useMemo(() => MSM_ASCII_VARIANTS, []);
  const [asciiIndex, setAsciiIndex] = useState(() => Math.floor(Math.random() * asciiVariants.length));
  const [themeMenuOpen, setThemeMenuOpen] = useState(false);

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
        className={`sidebar${mobileOpen ? ' sidebar--open' : ''}${stylePreset === '3' ? ' sidebar--preset-3' : ''}`}
        style={{ backgroundColor: colors.bg.secondary, borderRight: `1px solid ${colors.border}` }}
      >
        <div className="sidebar__logo" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <pre className="sidebar__ascii-logo mb-0" aria-label={t('sidebar.logoAria')}>
            {asciiVariants[asciiIndex]}
          </pre>
          <span className="sidebar__version-badge">v3.1</span>
        </div>

        <nav className="sidebar__nav" role="navigation" aria-label={t('sidebar.navAria')}>
          {items.map(item => (
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
            <ChoiceChips
              options={[
                { value: 'en', label: t('language.en') },
                { value: 'ru', label: t('language.ru') },
              ]}
              value={currentLang.startsWith('ru') ? 'ru' : 'en'}
              onChange={(value) => i18n.changeLanguage(value)}
              colors={colors}
            />
          </div>

          <div className="mt-2">
            <label className="form-label small mb-1" style={{ color: colors.text.secondary }}>
              {t('sidebar.themeLabel')}
            </label>
            <div style={{ position: 'relative' }}>
              <button
                className="sidebar__footer-btn w-100"
                onClick={() => setThemeMenuOpen((prev) => !prev)}
                title={t('sidebar.themeChoose')}
                style={{
                  backgroundColor: colors.bg.tertiary,
                  border: `1px solid ${colors.border}`,
                  color: colors.text.primary,
                }}
              >
                <span className="d-inline-flex align-items-center gap-2">
                  <UIIcon name={themeMode === '1' ? 'sun' : 'moon'} size={14} />
                  {t('sidebar.themeCurrent', { mode: themeMode })}
                </span>
              </button>

              {themeMenuOpen && (
                <div
                  className="mt-2 p-2 rounded"
                  style={{
                    border: `1px solid ${colors.border}`,
                    backgroundColor: colors.bg.secondary,
                    display: 'grid',
                    gap: 6,
                  }}
                >
                  {([
                    { value: '1', label: t('sidebar.theme1') },
                    { value: '2', label: t('sidebar.theme2') },
                    { value: '3', label: t('sidebar.theme3') },
                  ] as const).map((mode) => (
                    <button
                      key={mode.value}
                      className="btn btn-sm"
                      onClick={() => {
                        setThemeMode(mode.value);
                        setThemeMenuOpen(false);
                      }}
                      style={{
                        backgroundColor: themeMode === mode.value ? colors.accent : colors.bg.tertiary,
                        borderColor: themeMode === mode.value ? colors.accent : colors.border,
                        color: themeMode === mode.value ? colors.accentText : colors.text.primary,
                      }}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="sidebar__footer-actions mt-2">
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
