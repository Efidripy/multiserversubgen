import type { NodeRecord } from '../api/nodes';

export interface NodeConnectionFormData {
  name: string;
  url: string;
  port: string;
  user: string;
  password: string;
  bearer_token: string;
}

export type NodeEditPayload = {
  name: string;
  url: string;
  user?: string;
  password?: string;
  bearer_token?: string;
};

export type NodeEditPayloadResult =
  | { payload: NodeEditPayload }
  | { error: 'name' | 'url' | 'credentials' };

export const emptyNodeConnectionForm = (): NodeConnectionFormData => ({
  name: '',
  url: '',
  port: '',
  user: '',
  password: '',
  bearer_token: '',
});

export const buildPanelUrl = (rawUrl: string, rawPort: string): string | null => {
  const trimmedUrl = rawUrl.trim();
  if (!trimmedUrl) return null;
  const withScheme = /^https?:\/\//i.test(trimmedUrl) ? trimmedUrl : `https://${trimmedUrl}`;

  try {
    const url = new URL(withScheme);
    const trimmedPort = rawPort.trim();
    if (trimmedPort) url.port = trimmedPort;
    url.search = '';
    url.hash = '';
    const path = url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '');
    return `${url.protocol}//${url.host}${path}`;
  } catch {
    return null;
  }
};

const getNodePanelUrl = (node: NodeRecord): string => {
  if (node.url) return node.url;
  if (node.panel_url) return node.panel_url;
  const scheme = node.scheme || 'https';
  const host = node.ip || node.name;
  const port = node.port ? `:${node.port}` : '';
  const basePath = (node.base_path || '').replace(/^\/|\/$/g, '');
  return `${scheme}://${host}${port}${basePath ? `/${basePath}` : ''}`;
};

export const nodeToEditForm = (node: NodeRecord): NodeConnectionFormData => {
  const fallbackUrl = getNodePanelUrl(node);
  const storedUser = node.user === 'bearer_token' ? '' : node.user || '';

  try {
    const parsed = new URL(fallbackUrl);
    const port = node.port || parsed.port;
    parsed.port = '';
    const path = parsed.pathname === '/' ? '' : parsed.pathname.replace(/\/$/, '');
    return {
      name: node.name,
      url: `${parsed.protocol}//${parsed.host}${path}`,
      port,
      user: storedUser,
      password: '',
      bearer_token: '',
    };
  } catch {
    return {
      name: node.name,
      url: fallbackUrl,
      port: node.port || '',
      user: storedUser,
      password: '',
      bearer_token: '',
    };
  }
};

export const buildNodeEditPayload = (
  node: NodeRecord,
  form: NodeConnectionFormData,
): NodeEditPayloadResult => {
  const name = form.name.trim();
  if (!name) return { error: 'name' };

  const url = buildPanelUrl(form.url, form.port);
  if (!url) return { error: 'url' };

  const bearerToken = form.bearer_token.trim();
  if (bearerToken) return { payload: { name, url, bearer_token: bearerToken } };

  const user = form.user.trim();
  const storedUser = node.user === 'bearer_token' ? '' : node.user || '';
  const userChanged = user !== storedUser;
  const hasNewPassword = form.password.length > 0;
  const usesBearerAuthentication = node.user === 'bearer_token';
  const replacingBearerAuthentication = usesBearerAuthentication && (userChanged || hasNewPassword);

  if ((replacingBearerAuthentication && (!user || !hasNewPassword)) || (!usesBearerAuthentication && userChanged && !user)) {
    return { error: 'credentials' };
  }

  const payload: NodeEditPayload = { name, url };
  if (userChanged || hasNewPassword) {
    payload.user = user;
    if (hasNewPassword) payload.password = form.password;
  }
  return { payload };
};
