import { describe, expect, it } from 'vitest';
import type { NodeRecord } from '../src/api/nodes';
import { buildNodeEditPayload, nodeToEditForm } from '../src/components/nodeEditForm';

const node = (overrides: Partial<NodeRecord> = {}): NodeRecord => ({
  id: 7,
  name: 'edge-7',
  panel_url: 'https://edge.example.test:8443/panel',
  url: 'https://edge.example.test:8443/panel',
  source_type: 'xui',
  verify_tls: true,
  enabled: true,
  read_only: false,
  api_version: 'v3',
  ip: 'edge.example.test',
  port: '8443',
  base_path: 'panel',
  scheme: 'https',
  user: 'root',
  ...overrides,
});

describe('node connection edit form', () => {
  it('pre-fills public connection data but never pre-fills a password or bearer token', () => {
    const form = nodeToEditForm(node());

    expect(form).toMatchObject({
      name: 'edge-7',
      url: 'https://edge.example.test/panel',
      port: '8443',
      user: 'root',
      password: '',
      bearer_token: '',
    });
  });

  it('sends a replacement password only when the operator entered one', () => {
    const form = nodeToEditForm(node());
    expect(buildNodeEditPayload(node(), form)).toEqual({
      payload: { name: 'edge-7', url: 'https://edge.example.test:8443/panel' },
    });

    form.password = 'rotated-password';
    expect(buildNodeEditPayload(node(), form)).toEqual({
      payload: {
        name: 'edge-7',
        url: 'https://edge.example.test:8443/panel',
        user: 'root',
        password: 'rotated-password',
      },
    });
  });

  it('keeps an existing bearer token when no replacement is entered and requires a complete credential switch', () => {
    const bearerNode = node({ user: 'bearer_token' });
    const form = nodeToEditForm(bearerNode);

    expect(buildNodeEditPayload(bearerNode, form)).toEqual({
      payload: { name: 'edge-7', url: 'https://edge.example.test:8443/panel' },
    });

    form.user = 'root';
    expect(buildNodeEditPayload(bearerNode, form)).toEqual({ error: 'credentials' });

    form.password = 'new-password';
    expect(buildNodeEditPayload(bearerNode, form)).toEqual({
      payload: {
        name: 'edge-7',
        url: 'https://edge.example.test:8443/panel',
        user: 'root',
        password: 'new-password',
      },
    });
  });
});
