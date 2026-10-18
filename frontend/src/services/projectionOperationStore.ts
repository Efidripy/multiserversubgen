import { useSyncExternalStore } from 'react';

export type ProjectionOperationResource = 'clients' | 'inbounds';
export type ProjectionOperationStatus =
  | 'sending'
  | 'remote_succeeded_awaiting_projection'
  | 'visible_in_projection'
  | 'partial'
  | 'failed'
  | 'outcome_unknown';

export type ProjectionOperationKind = 'add' | 'delete' | 'update' | 'batch';

/**
 * Presentation metadata only. A target is deliberately keyed by the local
 * projection identity, never by an optimistic client row. Its status explains
 * an in-flight operation; it does not claim a remote XUI state.
 */
export interface ProjectionOperationTarget {
  key: string;
  email?: string;
  nodeId?: number;
  nodeName?: string;
  inboundId?: number;
  status: ProjectionOperationStatus;
}

export interface BeginProjectionOperationOptions {
  kind?: ProjectionOperationKind;
  targets?: Array<Omit<ProjectionOperationTarget, 'status'>>;
}

export const clientProjectionTargetKey = (
  nodeId: number | null | undefined,
  inboundId: number | null | undefined,
  email: string,
): string => `client:${nodeId ?? 'unknown'}:${inboundId ?? 'unknown'}:${email.trim().toLowerCase()}`;

export interface ProjectionOperation {
  id: number;
  resource: ProjectionOperationResource;
  label: string;
  status: ProjectionOperationStatus;
  createdAt: number;
  kind?: ProjectionOperationKind;
  targets: ProjectionOperationTarget[];
}

let nextId = 1;
let operations: ProjectionOperation[] = [];
const listeners = new Set<() => void>();
const EMPTY_OPERATIONS: ProjectionOperation[] = [];
const snapshots: Record<ProjectionOperationResource, ProjectionOperation[]> = {
  clients: EMPTY_OPERATIONS,
  inbounds: EMPTY_OPERATIONS,
};

const notify = () => {
  snapshots.clients = operations.filter((operation) => operation.resource === 'clients');
  snapshots.inbounds = operations.filter((operation) => operation.resource === 'inbounds');
  listeners.forEach((listener) => listener());
};

export function beginProjectionOperation(
  resource: ProjectionOperationResource,
  label: string,
  options: BeginProjectionOperationOptions = {},
): number {
  const id = nextId++;
  operations = [...operations, {
    id,
    resource,
    label,
    status: 'sending',
    createdAt: Date.now(),
    kind: options.kind,
    targets: (options.targets || []).map((target) => ({ ...target, status: 'sending' })),
  }];
  notify();
  return id;
}

export function setProjectionOperationStatus(id: number, status: ProjectionOperationStatus): void {
  operations = operations.map((operation) => operation.id === id ? { ...operation, status } : operation);
  notify();
}

export function setProjectionOperationTargetStatus(
  id: number,
  targetKey: string,
  status: ProjectionOperationStatus,
): void {
  operations = operations.map((operation) => operation.id === id
    ? {
      ...operation,
      targets: operation.targets.map((target) => target.key === targetKey ? { ...target, status } : target),
    }
    : operation);
  notify();
}

export function clearProjectionOperation(id: number): void {
  operations = operations.filter((operation) => operation.id !== id);
  notify();
}

export function useProjectionOperations(resource: ProjectionOperationResource): ProjectionOperation[] {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => snapshots[resource],
    () => EMPTY_OPERATIONS,
  );
}
