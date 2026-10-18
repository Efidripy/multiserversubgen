import { useSyncExternalStore } from 'react';

export type ProjectionOperationResource = 'clients' | 'inbounds';
export type ProjectionOperationStatus =
  | 'sending'
  | 'remote_succeeded_awaiting_projection'
  | 'visible_in_projection'
  | 'partial'
  | 'failed'
  | 'outcome_unknown';

export interface ProjectionOperation {
  id: number;
  resource: ProjectionOperationResource;
  label: string;
  status: ProjectionOperationStatus;
  createdAt: number;
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
): number {
  const id = nextId++;
  operations = [...operations, { id, resource, label, status: 'sending', createdAt: Date.now() }];
  notify();
  return id;
}

export function setProjectionOperationStatus(id: number, status: ProjectionOperationStatus): void {
  operations = operations.map((operation) => operation.id === id ? { ...operation, status } : operation);
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
