import api from '../api/client';
import { getAuth } from '../auth';

export const NODE_REFRESH_INCOMPLETE_EVENT = 'sub-manager:node-refresh-incomplete';

let nodeRefreshPromise: Promise<void> | null = null;

const notifyIncomplete = () => {
  window.dispatchEvent(new CustomEvent(NODE_REFRESH_INCOMPLETE_EVENT));
};

/** Poll every node once before a section rereads its projection. */
export function forceNodeRefresh(): Promise<void> {
  if (nodeRefreshPromise) return nodeRefreshPromise;
  nodeRefreshPromise = api.post('/v1/nodes/refresh-now', {}, {
    auth: getAuth(),
    params: { wait: true },
    timeout: 60_000,
  }).then((res) => {
    if (res?.data?.completed === false) notifyIncomplete();
  }).catch(notifyIncomplete).finally(() => {
    nodeRefreshPromise = null;
  });
  return nodeRefreshPromise;
}

