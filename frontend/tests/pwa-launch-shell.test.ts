import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const indexHtml = readFileSync(resolve(__dirname, '../index.html'), 'utf8');
const manifest = JSON.parse(readFileSync(resolve(__dirname, '../public/manifest.webmanifest'), 'utf8')) as Record<string, unknown>;
const appCss = readFileSync(resolve(__dirname, '../src/App.css'), 'utf8');
const appSource = readFileSync(resolve(__dirname, '../src/App.tsx'), 'utf8');
const appleTouchIcon = readFileSync(resolve(__dirname, '../public/apple-touch-icon.png'));

describe('iOS standalone launch shell', () => {
  it('sets the same dark palette before the Vite bundle can paint', () => {
    expect(indexHtml).toContain('<meta name="theme-color" content="#0a0e1a" />');
    expect(indexHtml).toContain('<link rel="manifest" href="%BASE_URL%manifest.webmanifest" />');
    expect(indexHtml).toContain('color-scheme: dark;');
    expect(indexHtml).toContain('html,\n      body,\n      #root');
    expect(indexHtml).toContain('background: #0a0e1a;');
    expect(indexHtml).toContain('body:has(.app-bootstrap)');
    expect(indexHtml).toContain('overflow: hidden;');
  });

  it('renders a truthful, non-scrollable bootstrap until React takes ownership', () => {
    expect(indexHtml).toContain('<div id="root"><div class="app-bootstrap" role="status" aria-label="Загрузка интерфейса">');
    expect(indexHtml).toContain('min-height: 100dvh;');
    expect(indexHtml).toContain('app-bootstrap__spinner');
    expect(indexHtml).toContain('prefers-reduced-motion: reduce');
    expect(indexHtml).toContain('<script type="module" src="/src/main.tsx"></script>');
  });

  it('declares standalone Apple metadata without changing app routes or API behavior', () => {
    expect(indexHtml).toContain('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />');
    expect(indexHtml).toContain('<meta name="apple-mobile-web-app-capable" content="yes" />');
    expect(indexHtml).toContain('<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />');
    expect(indexHtml).toContain('<meta name="apple-mobile-web-app-title" content="&#8203;" />');
    expect(indexHtml).toContain('<link rel="apple-touch-icon" sizes="512x512" href="%BASE_URL%apple-touch-icon.png" />');
    expect(indexHtml).not.toContain('/api/');
    expect(manifest).toMatchObject({
      display: 'standalone',
      start_url: './',
      scope: './',
      background_color: '#0a0e1a',
      theme_color: '#0a0e1a',
    });
    expect(manifest).toMatchObject({
      short_name: '\u200B',
      icons: [{
        src: 'apple-touch-icon.png',
        sizes: '512x512',
        type: 'image/png',
      }],
    });
    expect(appleTouchIcon.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  });

  it('keeps the standalone layout within the visual viewport without disabling zoom', () => {
    expect(indexHtml).toContain('width=device-width, initial-scale=1, viewport-fit=cover');
    expect(indexHtml).not.toMatch(/(?:maximum-scale|user-scalable)/i);
    expect(appCss).toMatch(/@media \(max-width: 1024px\)[\s\S]*?\.app-layout,[\s\S]*?\.app-shell\s*\{[\s\S]*?padding-top: env\(safe-area-inset-top, 0px\);/);
    expect(appCss).toMatch(/\.app-main\s*\{[\s\S]*?min-height: calc\(100dvh - env\(safe-area-inset-top, 0px\)\);/);
    expect(appCss).toMatch(/\.sidebar,[\s\S]*?\.app-sidebar\s*\{[\s\S]*?top: env\(safe-area-inset-top, 0px\);[\s\S]*?height: calc\(100dvh - env\(safe-area-inset-top, 0px\)\);/);
    expect(appCss).toMatch(/\.app-topbar\s*\{[\s\S]*?height: 56px;[\s\S]*?padding: 0 12px;/);
    expect(appCss).toMatch(/\.app-topbar__title-content\s*\{[\s\S]*?min-width: 0;[\s\S]*?overflow: hidden;/);
    expect(appCss).toMatch(/\.app-topbar__activity-dot\s*\{[\s\S]*?flex: 0 0 auto;/);
    expect(appCss).toContain('text-overflow: ellipsis;');
    expect(appCss).toContain('right: env(safe-area-inset-right, 0px);');
    expect(appCss).toContain('width: min(420px, calc(100vw - 1rem - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px)));');
    expect(appSource).toMatch(/id="login-username"[\s\S]*?text-base/);
    expect(appSource).toMatch(/id="login-password"[\s\S]*?text-base/);
    expect(appSource).toContain("enabled: activeTab !== 'dashboard' || dashboardRefreshReady");
    expect(appSource).toMatch(/if \(activeTab === 'dashboard'\)[\s\S]*?window\.location\.reload\(\);/);
  });
});
