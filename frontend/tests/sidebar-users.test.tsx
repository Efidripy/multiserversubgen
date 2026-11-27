import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '../src/components/Sidebar';
import { ThemeProvider } from '../src/contexts/ThemeContext';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en', resolvedLanguage: 'en', changeLanguage: vi.fn() } }),
}));

const props = { activeTab: 'dashboard' as const, setActiveTab: vi.fn(), items: [], user: 'admin', onLogout: vi.fn(), onOpenLog: vi.fn(), mobileOpen: false, onMobileClose: vi.fn() };

afterEach(() => cleanup());

describe('Sidebar user management control', () => {
  it('shows the settings button only when user management is allowed', () => {
    const onOpenUsers = vi.fn();
    const { rerender } = render(<ThemeProvider><Sidebar {...props} canManageUsers={false} onOpenUsers={vi.fn()} /></ThemeProvider>);
    expect(screen.queryByRole('button', { name: 'usersAdmin.open' })).toBeNull();
    const preferences = screen.getByRole('button', { name: 'sidebar.preferences' });
    expect(preferences.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(preferences);
    expect(screen.getByText('language.title')).toBeTruthy();
    fireEvent.click(preferences);
    expect(screen.queryByText('language.title')).toBeNull();
    rerender(<ThemeProvider><Sidebar {...props} canManageUsers onOpenUsers={onOpenUsers} /></ThemeProvider>);
    expect(screen.getByRole('button', { name: 'usersAdmin.open' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'usersAdmin.open' }).className).toContain('sidebar__user-settings');
    fireEvent.click(screen.getByRole('button', { name: 'usersAdmin.open' }));
    expect(onOpenUsers).toHaveBeenCalledTimes(1);
  });
});
