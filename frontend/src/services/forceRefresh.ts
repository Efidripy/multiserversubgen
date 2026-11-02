import api from '../api/client';
import { getAuth } from '../auth';

let nodeRefreshPromise: Promise<void> | null = null;

/** Poll every node once before a section rereads its projection. */
export function forceNodeRefresh(): Promise<void> {
  if (nodeRefreshPromise) return nodeRefreshPromise;
  nodeRefreshPromise = api.post('/v1/nodes/refresh-now', {}, {
    auth: getAuth(),
    params: { wait: true },
    timeout: 60_000,
  }).then(() => undefined).catch(() => undefined).finally(() => {
    nodeRefreshPromise = null;
  });
  return nodeRefreshPromise;
}

