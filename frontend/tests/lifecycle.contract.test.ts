import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const repo = resolve(process.cwd(), '..');
const read = (relative: string) => readFileSync(resolve(repo, relative), 'utf8');

describe('lifecycle remediation contracts', () => {
  it('mounts only the active tab and lazy-loads large managers', () => {
    const app = read('frontend/src/App.tsx');
    expect(app).not.toContain('mountedTabs');
    expect(app).toContain('React.lazy');
    expect(app).toContain('<React.Suspense');
  });

  it('keeps Service Worker registration and caches scope-isolated', () => {
    const manager = read('frontend/src/services/serviceWorkerManager.ts');
    const worker = read('frontend/public/sw.js');
    expect(manager).toContain('registration.scope === expectedScope');
    expect(manager).toContain('scriptUrl === expectedWorker');
    expect(worker).toContain('CACHE_PREFIX');
    expect(worker).toContain('cacheName.startsWith(CACHE_PREFIX)');
    expect(worker).toContain('cache.match(request)');
  });

  it('keeps login errors and transient notifications announced to assistive tech', () => {
    const app = read('frontend/src/App.tsx');
    const toast = read('frontend/src/components/Toast.tsx');
    const activity = read('frontend/src/components/ActivityLogPanel.tsx');
    expect(app).toContain('role="alert"');
    expect(app).toContain('htmlFor="login-username"');
    expect(toast).toContain('aria-live=');
    expect(activity).toContain('aria-modal="true"');
    expect(activity).toContain("event.key === 'Escape'");
  });
});
