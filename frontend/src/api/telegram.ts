import api from './client';
import { getAuth } from '../auth';

export type TelegramRequest = {
  telegram_user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  row_version: number;
  requested_at: string | null;
  introduction_text: string | null;
  suggested_email: string;
};

export type TelegramCustomer = {
  customer_id: number;
  email_display: string;
  origin: string;
  status: string;
  row_version: number;
  telegram_user_id: number | null;
  created_at: string;
  updated_at: string;
};

export type CustomerNode = {
  node_id: number;
  node_name: string;
  state: string;
  binding_id: number | null;
  desired_enabled: boolean | null;
  management_state: string | null;
};

export type CustomerOperationAttempt = {
  binding_id: number;
  node_id: number;
  node_name: string;
  action: string;
  status: string;
  error_code: string | null;
  error_summary: string | null;
  attempt_count: number;
};

export type CustomerOperation = {
  operation_id: number;
  customer_id: number;
  customer_email: string;
  operation_type: string;
  status: string;
  row_version: number;
  target_snapshot_digest: string;
  created_at: string;
  finished_at: string | null;
  attempts: CustomerOperationAttempt[];
};

export type CustomerOperationPreview = {
  customer_id: number;
  operation_type: 'suspend' | 'resume' | 'delete' | 'suspend_node' | 'resume_node';
  expected_customer_version: number;
  target_snapshot_digest: string;
  targets: Array<{ binding_id: number; node_id: number; node_name: string; action: string; previous_enabled: boolean | null }>;
  blocked_binding_ids: number[];
};

export const newIdempotencyKey = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `tg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

export async function listTelegramRequests(): Promise<TelegramRequest[]> {
  const response = await api.get('/v1/telegram/requests', { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function approveTelegramRequest(request: TelegramRequest, emailDisplay: string): Promise<void> {
  await api.post(
    `/v1/telegram/requests/${request.telegram_user_id}/approve-new`,
    { expected_identity_version: request.row_version, email_display: emailDisplay, idempotency_key: newIdempotencyKey() },
    { auth: getAuth() },
  );
}

export async function listTelegramCustomers(query = ''): Promise<TelegramCustomer[]> {
  const response = await api.get('/v1/telegram/customers', { auth: getAuth(), params: { query, page_size: 100 } });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function getCustomerNodes(customerId: number): Promise<CustomerNode[]> {
  const response = await api.get(`/v1/telegram/customers/${customerId}/nodes`, { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function getCustomerOperations(customerId: number): Promise<CustomerOperation[]> {
  const response = await api.get(`/v1/telegram/customers/${customerId}/operations`, { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function previewCustomerOperation(customerId: number, operationType: CustomerOperationPreview['operation_type']): Promise<CustomerOperationPreview> {
  const response = await api.post(
    `/v1/telegram/customers/${customerId}/lifecycle/preview`,
    { operation_type: operationType },
    { auth: getAuth() },
  );
  return response.data?.preview as CustomerOperationPreview;
}

export async function queueCustomerOperation(preview: CustomerOperationPreview): Promise<void> {
  await api.post(
    `/v1/telegram/customers/${preview.customer_id}/lifecycle`,
    {
      operation_type: preview.operation_type,
      expected_customer_version: preview.expected_customer_version,
      target_snapshot_digest: preview.target_snapshot_digest,
      idempotency_key: newIdempotencyKey(),
    },
    { auth: getAuth() },
  );
}

export async function addCustomerNode(customer: TelegramCustomer, nodeId: number): Promise<void> {
  await api.post(
    `/v1/telegram/customers/${customer.customer_id}/nodes/${nodeId}/add`,
    { expected_customer_version: customer.row_version, idempotency_key: newIdempotencyKey() },
    { auth: getAuth() },
  );
}

export async function previewCustomerNodeOperation(
  customerId: number,
  nodeId: number,
  operationType: 'suspend_node' | 'resume_node',
): Promise<CustomerOperationPreview> {
  const response = await api.post(
    `/v1/telegram/customers/${customerId}/nodes/${nodeId}/operation/preview`,
    { operation_type: operationType },
    { auth: getAuth() },
  );
  return response.data?.preview as CustomerOperationPreview;
}

export async function queueCustomerNodeOperation(preview: CustomerOperationPreview, nodeId: number): Promise<void> {
  await api.post(
    `/v1/telegram/customers/${preview.customer_id}/nodes/${nodeId}/operation`,
    {
      operation_type: preview.operation_type,
      expected_customer_version: preview.expected_customer_version,
      target_snapshot_digest: preview.target_snapshot_digest,
      idempotency_key: newIdempotencyKey(),
    },
    { auth: getAuth() },
  );
}

export async function retryCustomerOperation(operation: CustomerOperation): Promise<void> {
  await api.post(
    `/v1/telegram/customer-operations/${operation.operation_id}/reconcile`,
    { expected_operation_version: operation.row_version, idempotency_key: newIdempotencyKey() },
    { auth: getAuth() },
  );
}
