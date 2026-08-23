import axios from 'axios';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import api, { resetInFlightGetRequests } from '../src/api/client';
import { getInboundOptions } from '../src/api/inbounds';
import { cacheService } from '../src/services/cacheService';

describe('inbound options read projection', () => {
  beforeEach(() => {
    cacheService.invalidate();
    resetInFlightGetRequests();
  });

  afterEach(() => {
    api.defaults.adapter = axios.defaults.adapter;
    cacheService.invalidate();
    resetInFlightGetRequests();
  });

  it('requests the compact options route and forwards cancellation', async () => {
    const controller = new AbortController();
    let request: any;
    api.defaults.adapter = async (config: any) => {
      request = config;
      return {
        data: {
          inbounds: [{
            id: 7,
            node_id: 3,
            node_name: 'node-a',
            protocol: 'vless',
            remark: 'Main',
            settings: '{"clients":[{"email":"must-not-leak"}]}',
            clientStats: [{ email: 'must-not-leak' }],
            password: 'must-not-leak',
          }],
          count: 1,
        },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      };
    };

    await expect(getInboundOptions({ signal: controller.signal })).resolves.toEqual([{
      id: 7,
      node_id: 3,
      node_name: 'node-a',
      protocol: 'vless',
      remark: 'Main',
    }]);
    expect(request.url).toBe('/v1/inbounds/options');
    expect(request.signal).toBe(controller.signal);
  });

  it('returns no full-DTO fallback when the options projection is malformed', async () => {
    api.defaults.adapter = async (config: any) => ({
      data: {
        inbounds: [
          { id: 'not-a-number', node_name: 'ignored' },
          null,
          { id: 8, node_name: 'node-b', protocol: 'shadowsocks', remark: null, settings: { clients: [] } },
        ],
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    });

    await expect(getInboundOptions()).resolves.toEqual([{
      id: 8,
      node_name: 'node-b',
      protocol: 'shadowsocks',
      remark: '',
    }]);
  });
});
