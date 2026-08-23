import api from './client';
import { getAuth } from '../auth';

/**
 * Small read projection for controls that only need to select an inbound.
 *
 * This must stay separate from the full Inbound DTO used by InboundManager's
 * edit and clone flows.  In particular, do not add settings, client lists, or
 * transport configuration here.
 */
export interface InboundOption {
  id: number;
  node_id?: number;
  node_name: string;
  protocol: string;
  remark: string;
}

const asFiniteNumber = (value: unknown): number | undefined => {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : undefined;
};

const asText = (value: unknown): string => typeof value === 'string' ? value : '';

const normalizeInboundOption = (value: unknown): InboundOption | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const id = asFiniteNumber(raw.id);
  if (id === undefined) return null;

  const nodeId = asFiniteNumber(raw.node_id);
  return {
    id,
    ...(nodeId === undefined ? {} : { node_id: nodeId }),
    node_name: asText(raw.node_name),
    protocol: asText(raw.protocol),
    remark: asText(raw.remark),
  };
};

export async function getInboundOptions(options: { signal?: AbortSignal } = {}): Promise<InboundOption[]> {
  const res = await api.get('/v1/inbounds/options', { auth: getAuth(), signal: options.signal });
  const items = Array.isArray(res.data?.inbounds) ? res.data.inbounds : [];
  return items.flatMap((item: unknown) => {
    const normalized = normalizeInboundOption(item);
    return normalized ? [normalized] : [];
  });
}
