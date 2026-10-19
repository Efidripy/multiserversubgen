import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const indexHtml = readFileSync(resolve(__dirname, '../index.html'), 'utf8');
const manifest = JSON.parse(readFileSync(resolve(__dirname, '../public/manifest.webmanifest'), 'utf8')) as Record<string, unknown>;

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
    expect(indexHtml).not.toContain('/api/');
    expect(manifest).toMatchObject({
      display: 'standalone',
      start_url: './',
      scope: './',
      background_color: '#0a0e1a',
      theme_color: '#0a0e1a',
    });
  });
});
