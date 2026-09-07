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

export type ExistingDiscoveryCandidate = {
  email_display: string;
  binding_count: number;
  node_names: string[];
};

export type TelegramAppeal = {
  appeal_id: number;
  telegram_user_id: number;
  customer_id: number;
  email_display: string;
  body: string;
  status: 'open' | 'handled' | 'rejected';
  row_version: number;
  created_at: string;
  updated_at: string;
};

export type TelegramSupportRequest = {
  support_request_id: number;
  telegram_user_id: number;
  customer_id: number;
  email_display: string;
  category: 'link' | 'connection' | 'device' | 'directions' | 'other';
  body: string;
  status: 'open' | 'read' | 'resolved';
  row_version: number;
  created_at: string;
  updated_at: string;
  admin_response: string | null;
};

export type ProvisioningJob = {
  job_id: number;
  customer_id: number;
  customer_email: string;
  trigger: string;
  status: string;
  row_version: number;
  attempt_count: number;
  created_at: string;
  finished_at: string | null;
  attempts: Array<{ node_id: number; node_name: string; status: string; error_code: string | null; error_summary: string | null; attempt_count: number; next_attempt_at: string | null }>;
};

export type BlockedIdentity = { telegram_user_id: number; username: string | null; first_name: string | null; row_version: number; blocked_at: string | null; decision_reason: string | null; };

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

export type CustomerTraffic = {
  customer_id: number;
  lifetime_bytes: number;
  last_observed_bytes: number;
  last_observed_at: string;
};

export type TelegramTransportStatus = {
  mode: 'direct' | 'local_proxy';
  row_version: number;
  configured: boolean;
  reachable: boolean;
  updated_by: string;
  updated_at: string;
};

export type TelegramBotConfigurationStatus = {
  configured: boolean;
  token_suffix: string | null;
  row_version: number;
  updated_by: string;
  updated_at: string;
  source: 'panel' | 'environment' | 'none';
};

export type TelegramAdminDashboard = {
  pending_requests: number; active_customers: number; suspended_customers: number;
  lifecycle_attention: number; provisioning_attention: number; open_appeals: number;
  open_support_requests: number; open_drift_findings: number; scheduled_lifecycle_actions: number;
};

