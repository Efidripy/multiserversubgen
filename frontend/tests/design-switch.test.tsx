import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const i18nMock = { language: 'ru', resolvedLanguage: 'ru', changeLanguage: vi.fn() };
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: i18nMock }),
}));

import { DESIGN_STORAGE_KEY, ThemeProvider, useTheme } from '../src/contexts/ThemeContext';
import { Sidebar } from '../src/components/Sidebar';

function Probe() {
  const { design, colors, setDesign } = useTheme();
  return (
    <div>
      <span data-testid="design">{design}</span>
      <span data-testid="accent">{colors.accent}</span>
      <button type="button" onClick={() => setDesign('new')}>to-new</button>
    </div>
  );
}

const root = document.documentElement;

beforeEach(() => {
  localStorage.clear();
  delete root.dataset.design;
});

afterEach(() => {
  cleanup();
});

describe('design switch', () => {
  it('defaults existing users to the classic design and palette', () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId('design').textContent).toBe('classic');
    expect(screen.getByTestId('accent').textContent).toBe('#22d3ee');
    expect(root.dataset.design).toBe('classic');
    expect(root.style.getPropertyValue('--bg-primary')).toBe('#0a0e1a');
  });

  it('restores a saved choice and ignores garbage values', () => {
    localStorage.setItem(DESIGN_STORAGE_KEY, 'new');
    const { unmount } = render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId('design').textContent).toBe('new');
    expect(root.dataset.design).toBe('new');
    unmount();

    localStorage.setItem(DESIGN_STORAGE_KEY, 'neon');
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId('design').textContent).toBe('classic');
  });

  it('switches without reload, persists the choice and swaps the palette', () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    fireEvent.click(screen.getByText('to-new'));
    expect(localStorage.getItem(DESIGN_STORAGE_KEY)).toBe('new');
    expect(root.dataset.design).toBe('new');
    expect(root.style.getPropertyValue('--bg-primary')).toBe('#0b0b0c');
    expect(screen.getByTestId('accent').textContent).toBe('#e4e4e7');
  });

  it('places the switch under the language chips and leaves the language alone', () => {
    render(
      <ThemeProvider>
        <Sidebar
          activeTab="dashboard"
          setActiveTab={vi.fn()}
          items={[]}
          user="admin"
          onLogout={vi.fn()}
          onOpenLog={vi.fn()}
          mobileOpen={false}
          onMobileClose={vi.fn()}
        />
      </ThemeProvider>,
    );

    const languageLabel = screen.getByText('language.title');
    const designLabel = screen.getByText('design.title');
    expect(languageLabel.compareDocumentPosition(designLabel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const oldButton = screen.getByText('design.classic');
    const newButton = screen.getByText('design.new');
    expect(oldButton.getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(newButton);
    expect(newButton.getAttribute('aria-pressed')).toBe('true');
    expect(root.dataset.design).toBe('new');
    expect(i18nMock.changeLanguage).not.toHaveBeenCalled();
  });
});
