import axios, { AxiosError } from 'axios';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import api, { AUTH_REQUIRED_EVENT, resetAuthRequiredEventGuard } from '../src/api/client';
import { createBrowserSession, verifyCurrentAuth } from '../src/api/authService';
import { setAuthCredentials, clearAuthCredentials } from '../src/auth';
import { getDashboardOverview } from '../src/api/dashboard';

const unauthorizedAdapter = async (config: any) => {
  throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, undefined, {
    data: { detail: 'Unauthorized' },
    status: 401,
    statusText: 'Unauthorized',
    headers: {},
    config,
  } as any);
};

describe('API authentication lifecycle', () => {
  beforeEach(() => {
    resetAuthRequiredEventGuard();
    api.defaults.adapter = unauthorizedAdapter;
  });

  afterEach(() => {
    api.defaults.adapter = axios.defaults.adapter;
  });

  it('dispatches one auth-required event for repeated API 401 responses', async () => {
    const events: Event[] = [];
    const listener = (event: Event) => events.push(event);
    window.addEventListener(AUTH_REQUIRED_EVENT, listener);

    await expect(api.get('/v1/nodes?auth-test=1')).rejects.toMatchObject({ response: { status: 401 } });
    await expect(api.get('/v1/nodes?auth-test=2')).rejects.toMatchObject({ response: { status: 401 } });

    window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
    expect(events).toHaveLength(1);
  });

  it('does not dispatch auth-required for intentional auth verification failure', async () => {
    const events: Event[] = [];
    const listener = (event: Event) => events.push(event);
    window.addEventListener(AUTH_REQUIRED_EVENT, listener);

    await expect(api.post('/auth/verify')).rejects.toMatchObject({ response: { status: 401 } });

    window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
    expect(events).toHaveLength(0);
  });

  it('uses the HttpOnly browser session for Dashboard polling without an empty Basic header', async () => {
    let captured: any;
    setAuthCredentials('admin', 'legacy-basic-must-not-be-replayed', '', 'ticket', 'admin');
    api.defaults.adapter = async (config: any) => {
      captured = config;
      return {
        data: { summary: {}, fleet: [] },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await expect(getDashboardOverview()).resolves.toMatchObject({ projection: 'dashboard-v1' });
    expect(captured.auth).toBeUndefined();
    expect(captured.headers?.get?.('Authorization')).toBeUndefined();
    expect(captured.withCredentials).toBe(true);
    clearAuthCredentials();
  });
  it('uses the HttpOnly browser session on refresh instead of sending empty Basic credentials', async () => {
    let captured: any;
    api.defaults.adapter = async (config: any) => {
      captured = config;
      return {
        data: { user: 'admin', role: 'admin', ws_ticket: 'ticket' },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await expect(verifyCurrentAuth()).resolves.toMatchObject({ user: 'admin' });
    expect(captured.auth).toBeUndefined();
    expect(captured.withCredentials).toBe(true);
  });

  it('keeps explicit Basic authentication for browser-session bootstrap', async () => {
    let captured: any;
    api.defaults.adapter = async (config: any) => {
      captured = config;
      return {
        data: { user: 'admin', role: 'admin', ws_ticket: 'ticket' },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await expect(createBrowserSession('admin', 'bootstrap-basic-password')).resolves.toMatchObject({ user: 'admin' });
    expect(captured.auth).toEqual({ username: 'admin', password: 'bootstrap-basic-password' });
    expect(captured.withCredentials).toBe(true);
  });
});