export type CustomerTimelineEvent = { event_type: string; entity_type: string; entity_id: string; created_at: string; actor_type: string | null; actor_id: string | null; status: string | null; };
export type CustomerTag = { customer_id: number; tag: string; };
export type LifecycleSchedule = { schedule_id: number; customer_id: number; customer_email: string; operation_type: 'suspend' | 'delete'; expected_customer_version: number; target_snapshot_digest: string; execute_not_before: string; status: string; row_version: number; operation_id: number | null; created_at: string; };
export type DriftFinding = { finding_id: number; kind: 'binding_missing' | 'binding_conflict' | 'orphan_remote'; customer_id: number | null; customer_email: string | null; node_id: number; node_name: string; remote_email: string; remote_client_id: string; remote_sub_id: string; status: string; row_version: number; last_seen_at: string; };
export type BulkLifecyclePreview = {
  operation_type: 'suspend' | 'resume' | 'delete'; target_snapshot_digest: string;
  items: Array<{ customer_id: number; customer_email: string; expected_customer_version: number; target_snapshot_digest: string; target_count: number; blocked_binding_ids: number[] }>;
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

export async function listBlockedTelegramIdentities(): Promise<BlockedIdentity[]> {
  const response = await api.get('/v1/telegram/identities/blocked', { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function getTelegramTransport(): Promise<TelegramTransportStatus> {
  const response = await api.get('/v1/telegram/transport', { auth: getAuth() });
  return response.data?.transport as TelegramTransportStatus;
}

export async function getTelegramBotConfiguration(): Promise<TelegramBotConfigurationStatus> {
  const response = await api.get('/v1/telegram/bot-configuration', { auth: getAuth() });
  return response.data?.configuration as TelegramBotConfigurationStatus;
}

export async function setTelegramBotConfiguration(configuration: TelegramBotConfigurationStatus, botToken: string): Promise<TelegramBotConfigurationStatus> {
  const response = await api.put('/v1/telegram/bot-configuration', {
    bot_token: botToken, expected_row_version: configuration.row_version,
  }, { auth: getAuth() });
  return response.data?.configuration as TelegramBotConfigurationStatus;
}

export async function clearTelegramBotConfiguration(configuration: TelegramBotConfigurationStatus): Promise<TelegramBotConfigurationStatus> {
  const response = await api.delete('/v1/telegram/bot-configuration', {
    auth: getAuth(), params: { expected_row_version: configuration.row_version },
  });
  return response.data?.configuration as TelegramBotConfigurationStatus;
}

export async function setTelegramTransport(
  transport: TelegramTransportStatus,
  mode: TelegramTransportStatus['mode'],
): Promise<TelegramTransportStatus> {
  const response = await api.put(
    '/v1/telegram/transport',
    { mode, expected_row_version: transport.row_version },
    { auth: getAuth() },
  );
  return response.data?.transport as TelegramTransportStatus;
}

export async function approveTelegramRequest(request: TelegramRequest, emailDisplay: string): Promise<void> {
  await api.post(
    `/v1/telegram/requests/${request.telegram_user_id}/approve-new`,
    { expected_identity_version: request.row_version, email_display: emailDisplay, idempotency_key: newIdempotencyKey() },
    { auth: getAuth() },
  );
}

export async function discoverExistingTelegramCustomer(request: TelegramRequest, emailDisplay: string): Promise<ExistingDiscoveryCandidate> {
  const response = await api.post(
    `/v1/telegram/requests/${request.telegram_user_id}/discover-existing`,
    { expected_identity_version: request.row_version, email_display: emailDisplay },
    { auth: getAuth() },
  );
  return response.data?.candidate as ExistingDiscoveryCandidate;
}

export async function adoptExistingTelegramCustomer(request: TelegramRequest, emailDisplay: string): Promise<void> {
  await api.post(
    `/v1/telegram/requests/${request.telegram_user_id}/adopt-existing`,
    { expected_identity_version: request.row_version, email_display: emailDisplay, idempotency_key: newIdempotencyKey() },
    { auth: getAuth() },
  );
}

export async function rejectTelegramRequest(request: TelegramRequest): Promise<void> {
  await api.post(`/v1/telegram/requests/${request.telegram_user_id}/reject`, {
    expected_identity_version: request.row_version, idempotency_key: newIdempotencyKey(),
  }, { auth: getAuth() });
}

export async function blockTelegramRequest(request: TelegramRequest): Promise<void> {
  await api.post(`/v1/telegram/identities/${request.telegram_user_id}/block`, {
    expected_identity_version: request.row_version, idempotency_key: newIdempotencyKey(),
  }, { auth: getAuth() });
}

export async function unblockTelegramIdentity(identity: BlockedIdentity): Promise<void> {
  await api.post(`/v1/telegram/identities/${identity.telegram_user_id}/unblock`, {
    expected_identity_version: identity.row_version, idempotency_key: newIdempotencyKey(),
  }, { auth: getAuth() });
}

export async function listTelegramCustomers(query = ''): Promise<TelegramCustomer[]> {
  const response = await api.get('/v1/telegram/customers', { auth: getAuth(), params: { query, page_size: 100 } });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function getCustomerNodes(customerId: number): Promise<CustomerNode[]> {
  const response = await api.get(`/v1/telegram/customers/${customerId}/nodes`, { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function getCustomerTraffic(customerId: number): Promise<CustomerTraffic> {
  const response = await api.get(`/v1/telegram/customers/${customerId}/traffic`, { auth: getAuth() });
  return response.data?.traffic as CustomerTraffic;
}

export async function getCustomerOperations(customerId: number): Promise<CustomerOperation[]> {
  const response = await api.get(`/v1/telegram/customers/${customerId}/operations`, { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function getTelegramDashboard(): Promise<TelegramAdminDashboard> {
  const response = await api.get('/v1/telegram/dashboard', { auth: getAuth() });
  return response.data?.dashboard as TelegramAdminDashboard;
}

export async function getCustomerTags(customerId: number): Promise<CustomerTag[]> {
  const response = await api.get(`/v1/telegram/customers/${customerId}/tags`, { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function setCustomerTags(customerId: number, tags: string[]): Promise<CustomerTag[]> {
  const response = await api.put(`/v1/telegram/customers/${customerId}/tags`, { tags }, { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function getCustomerTimeline(customerId: number): Promise<CustomerTimelineEvent[]> {
  const response = await api.get(`/v1/telegram/customers/${customerId}/timeline`, { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function listLifecycleSchedules(customerId?: number): Promise<LifecycleSchedule[]> {
  const response = await api.get('/v1/telegram/lifecycle-schedules', { auth: getAuth(), params: customerId ? { customer_id: customerId } : undefined });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function scheduleCustomerOperation(preview: CustomerOperationPreview, executeNotBefore: string): Promise<LifecycleSchedule> {
  const response = await api.post(`/v1/telegram/customers/${preview.customer_id}/lifecycle/schedule`, {
    operation_type: preview.operation_type,
    execute_not_before: executeNotBefore,
    expected_customer_version: preview.expected_customer_version,
    target_snapshot_digest: preview.target_snapshot_digest,
    idempotency_key: newIdempotencyKey(),
  }, { auth: getAuth() });
  return response.data?.schedule as LifecycleSchedule;
}

export async function cancelLifecycleSchedule(schedule: LifecycleSchedule): Promise<LifecycleSchedule> {
  const response = await api.post(`/v1/telegram/lifecycle-schedules/${schedule.schedule_id}/cancel`, {
    expected_row_version: schedule.row_version,
    reason: 'cancelled_from_panel',
  }, { auth: getAuth() });
  return response.data?.schedule as LifecycleSchedule;
}

export async function previewBulkCustomerOperations(customerIds: number[], operationType: BulkLifecyclePreview['operation_type']): Promise<BulkLifecyclePreview> {
  const response = await api.post('/v1/telegram/bulk-lifecycle/preview', {
    customer_ids: customerIds, operation_type: operationType,
  }, { auth: getAuth() });
  return response.data?.preview as BulkLifecyclePreview;
}

export async function queueBulkCustomerOperations(preview: BulkLifecyclePreview): Promise<void> {
  await api.post('/v1/telegram/bulk-lifecycle', {
    operation_type: preview.operation_type,
    target_snapshot_digest: preview.target_snapshot_digest,
    items: preview.items.map((item) => ({
      customer_id: item.customer_id,
      expected_customer_version: item.expected_customer_version,
      target_snapshot_digest: item.target_snapshot_digest,
    })),
    idempotency_key: newIdempotencyKey(),
  }, { auth: getAuth() });
}

export async function listDriftFindings(): Promise<DriftFinding[]> {
  const response = await api.get('/v1/telegram/drift', { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function scanDrift(): Promise<void> {
  await api.post('/v1/telegram/drift/scan', {}, { auth: getAuth() });
}

export async function resolveDriftFinding(finding: DriftFinding): Promise<DriftFinding> {
  const response = await api.post(`/v1/telegram/drift/${finding.finding_id}/resolve`, {
    expected_row_version: finding.row_version, status: 'resolved',
  }, { auth: getAuth() });
  return response.data?.item as DriftFinding;
}

export async function adoptDriftFinding(finding: DriftFinding): Promise<DriftFinding> {
  const response = await api.post(`/v1/telegram/drift/${finding.finding_id}/adopt`, {
    expected_row_version: finding.row_version,
  }, { auth: getAuth() });
  return response.data?.item as DriftFinding;
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

export async function listTelegramJobs(): Promise<ProvisioningJob[]> {
  const response = await api.get('/v1/telegram/jobs', { auth: getAuth() });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function reconcileTelegramJob(job: ProvisioningJob): Promise<void> {
  await api.post(
    `/v1/telegram/jobs/${job.job_id}/reconcile`,
    { expected_job_version: job.row_version, idempotency_key: newIdempotencyKey() },
    { auth: getAuth() },
  );
}

export async function listTelegramAppeals(): Promise<TelegramAppeal[]> {
  const response = await api.get('/v1/telegram/appeals', { auth: getAuth(), params: { status: 'open' } });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function resolveTelegramAppeal(appeal: TelegramAppeal, status: 'handled' | 'rejected'): Promise<void> {
  await api.post(
    `/v1/telegram/appeals/${appeal.appeal_id}/resolve`,
    { status, expected_row_version: appeal.row_version, idempotency_key: newIdempotencyKey() },
    { auth: getAuth() },
  );
}

export async function listTelegramSupportRequests(status: 'open' | 'read' | 'resolved' | 'all'): Promise<TelegramSupportRequest[]> {
  const response = await api.get('/v1/telegram/support', { auth: getAuth(), params: { status, limit: 100 } });
  return Array.isArray(response.data?.items) ? response.data.items : [];
}

export async function resolveTelegramSupportRequest(request: TelegramSupportRequest, response: string): Promise<void> {
  await api.post(`/v1/telegram/support/${request.support_request_id}/resolve`, {
    expected_row_version: request.row_version,
    response,
    idempotency_key: newIdempotencyKey(),
  }, { auth: getAuth() });
}
