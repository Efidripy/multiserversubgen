import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useToast } from './Toast';
import { UIIcon } from './UIIcon';
import {
  approveTelegramRequest,
  blockTelegramRequest,
  BlockedIdentity,
  addCustomerNode,
  adoptExistingTelegramCustomer,
  CustomerNode,
  CustomerOperation,
  CustomerOperationPreview,
  CustomerTraffic,
  CustomerTag,
  CustomerTimelineEvent,
  DriftFinding,
  LifecycleSchedule,
  BulkLifecyclePreview,
  discoverExistingTelegramCustomer,
  ExistingDiscoveryCandidate,
  getCustomerNodes,
  getCustomerOperations,
  getCustomerTraffic,
  getCustomerTags,
  getCustomerTimeline,
  getTelegramDashboard,
  getTelegramBotConfiguration,
  getTelegramTransport,
  listTelegramCustomers,
  listTelegramAppeals,
  listTelegramJobs,
  listBlockedTelegramIdentities,
  listTelegramRequests,
  listLifecycleSchedules,
  listDriftFindings,
  previewCustomerOperation,
  previewCustomerNodeOperation,
  queueCustomerOperation,
  queueCustomerNodeOperation,
  previewBulkCustomerOperations,
  queueBulkCustomerOperations,
  rejectTelegramRequest,
  retryCustomerOperation,
  TelegramCustomer,
  TelegramAppeal,
  TelegramSupportRequest,
  TelegramBotConfigurationStatus,
  ProvisioningJob,
  TelegramRequest,
  TelegramTransportStatus,
  setTelegramTransport,
  setTelegramBotConfiguration,
  clearTelegramBotConfiguration,
  reconcileTelegramJob,
  scheduleCustomerOperation,
  cancelLifecycleSchedule,
  scanDrift,
  resolveDriftFinding,
  adoptDriftFinding,
  resolveTelegramAppeal,
  resolveTelegramSupportRequest,
  listTelegramSupportRequests,
  queueTelegramCustomerMessage,
  setCustomerTags,
  unblockTelegramIdentity,
} from '../api/telegram';

const shellClass = 'min-h-screen min-w-0 bg-[#080c15] p-4 text-slate-100 sm:p-5 lg:p-6';
const panelClass = 'min-w-0 overflow-hidden rounded-[7px] border border-cyan-400/15 bg-[#0d131f] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.025),0_18px_50px_rgba(0,0,0,0.18)]';
const inputClass = 'w-full rounded-[6px] border border-cyan-400/18 bg-[#0a0f19] px-2.5 py-1.5 text-xs text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/70 focus:ring-2 focus:ring-cyan-300/15';
const buttonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-[6px] border border-cyan-400/18 bg-[#0a0f19] px-3 text-[11px] font-medium uppercase tracking-[0.1em] text-slate-300 transition hover:border-cyan-300/55 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70 disabled:cursor-not-allowed disabled:opacity-45';
const primaryButtonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-[6px] border border-cyan-200/35 bg-cyan-300 px-3 text-[11px] font-medium uppercase tracking-[0.1em] text-[#06111f] transition hover:bg-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-100 focus-visible:ring-offset-2 focus-visible:ring-offset-[#080c15] disabled:cursor-not-allowed disabled:opacity-45';

type TelegramAdminTab = 'users' | 'operations' | 'settings';
type TelegramUsersSection = 'requests' | 'customers' | 'support' | 'blocked';

const formatDate = (value: string | null) => value ? new Date(value.replace(' ', 'T')).toLocaleString() : '—';
const formatBytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
};
const customerStatusDotClass = (status: string) => {
  if (status === 'active') return 'bg-emerald-400';
  if (['deleting', 'deleted'].includes(status)) return 'bg-rose-400';
  return 'bg-amber-400';
};

export const TelegramAdmin: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [requests, setRequests] = useState<TelegramRequest[]>([]);
  const [blocked, setBlocked] = useState<BlockedIdentity[]>([]);
  const [customers, setCustomers] = useState<TelegramCustomer[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [isCustomerDialogOpen, setIsCustomerDialogOpen] = useState(false);
  const [nodes, setNodes] = useState<CustomerNode[]>([]);
  const [operations, setOperations] = useState<CustomerOperation[]>([]);
  const [traffic, setTraffic] = useState<CustomerTraffic | null>(null);
  const [tags, setTags] = useState<CustomerTag[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [timeline, setTimeline] = useState<CustomerTimelineEvent[]>([]);
  const [preview, setPreview] = useState<CustomerOperationPreview | null>(null);
  const [previewNodeId, setPreviewNodeId] = useState<number | null>(null);
  const [nodeAddConfirmation, setNodeAddConfirmation] = useState<CustomerNode | null>(null);
  const [customerRefreshDeadline, setCustomerRefreshDeadline] = useState<number | null>(null);
  const [applicationNoteTooltip, setApplicationNoteTooltip] = useState<{ note: string; left: number; top: number } | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [transport, setTransport] = useState<TelegramTransportStatus | null>(null);
  const [botConfiguration, setBotConfiguration] = useState<TelegramBotConfigurationStatus | null>(null);
  const [botToken, setBotToken] = useState('');
  const [jobs, setJobs] = useState<ProvisioningJob[]>([]);
  const [appeals, setAppeals] = useState<TelegramAppeal[]>([]);
  const [supportRequests, setSupportRequests] = useState<TelegramSupportRequest[]>([]);
  const [selectedSupportCustomerId, setSelectedSupportCustomerId] = useState<number | null>(null);
  const [supportReply, setSupportReply] = useState<{ request: TelegramSupportRequest; body: string } | null>(null);
  const [isSupportCustomerDialogOpen, setIsSupportCustomerDialogOpen] = useState(false);
  const [supportSearch, setSupportSearch] = useState('');
  const [supportPage, setSupportPage] = useState(1);
  const [supportMessageBody, setSupportMessageBody] = useState('');
  const [supportMessageConfirmation, setSupportMessageConfirmation] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<Record<string, number> | null>(null);
  const [schedules, setSchedules] = useState<LifecycleSchedule[]>([]);
  const [driftFindings, setDriftFindings] = useState<DriftFinding[]>([]);
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<number[]>([]);
  const [bulkPreview, setBulkPreview] = useState<BulkLifecyclePreview | null>(null);
  const [scheduleAt, setScheduleAt] = useState('');
  const [approval, setApproval] = useState<{ request: TelegramRequest; mode: 'new' | 'existing'; email: string; candidate?: ExistingDiscoveryCandidate } | null>(null);
  const [activeTab, setActiveTab] = useState<TelegramAdminTab>('users');
  const [activeUsersSection, setActiveUsersSection] = useState<TelegramUsersSection>('requests');
  const [selectedRequestId, setSelectedRequestId] = useState<number | null>(null);
  const [customerStatusFilter, setCustomerStatusFilter] = useState('');
  const [customerPage, setCustomerPage] = useState(1);
  const selectedCustomer = useMemo(
    () => customers.find((item) => item.customer_id === selectedCustomerId) ?? null,
    [customers, selectedCustomerId],
  );
  const selectedRequest = useMemo(
    () => requests.find((item) => item.telegram_user_id === selectedRequestId) ?? requests[0] ?? null,
    [requests, selectedRequestId],
  );
  const filteredCustomers = useMemo(
    () => customers.filter((customer) => !customerStatusFilter || customer.status === customerStatusFilter),
    [customers, customerStatusFilter],
  );
  const customerStatusOptions = useMemo(
    () => [...new Set(customers.map((customer) => customer.status))].sort(),
    [customers],
  );
  const customerPageSize = 15;
  const customerPageCount = Math.max(1, Math.ceil(filteredCustomers.length / customerPageSize));
  const visibleCustomers = useMemo(
    () => filteredCustomers.slice((Math.min(customerPage, customerPageCount) - 1) * customerPageSize, Math.min(customerPage, customerPageCount) * customerPageSize),
    [customerPage, customerPageCount, filteredCustomers],
  );
  const supportCustomers = useMemo(() => {
    const grouped = new Map<number, { customerId: number; emailDisplay: string; telegramUserId: number; requests: TelegramSupportRequest[]; openCount: number; latestAt: string }>();
    for (const request of supportRequests) {
      const existing = grouped.get(request.customer_id);
      if (existing) {
        existing.requests.push(request);
        if (request.status !== 'resolved') existing.openCount += 1;
        if (request.created_at > existing.latestAt) existing.latestAt = request.created_at;
      } else {
        grouped.set(request.customer_id, {
          customerId: request.customer_id,
          emailDisplay: request.email_display,
          telegramUserId: request.telegram_user_id,
          requests: [request],
          openCount: request.status === 'resolved' ? 0 : 1,
          latestAt: request.created_at,
        });
      }
    }
    return [...grouped.values()]
      .map((customer) => ({ ...customer, requests: [...customer.requests].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.support_request_id - b.support_request_id) }))
      .sort((a, b) => (b.openCount - a.openCount) || b.latestAt.localeCompare(a.latestAt));
  }, [supportRequests]);
  const selectedSupportCustomer = useMemo(
    () => supportCustomers.find((customer) => customer.customerId === selectedSupportCustomerId) ?? supportCustomers[0] ?? null,
    [selectedSupportCustomerId, supportCustomers],
  );
  const filteredSupportCustomers = useMemo(() => {
    const normalized = supportSearch.trim().toLocaleLowerCase();
    if (!normalized) return supportCustomers;
    return supportCustomers.filter((customer) => {
      const profile = customers.find((item) => item.customer_id === customer.customerId);
      const identity = [profile?.telegram_username, profile?.telegram_first_name, profile?.telegram_last_name, customer.telegramUserId]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase();
      return `${customer.emailDisplay} ${identity}`.toLocaleLowerCase().includes(normalized);
    });
  }, [customers, supportCustomers, supportSearch]);
  const supportPageSize = 15;
  const supportPageCount = Math.max(1, Math.ceil(filteredSupportCustomers.length / supportPageSize));
  const visibleSupportCustomers = useMemo(
    () => filteredSupportCustomers.slice((Math.min(supportPage, supportPageCount) - 1) * supportPageSize, Math.min(supportPage, supportPageCount) * supportPageSize),
    [filteredSupportCustomers, supportPage, supportPageCount],
  );
  const openSupportRequests = useMemo(
    () => supportRequests.filter((request) => request.status !== 'resolved'),
    [supportRequests],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRequests, nextCustomers, nextBlocked, nextTransport, nextBotConfiguration, nextJobs, nextAppeals, nextSupportRequests, nextDashboard, nextSchedules, nextDrift] = await Promise.all([
        listTelegramRequests(), listTelegramCustomers(search), listBlockedTelegramIdentities(), getTelegramTransport(), getTelegramBotConfiguration(), listTelegramJobs(), listTelegramAppeals(), listTelegramSupportRequests('all'), getTelegramDashboard(), listLifecycleSchedules(), listDriftFindings(),
      ]);
      setRequests(nextRequests);
      setCustomers(nextCustomers);
      setBlocked(nextBlocked);
      setTransport(nextTransport);
      setBotConfiguration(nextBotConfiguration);
      setJobs(nextJobs);
      setAppeals(nextAppeals);
      setSupportRequests(nextSupportRequests);
      setSelectedSupportCustomerId((current) => current && nextSupportRequests.some((item) => item.customer_id === current) ? current : nextSupportRequests[0]?.customer_id ?? null);
      setDashboard(nextDashboard);
      setSchedules(nextSchedules);
      setDriftFindings(nextDrift);
      setSelectedCustomerIds((current) => current.filter((customerId) => nextCustomers.some((customer) => customer.customer_id === customerId)));
    } catch {
      toast(t('telegram.loadFailed'), 'error');
    } finally {
      setLoading(false);
    }
  }, [search, t, toast]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!isCustomerDialogOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (applicationNoteTooltip) setApplicationNoteTooltip(null);
      else if (preview) { setPreview(null); setPreviewNodeId(null); }
      else if (nodeAddConfirmation) setNodeAddConfirmation(null);
      else setIsCustomerDialogOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [applicationNoteTooltip, isCustomerDialogOpen, nodeAddConfirmation, preview]);

  useEffect(() => {
    if (!applicationNoteTooltip) return undefined;
    const closeTooltip = () => setApplicationNoteTooltip(null);
    window.addEventListener('scroll', closeTooltip, true);
    window.addEventListener('resize', closeTooltip);
    return () => {
      window.removeEventListener('scroll', closeTooltip, true);
      window.removeEventListener('resize', closeTooltip);
    };
  }, [applicationNoteTooltip]);

  const showApplicationNoteTooltip = useCallback((anchor: HTMLElement, note: string) => {
    const rect = anchor.getBoundingClientRect();
    const width = Math.min(288, window.innerWidth - 24);
    setApplicationNoteTooltip({
      note,
      left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
      top: Math.min(rect.bottom + 8, window.innerHeight - 80),
    });
  }, []);

  const refreshCustomerDetails = useCallback(async (customerId: number, syncTagInput = false) => {
    const refreshToken = Date.now();
    const [nextNodes, nextOperations, nextTraffic, nextTags, nextTimeline, nextJobs, nextCustomers] = await Promise.all([
      getCustomerNodes(customerId, refreshToken),
      getCustomerOperations(customerId, refreshToken),
      getCustomerTraffic(customerId, refreshToken),
      getCustomerTags(customerId, refreshToken),
      getCustomerTimeline(customerId, refreshToken),
      listTelegramJobs(),
      listTelegramCustomers(search, refreshToken),
    ]);
    setNodes(nextNodes);
    setOperations(nextOperations);
    setTraffic(nextTraffic);
    setTags(nextTags);
    if (syncTagInput) setTagInput(nextTags.map((tag) => tag.tag).join(', '));
    setTimeline(nextTimeline);
    setJobs(nextJobs);
    setCustomers(nextCustomers);
  }, [search]);

  const selectCustomer = useCallback(async (customer: TelegramCustomer) => {
    setSelectedCustomerId(customer.customer_id);
    setPreview(null);
    setPreviewNodeId(null);
    setNodes([]);
    setOperations([]);
    setTraffic(null);
    setTags([]);
    setTimeline([]);
    try {
      await refreshCustomerDetails(customer.customer_id, true);
    } catch {
      toast(t('telegram.detailsFailed'), 'error');
    }
  }, [refreshCustomerDetails, t, toast]);

  const openCustomerDialog = useCallback((customer: TelegramCustomer) => {
    setIsCustomerDialogOpen(true);
    void selectCustomer(customer);
  }, [selectCustomer]);

  const confirmNew = async () => {
    if (!approval || approval.mode !== 'new') return;
    setMutating(true);
    try {
      await approveTelegramRequest(approval.request, approval.email);
      toast(t('telegram.approvalQueued'), 'success');
      setApproval(null);
      await load();
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const discoverExisting = async () => {
    if (!approval || approval.mode !== 'existing') return;
    setMutating(true);
    try {
      const candidate = await discoverExistingTelegramCustomer(approval.request, approval.email);
      setApproval((current) => current ? { ...current, email: candidate.email_display, candidate } : current);
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const confirmExisting = async () => {
    if (!approval || approval.mode !== 'existing' || !approval.candidate) return;
    setMutating(true);
    try {
      await adoptExistingTelegramCustomer(approval.request, approval.email);
      toast(t('telegram.requestUpdated'), 'success');
      setApproval(null);
      await load();
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const decideRequest = async (request: TelegramRequest, action: 'reject' | 'block') => {
    if (!window.confirm(t(action === 'block' ? 'telegram.blockConfirm' : 'telegram.rejectConfirm'))) return;
    setMutating(true);
    try {
      if (action === 'block') await blockTelegramRequest(request);
      else await rejectTelegramRequest(request);
      toast(t('telegram.requestUpdated'), 'success');
      await load();
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const makePreview = async (operationType: CustomerOperationPreview['operation_type']) => {
    if (!selectedCustomer) return;
    setMutating(true);
    try {
      const next = await previewCustomerOperation(selectedCustomer.customer_id, operationType);
      setPreview(next);
      setPreviewNodeId(null);
    } catch {
      toast(t('telegram.previewFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const addNode = async () => {
    if (!selectedCustomer || !nodeAddConfirmation) return;
    setMutating(true);
    try {
      await addCustomerNode(selectedCustomer, nodeAddConfirmation.node_id);
      setNodeAddConfirmation(null);
      setCustomerRefreshDeadline(Date.now() + 30_000);
      toast(t('telegram.nodeOperationQueued'), 'success');
      await refreshCustomerDetails(selectedCustomer.customer_id);
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const makeNodePreview = async (node: CustomerNode, operationType: 'suspend_node' | 'resume_node') => {
    if (!selectedCustomer) return;
    setMutating(true);
    try {
      const next = await previewCustomerNodeOperation(selectedCustomer.customer_id, node.node_id, operationType);
      setPreview(next);
      setPreviewNodeId(node.node_id);
    } catch {
      toast(t('telegram.previewFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const confirmPreview = async () => {
    if (!preview) return;
    setMutating(true);
    try {
      if (previewNodeId === null) await queueCustomerOperation(preview);
      else await queueCustomerNodeOperation(preview, previewNodeId);
      toast(t('telegram.operationQueued'), 'success');
      setPreview(null);
      setPreviewNodeId(null);
      setCustomerRefreshDeadline(Date.now() + 30_000);
      if (selectedCustomer) await refreshCustomerDetails(selectedCustomer.customer_id);
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const saveTags = async () => {
    if (!selectedCustomer) return;
    const nextTags = tagInput.split(',').map((value) => value.trim()).filter(Boolean);
    setMutating(true);
    try {
      const saved = await setCustomerTags(selectedCustomer.customer_id, nextTags);
      setTags(saved);
      setTagInput(saved.map((tag) => tag.tag).join(', '));
      toast(t('telegram.tagsSaved'), 'success');
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const schedulePreview = async () => {
    if (!preview || !scheduleAt || previewNodeId !== null || !['suspend', 'delete'].includes(preview.operation_type)) return;
    setMutating(true);
    try {
      await scheduleCustomerOperation(preview, new Date(scheduleAt).toISOString());
      setScheduleAt('');
      setPreview(null);
      toast(t('telegram.scheduleCreated'), 'success');
      await load();
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const cancelSchedule = async (schedule: LifecycleSchedule) => {
    if (!window.confirm(t('telegram.scheduleCancelConfirm'))) return;
    setMutating(true);
    try {
      await cancelLifecycleSchedule(schedule);
      toast(t('telegram.scheduleCancelled'), 'success');
      await load();
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const makeBulkPreview = async (operationType: BulkLifecyclePreview['operation_type']) => {
    if (selectedCustomerIds.length === 0) return;
    setMutating(true);
    try {
      setBulkPreview(await previewBulkCustomerOperations(selectedCustomerIds, operationType));
    } catch {
      toast(t('telegram.previewFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const confirmBulkPreview = async () => {
    if (!bulkPreview || bulkPreview.items.some((item) => item.blocked_binding_ids.length > 0)) return;
    if (!window.confirm(t('telegram.bulkConfirm', { count: bulkPreview.items.length }))) return;
    setMutating(true);
    try {
      await queueBulkCustomerOperations(bulkPreview);
      setBulkPreview(null);
      setSelectedCustomerIds([]);
      toast(t('telegram.operationQueued'), 'success');
      await load();
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const runDriftScan = async () => {
    setMutating(true);
    try {
      await scanDrift();
      setDriftFindings(await listDriftFindings());
      toast(t('telegram.driftScanDone'), 'success');
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const resolveDrift = async (finding: DriftFinding, adopt = false) => {
    if (adopt && !window.confirm(t('telegram.driftAdoptConfirm'))) return;
    setMutating(true);
    try {
      if (adopt) await adoptDriftFinding(finding);
      else await resolveDriftFinding(finding);
      setDriftFindings(await listDriftFindings());
      toast(t('telegram.requestUpdated'), 'success');
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const selectTransport = async (mode: TelegramTransportStatus['mode']) => {
    if (!transport || transport.mode === mode) return;
    setMutating(true);
    try {
      const nextTransport = await setTelegramTransport(transport, mode);
      setTransport(nextTransport);
      toast(t('telegram.transportUpdated'), 'success');
    } catch {
      toast(t('telegram.transportUpdateFailed'), 'error');
      await load();
    } finally {
      setMutating(false);
    }
  };

  const saveBotToken = async () => {
    if (!botConfiguration || !botToken.trim()) return;
    const tokenToSave = botToken;
    setMutating(true);
    try {
      const nextConfiguration = await setTelegramBotConfiguration(botConfiguration, tokenToSave);
      setBotConfiguration(nextConfiguration);
      setBotToken('');
      toast(t('telegram.botTokenSaved'), 'success');
    } catch {
      setBotToken('');
      toast(t('telegram.botTokenSaveFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const clearBotToken = async () => {
    if (!botConfiguration || botConfiguration.source !== 'panel') return;
    if (!window.confirm(t('telegram.botTokenClearConfirm'))) return;
    setMutating(true);
    try {
      const nextConfiguration = await clearTelegramBotConfiguration(botConfiguration);
      setBotConfiguration(nextConfiguration);
      setBotToken('');
      toast(t('telegram.botTokenCleared'), 'success');
    } catch {
      toast(t('telegram.botTokenSaveFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const submitSupportReply = async () => {
    if (!supportReply || !supportReply.body.trim()) return;
    setMutating(true);
    try {
      await resolveTelegramSupportRequest(supportReply.request, supportReply.body.trim());
      setSupportReply(null);
      toast(t('telegram.supportResolved'), 'success');
      await load();
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const submitSupportCustomerMessage = async () => {
    if (!selectedSupportCustomer || !supportMessageConfirmation?.trim()) return;
    setMutating(true);
    try {
      await queueTelegramCustomerMessage(selectedSupportCustomer.customerId, supportMessageConfirmation);
      setSupportMessageBody('');
      setSupportMessageConfirmation(null);
      toast(t('telegram.directMessageQueued'), 'success');
    } catch {
      toast(t('telegram.actionFailed'), 'error');
    } finally {
      setMutating(false);
    }
  };

  const selectedTitle = useMemo(() => selectedCustomer?.email_display ?? t('telegram.selectCustomer'), [selectedCustomer, t]);
  const pendingNodeIds = useMemo(() => new Set(
    jobs
      .filter((job) => job.customer_id === selectedCustomer?.customer_id && ['queued', 'running', 'partial'].includes(job.status))
      .flatMap((job) => job.attempts)
      .filter((attempt) => ['pending', 'reconciling', 'creating', 'ambiguous'].includes(attempt.status))
      .map((attempt) => attempt.node_id),
  ), [jobs, selectedCustomer?.customer_id]);
  const hasPendingCustomerWork = useMemo(
    () => pendingNodeIds.size > 0 || operations.some((operation) => (
      ['queued', 'running'].includes(operation.status)
      || operation.attempts.some((attempt) => ['pending', 'reconciling', 'creating', 'ambiguous'].includes(attempt.status))
    )),
    [operations, pendingNodeIds],
  );

  useEffect(() => {
    if (!isCustomerDialogOpen || !selectedCustomer || (!hasPendingCustomerWork && !customerRefreshDeadline)) return undefined;
    const customerId = selectedCustomer.customer_id;
    const refresh = () => {
      if (customerRefreshDeadline && Date.now() >= customerRefreshDeadline) {
        setCustomerRefreshDeadline(null);
        return;
      }
      void refreshCustomerDetails(customerId).catch(() => undefined);
    };
    const intervalId = window.setInterval(refresh, 2500);
    return () => window.clearInterval(intervalId);
  }, [customerRefreshDeadline, hasPendingCustomerWork, isCustomerDialogOpen, refreshCustomerDetails, selectedCustomer]);

  const usersAttention = requests.length + appeals.length + openSupportRequests.length;
  const operationsAttention = jobs.filter((job) => ['partial', 'failed', 'ambiguous', 'blocked'].includes(job.status)).length + driftFindings.length;
  const tabs: Array<{ id: TelegramAdminTab; icon: React.ComponentProps<typeof UIIcon>['name']; label: string; attention?: number }> = [
    { id: 'users', icon: 'clients', label: t('telegram.tabs.users'), attention: usersAttention },
    { id: 'operations', icon: 'monitoring', label: t('telegram.tabs.operations'), attention: operationsAttention },
    { id: 'settings', icon: 'servers', label: t('telegram.tabs.settings') },
  ];
  return (
    <>
    <div className={shellClass}>
      <div className="mb-5 border-b border-cyan-400/13 pb-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
            <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300"><UIIcon name="bell" size={14} />{t('telegram.title')}</p>
            <h2 className="mt-2 text-xl font-medium tracking-[-0.02em] text-[#eef4fa]">{tabs.find((tab) => tab.id === activeTab)?.label}</h2>
            <p className="mt-1 max-w-2xl text-xs font-light text-slate-500">{t('telegram.hint')}</p>
        </div>
          <button type="button" className={buttonClass} onClick={() => void load()} disabled={loading || mutating} aria-live="polite"><UIIcon name="refresh" size={14} />{t('common.refresh')}</button>
        </div>
      </div>

      <nav className="mb-4 overflow-x-auto border-b border-cyan-400/14" aria-label={t('telegram.tabs.label')}>
        <div className="flex min-w-max gap-6">
          {tabs.map((tab) => {
            const selected = activeTab === tab.id;
            return <button
              key={tab.id}
              id={`telegram-tab-${tab.id}`}
              type="button"
              aria-pressed={selected}
              className={`inline-flex items-center gap-2 border-b-2 px-0 pb-3 text-xs font-medium tracking-[0.03em] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#080c15] ${selected ? 'border-cyan-300 text-cyan-100 shadow-[0_8px_12px_-9px_rgba(34,211,238,0.9)]' : 'border-transparent text-slate-500 hover:border-cyan-400/35 hover:text-slate-300'}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <UIIcon name={tab.icon} size={15} />
              {tab.label}
              {tab.attention !== undefined && tab.attention > 0 && <span className={`rounded-full px-1.5 py-0.5 font-mono text-[10px] ${selected ? 'bg-cyan-300 text-[#07111c]' : 'bg-[#151d2a] text-slate-400'}`}>{tab.attention}</span>}
            </button>;
          })}
        </div>
      </nav>

      {activeTab === 'operations' && dashboard && <div className="mb-4 grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.75fr)]">
        <section className={panelClass} aria-label={t('telegram.jobsTitle')}>
          <div className="flex items-center justify-between gap-3 border-b border-cyan-400/12 pb-3"><div><h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-200">{t('telegram.jobsTitle')}</h3><p className="mt-1 text-[11px] text-slate-500">{t('telegram.operations')}</p></div><span className="rounded-full bg-[#151d2a] px-2 py-1 font-mono text-[10px] text-cyan-100">{jobs.length}</span></div>
          <div className="mt-3 space-y-2">{jobs.slice(0, 4).map((job) => <div key={job.job_id} className="flex flex-wrap items-center justify-between gap-3 rounded border border-cyan-400/12 bg-[#0a0f19] px-3 py-2"><span className="min-w-0 truncate text-xs text-slate-200">{job.customer_email}</span><span className={['succeeded'].includes(job.status) ? 'font-mono text-[10px] text-emerald-200' : 'font-mono text-[10px] text-amber-200'}>{job.status}</span></div>)}{jobs.length === 0 && <p className="py-7 text-center text-sm font-light text-slate-500">{t('telegram.noJobs')}</p>}</div>
        </section>
        <aside className={panelClass} aria-label={t('telegram.attentionTitle')}>
          <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-200">{t('telegram.attentionTitle')}</h3>
          <div className={`mt-3 rounded border p-3 ${operationsAttention > 0 ? 'border-amber-400/25 bg-amber-400/[0.055]' : 'border-emerald-400/20 bg-emerald-400/[0.04]'}`}><span className="block font-mono text-2xl text-[#e9f1f8]">{operationsAttention}</span><span className="mt-1 block text-[10px] uppercase tracking-[0.12em] text-slate-500">{operationsAttention > 0 ? t('telegram.attentionItems') : t('telegram.attentionEmpty')}</span></div>
          <div className="mt-3 grid grid-cols-3 gap-2">{[['provisioning_attention', 'telegram.dashboardProvisioning'], ['lifecycle_attention', 'telegram.dashboardLifecycle'], ['open_drift_findings', 'telegram.dashboardDrift']].map(([key, label]) => <div key={key} className="rounded border border-cyan-400/10 bg-[#0a0f19] px-2 py-2"><span className="block font-mono text-sm text-cyan-100">{dashboard[key] ?? 0}</span><span className="mt-1 block text-[9px] uppercase tracking-[0.08em] text-slate-500">{t(label)}</span></div>)}</div>
        </aside>
      </div>}

      {activeTab === 'settings' && <section className={`${panelClass} mb-4`} aria-label={t('telegram.tabs.settings')}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-[7px] border border-cyan-400/18 bg-cyan-400/[0.06] text-cyan-200"><UIIcon name="servers" size={19} /></span><div><h3 className="text-sm font-medium text-[#e9f1f8]">{t('telegram.tabs.settings')}</h3><p className="mt-1 text-xs text-slate-500">{t('telegram.hint')}</p></div></div>
          <div className="flex flex-wrap gap-2"><span className={`rounded border px-2 py-1 font-mono text-[10px] ${botConfiguration?.configured ? 'border-emerald-400/25 text-emerald-200' : 'border-amber-400/25 text-amber-200'}`}>{botConfiguration?.configured ? t('telegram.botTokenConfigured', { suffix: botConfiguration.token_suffix ?? '••••' }) : t('telegram.botTokenNotConfigured')}</span><span className={`rounded border px-2 py-1 font-mono text-[10px] ${transport?.reachable ? 'border-emerald-400/25 text-emerald-200' : 'border-slate-500/25 text-slate-500'}`}>{transport?.reachable ? t('telegram.transportReady') : t('telegram.transportUnavailable')}</span></div>
        </div>
      </section>}

      {activeTab === 'settings' && <section className={`${panelClass} mb-4`} aria-label={t('telegram.botTokenTitle')}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.botTokenTitle')}</h3>
            <p className="mt-1 max-w-3xl text-xs font-light text-slate-500">{t('telegram.botTokenHint')}</p>
          </div>
          <span className={`rounded border px-2 py-1 font-mono text-[10px] ${botConfiguration?.configured ? 'border-emerald-400/25 text-emerald-200' : 'border-amber-400/25 text-amber-200'}`}>
            {botConfiguration?.configured
              ? t('telegram.botTokenConfigured', { suffix: botConfiguration.token_suffix ?? '••••' })
              : t('telegram.botTokenNotConfigured')}
          </span>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto]">
          <input
            className={inputClass}
            type="password"
            inputMode="text"
            autoComplete="new-password"
            value={botToken}
            onChange={(event) => setBotToken(event.target.value)}
            placeholder={t('telegram.botTokenPlaceholder')}
            aria-label={t('telegram.botTokenInputLabel')}
          />
          <button type="button" className={primaryButtonClass} disabled={mutating || !botConfiguration || !botToken.trim()} onClick={() => void saveBotToken()}>{t('common.save')}</button>
          <button type="button" className={buttonClass} disabled={mutating || botConfiguration?.source !== 'panel'} onClick={() => void clearBotToken()}>{t('telegram.botTokenUseEnvironment')}</button>
        </div>
        <p className="mt-2 text-[11px] text-slate-500">{botConfiguration?.source === 'panel' ? t('telegram.botTokenPanelSource') : t('telegram.botTokenEnvironmentSource')}</p>
      </section>}

      {activeTab === 'settings' && <section className={`${panelClass} mb-4`} aria-label={t('telegram.transportTitle')}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.transportTitle')}</h3>
            <p className="mt-1 text-xs font-light text-slate-500">{t('telegram.transportHint')}</p>
          </div>
          <span className={`rounded border px-2 py-1 font-mono text-[10px] ${transport?.reachable ? 'border-emerald-400/25 text-emerald-200' : 'border-slate-500/25 text-slate-500'}`}>
            {transport?.reachable ? t('telegram.transportReady') : t('telegram.transportUnavailable')}
          </span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={transport?.mode === 'direct' ? primaryButtonClass : buttonClass} disabled={mutating || !transport || transport.mode === 'direct'} onClick={() => void selectTransport('direct')}>
            {t('telegram.transportDirect')}
          </button>
          <button type="button" className={transport?.mode === 'local_proxy' ? primaryButtonClass : buttonClass} disabled={mutating || !transport?.configured || !transport?.reachable || transport.mode === 'local_proxy'} onClick={() => void selectTransport('local_proxy')}>
            {t('telegram.transportLocalProxy')}
          </button>
        </div>
        {transport && !transport.configured && <p className="mt-2 text-xs text-slate-500">{t('telegram.transportNotConfigured')}</p>}
      </section>}

      {activeTab === 'users' && <>
        <section className="mb-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label={t('telegram.dashboardTitle')}>
          {[
            { id: 'requests' as const, value: requests.length, label: t('telegram.requests'), icon: 'bell' as const, tone: 'amber' },
            { id: 'customers' as const, value: customers.length, label: t('telegram.customers'), icon: 'clients' as const, tone: 'cyan' },
            { id: 'support' as const, value: openSupportRequests.length, label: t('telegram.supportOpenTitle'), icon: 'note' as const, tone: 'violet' },
            { id: 'blocked' as const, value: blocked.length, label: t('telegram.blocked'), icon: 'statusOff' as const, tone: 'slate' },
          ].map((metric) => {
            const selected = activeUsersSection === metric.id;
            return <button key={metric.id} type="button" aria-pressed={selected} onClick={() => setActiveUsersSection(metric.id)} className={`relative flex h-[58px] min-w-0 items-center gap-2.5 rounded-[7px] border px-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70 ${selected ? 'border-cyan-300/50 bg-cyan-400/[0.08] shadow-[inset_0_-2px_0_#22d3ee]' : metric.tone === 'amber' ? 'border-amber-400/22 bg-[#0d131f] hover:border-amber-300/45' : 'border-cyan-400/12 bg-[#0d131f] hover:border-cyan-300/35'}`}>
              <span className={`grid size-8 shrink-0 place-items-center rounded-[6px] ${metric.tone === 'amber' ? 'bg-amber-400/10 text-amber-200' : metric.tone === 'violet' ? 'bg-violet-400/10 text-violet-200' : 'bg-cyan-400/10 text-cyan-200'}`}><UIIcon name={metric.icon} size={16} /></span><span><span className="block font-mono text-[15px] font-semibold leading-5 text-[#e9f1f8]">{metric.value}</span><span className="block pt-0.5 text-[9px] uppercase tracking-[0.08em] text-slate-500">{metric.label}</span></span><span className="ml-auto shrink-0 text-sm text-slate-600" aria-hidden>›</span>
            </button>;
          })}
        </section>

        {activeUsersSection === 'customers' && <section className={`${panelClass} mb-4`} aria-label={t('telegram.customers')}>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cyan-400/12 pb-3">
            <div><h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-200">{t('telegram.customers')}</h3><p className="mt-1 text-[11px] text-slate-500">{t('telegram.shownOf', { shown: visibleCustomers.length, total: filteredCustomers.length })}</p></div>
            <div className="flex w-full flex-wrap gap-2 sm:w-auto">
              <label className="min-w-[190px] flex-1 sm:flex-none"><span className="sr-only">{t('common.search')}</span><input className={inputClass} value={search} onChange={(event) => { setSearch(event.target.value); setCustomerPage(1); }} placeholder={t('common.search')} /></label>
              <label className="min-w-[150px] flex-1 sm:flex-none"><span className="sr-only">{t('telegram.status')}</span><select className={inputClass} value={customerStatusFilter} onChange={(event) => { setCustomerStatusFilter(event.target.value); setCustomerPage(1); }} aria-label={t('telegram.status')}><option value="">{t('telegram.allStatuses')}</option>{customerStatusOptions.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
            </div>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-[11px]">
              <thead className="border-b border-cyan-400/12 bg-[#0a0f19] text-[8px] uppercase tracking-[0.12em] text-slate-500"><tr><th className="w-9 px-2 py-2" scope="col"><span className="sr-only">{t('telegram.bulkTitle')}</span></th><th className="w-[29%] px-2 py-2" scope="col">{t('telegram.customers')}</th><th className="w-[31%] px-2 py-2" scope="col">{t('telegram.telegramIdentity')}</th><th className="w-[11%] px-2 py-2" scope="col">{t('telegram.nodes')}</th><th className="w-[17%] px-2 py-2" scope="col">{t('telegram.lifetimeTraffic')}</th><th className="w-12 px-2 py-2" scope="col"><span className="sr-only">{t('telegram.applicationNote')}</span></th></tr></thead>
              <tbody>{visibleCustomers.map((customer) => {
                const telegramName = [customer.telegram_first_name, customer.telegram_last_name].filter(Boolean).join(' ');
                const open = () => openCustomerDialog(customer);
                return <tr key={customer.customer_id} className={`h-[49px] border-b border-cyan-400/[0.08] transition hover:bg-cyan-400/[0.035] ${selectedCustomer?.customer_id === customer.customer_id ? 'bg-cyan-400/[0.08]' : ''}`}>
                  <td className="px-2 py-1.5"><input type="checkbox" aria-label={t('telegram.bulkSelectCustomer', { email: customer.email_display })} checked={selectedCustomerIds.includes(customer.customer_id)} onClick={(event) => event.stopPropagation()} onChange={(event) => setSelectedCustomerIds((current) => event.target.checked ? [...current, customer.customer_id] : current.filter((customerId) => customerId !== customer.customer_id))} /></td>
                  <td className="p-0"><button type="button" className="flex h-[49px] w-full items-center gap-2 px-2 text-left text-[10px] text-slate-200 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={open} aria-label={t('telegram.openCustomer', { email: customer.email_display })}><span className={`size-[6px] shrink-0 rounded-full ${customerStatusDotClass(customer.status)}`} aria-label={customer.status} /><span className="truncate">{customer.email_display}</span></button></td>
                  <td className="p-0"><button type="button" className="flex h-[49px] w-full flex-col justify-center px-2 text-left leading-[13px] hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={open} aria-label={t('telegram.openCustomer', { email: customer.email_display })}><span className="truncate text-[10px] text-slate-300">{customer.telegram_username ? `@${customer.telegram_username}` : telegramName || '—'}</span><span className="truncate font-mono text-[9px] text-slate-500">{[telegramName, customer.telegram_user_id ? String(customer.telegram_user_id) : null].filter(Boolean).join(' · ') || '—'}</span></button></td>
                  <td className="p-0"><button type="button" className="h-[49px] w-full px-2 text-left font-mono text-[10px] text-slate-400 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={open} aria-label={t('telegram.openCustomer', { email: customer.email_display })}>{customer.node_count}</button></td>
                  <td className="p-0"><button type="button" className="h-[49px] w-full px-2 text-left font-mono text-[10px] text-slate-400 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={open} aria-label={t('telegram.openCustomer', { email: customer.email_display })}>{formatBytes(customer.lifetime_bytes)}</button></td>
                  <td className="px-2 py-1.5">{customer.application_introduction && <span className="inline-flex size-5 cursor-help items-center justify-center rounded-full border border-amber-300/45 text-[11px] font-semibold text-amber-200" tabIndex={0} aria-label={t('telegram.applicationNote', { note: customer.application_introduction })} onMouseEnter={(event) => showApplicationNoteTooltip(event.currentTarget, customer.application_introduction!)} onMouseLeave={() => setApplicationNoteTooltip(null)} onFocus={(event) => showApplicationNoteTooltip(event.currentTarget, customer.application_introduction!)} onBlur={() => setApplicationNoteTooltip(null)}>!</span>}</td>
                </tr>;
              })}</tbody>
            </table>
          </div>
          {filteredCustomers.length === 0 && <p className="py-6 text-center text-sm font-light text-slate-500">{t('telegram.noCustomers')}</p>}
          <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-cyan-400/12 pt-3"><button type="button" className={buttonClass} disabled={customerPage <= 1} onClick={() => setCustomerPage((page) => Math.max(1, page - 1))}>{t('telegram.previousPage')}</button><span className="font-mono text-[11px] text-slate-500">{customerPage} / {customerPageCount}</span><button type="button" className={buttonClass} disabled={customerPage >= customerPageCount} onClick={() => setCustomerPage((page) => Math.min(customerPageCount, page + 1))}>{t('telegram.nextPage')}</button></div>
        </section>}
      </>}

      {activeTab === 'users' && <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(290px,0.9fr)_minmax(0,1.3fr)]">
        {activeUsersSection === 'requests' && <section className={`${panelClass} xl:col-span-2 p-0`} aria-label={t('telegram.requests')}>
          <div className="grid min-w-0 xl:grid-cols-[minmax(280px,0.48fr)_minmax(0,1fr)]">
            <div className="min-w-0 border-b border-cyan-400/12 xl:border-b-0 xl:border-r">
              <div className="flex h-[45px] items-center justify-between border-b border-cyan-400/12 px-3"><h3 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-200">{t('telegram.requests')}</h3><span className="rounded-full bg-cyan-400/10 px-1.5 py-0.5 font-mono text-[10px] text-cyan-100">{requests.length}</span></div>
              <div className="max-h-[560px] overflow-auto">{requests.length === 0 && <p className="p-4 text-xs text-slate-500">{t('telegram.noRequests')}</p>}{requests.map((request) => {
                const selected = selectedRequest?.telegram_user_id === request.telegram_user_id;
                const name = request.username ? `@${request.username}` : request.first_name || t('telegram.unknownUser');
                return <button key={request.telegram_user_id} type="button" onClick={() => { setSelectedRequestId(request.telegram_user_id); setApproval(null); }} aria-pressed={selected} className={`flex min-h-[55px] w-full items-center gap-2 border-b border-cyan-400/[0.08] px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70 ${selected ? 'bg-cyan-400/[0.08] shadow-[inset_2px_0_0_#22d3ee]' : 'hover:bg-cyan-400/[0.035]'}`}><span className="grid size-7 shrink-0 place-items-center rounded-[6px] bg-cyan-400/10 font-mono text-[9px] text-cyan-100">{name.replace('@', '').slice(0, 2).toUpperCase()}</span><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-200">{name}</span><span className="mt-0.5 block truncate text-[10px] text-slate-500">{formatDate(request.requested_at)}</span></span></button>;
              })}</div>
            </div>
            <div className="min-w-0">
              {!selectedRequest && <p className="p-5 text-sm text-slate-500">{t('telegram.noRequests')}</p>}
              {selectedRequest && <div className="p-4">
                <div className="flex items-start justify-between gap-3 border-b border-cyan-400/12 pb-3"><div><p className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{t('telegram.requests')}</p><h3 className="mt-1 text-lg font-medium text-[#e9f1f8]">{selectedRequest.username ? `@${selectedRequest.username}` : selectedRequest.first_name || t('telegram.unknownUser')}</h3><p className="mt-1 font-mono text-[10px] text-slate-500">{formatDate(selectedRequest.requested_at)}</p></div></div>
                <dl className="mt-4 grid gap-x-5 gap-y-3 sm:grid-cols-2">
                  <div><dt className="text-[10px] uppercase tracking-[0.1em] text-slate-500">{t('telegram.requestTelegram')}</dt><dd className="mt-1 break-words text-xs text-slate-200">{selectedRequest.username ? `@${selectedRequest.username}` : '—'}</dd></div>
                  <div><dt className="text-[10px] uppercase tracking-[0.1em] text-slate-500">{t('telegram.requestName')}</dt><dd className="mt-1 break-words text-xs text-slate-200">{[selectedRequest.first_name, selectedRequest.last_name].filter(Boolean).join(' ') || '—'}</dd></div>
                  <div><dt className="text-[10px] uppercase tracking-[0.1em] text-slate-500">{t('telegram.requestTelegramId')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-200">{selectedRequest.telegram_user_id}</dd></div>
                  <div><dt className="text-[10px] uppercase tracking-[0.1em] text-slate-500">{t('telegram.requestSuggestedName')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-200">{selectedRequest.suggested_email || '—'}</dd></div>
                  <div className="sm:col-span-2"><dt className="text-[10px] uppercase tracking-[0.1em] text-slate-500">{t('telegram.requestIntroduction')}</dt><dd className="mt-1 whitespace-pre-wrap rounded-[6px] border border-cyan-400/10 bg-[#0a0f19] p-3 text-xs leading-5 text-slate-300">{selectedRequest.introduction_text || '—'}</dd></div>
                </dl>
                {approval?.request.telegram_user_id === selectedRequest.telegram_user_id ? (
                  <div className="mt-4 rounded-[6px] border border-amber-400/25 bg-amber-400/5 p-3"><p className="text-xs text-amber-100">{approval.mode === 'new' ? t('telegram.approvalNewTitle') : t('telegram.approvalExistingTitle')}</p><input className={`${inputClass} mt-2`} value={approval.email} onChange={(event) => setApproval((current) => current ? { ...current, email: event.target.value, candidate: undefined } : current)} aria-label={t('telegram.emailForRequest')} />{approval.mode === 'new' ? <div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} onClick={() => void confirmNew()} disabled={mutating}>{t('common.confirm')}</button><button type="button" className={buttonClass} onClick={() => setApproval(null)}>{t('common.cancel')}</button></div> : <><p className="mt-2 text-xs text-slate-500">{t('telegram.existingDiscoveryHint')}</p>{approval.candidate && <p className="mt-2 text-xs text-emerald-200">{t('telegram.existingFound', { count: approval.candidate.binding_count, nodes: approval.candidate.node_names.join(', ') })}</p>}<div className="mt-2 flex flex-wrap gap-2"><button type="button" className={buttonClass} onClick={() => void discoverExisting()} disabled={mutating}>{t('telegram.existingCheck')}</button>{approval.candidate && <button type="button" className={primaryButtonClass} onClick={() => void confirmExisting()} disabled={mutating}>✓ {t('telegram.existingBind')}</button>}<button type="button" className={buttonClass} onClick={() => setApproval(null)}>{t('common.cancel')}</button></div></>}</div>
                ) : <div className="mt-4 flex flex-wrap gap-2 border-t border-cyan-400/12 pt-3"><button type="button" className={primaryButtonClass} onClick={() => setApproval({ request: selectedRequest, mode: 'new', email: selectedRequest.suggested_email })} disabled={mutating}>{t('telegram.createNew')}</button><button type="button" className={buttonClass} onClick={() => setApproval({ request: selectedRequest, mode: 'existing', email: '' })} disabled={mutating}>{t('telegram.bindExisting')}</button><button type="button" className={buttonClass} onClick={() => void decideRequest(selectedRequest, 'reject')} disabled={mutating}>{t('telegram.reject')}</button><button type="button" className={`${buttonClass} border-rose-400/25 text-rose-200`} onClick={() => void decideRequest(selectedRequest, 'block')} disabled={mutating}>{t('telegram.block')}</button></div>}
              </div>}
            </div>
          </div>
        </section>}

        {activeUsersSection === 'blocked' && <section className={panelClass} aria-label={t('telegram.blocked')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.blocked')}</h3><div className="mt-3 space-y-2">{blocked.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noBlocked')}</p>}{blocked.map((identity) => <div key={identity.telegram_user_id} className="flex items-center justify-between gap-3 rounded border border-rose-400/15 bg-[#0a0e1a] p-3"><span className="truncate text-sm text-slate-300">{identity.username ? `@${identity.username}` : identity.first_name || `#${identity.telegram_user_id}`}</span><button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await unblockTelegramIdentity(identity); toast(t('telegram.requestUpdated'), 'success'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.unblock')}</button></div>)}</div>
        </section>}

        {activeUsersSection === 'customers' && <section className={panelClass} aria-label={t('telegram.bulkTitle')}>
          <div className="rounded-lg border border-cyan-500/15 bg-[#0a0e1a] p-3">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.bulkTitle')}</h4><p className="mt-1 text-xs text-slate-500">{t('telegram.bulkHint')}</p></div><span className="font-mono text-xs text-cyan-200">{t('telegram.bulkSelected', { count: selectedCustomerIds.length })}</span></div>
            <div className="mt-3 flex flex-wrap gap-2"><button type="button" className={buttonClass} disabled={mutating || selectedCustomerIds.length === 0} onClick={() => void makeBulkPreview('suspend')}>{t('telegram.suspend')}</button><button type="button" className={buttonClass} disabled={mutating || selectedCustomerIds.length === 0} onClick={() => void makeBulkPreview('resume')}>{t('telegram.resume')}</button></div>
            {bulkPreview && <div className="mt-3 rounded border border-amber-400/25 bg-amber-400/5 p-3"><p className="text-xs text-amber-100">{t('telegram.bulkPreviewText', { operation: t(`telegram.${bulkPreview.operation_type}`), count: bulkPreview.items.length })}</p>{bulkPreview.items.some((item) => item.blocked_binding_ids.length > 0) && <p className="mt-1 text-xs text-rose-200">{t('telegram.previewBlocked')}</p>}<div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} disabled={mutating || bulkPreview.items.some((item) => item.blocked_binding_ids.length > 0)} onClick={() => void confirmBulkPreview()}>{t('common.confirm')}</button><button type="button" className={buttonClass} onClick={() => setBulkPreview(null)}>{t('common.cancel')}</button></div></div>}
          </div>
        </section>}
      </div>}

      {isSupportCustomerDialogOpen && selectedSupportCustomer && <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#02050bcc] p-3 sm:p-5" onMouseDown={() => { if (!supportMessageConfirmation) setIsSupportCustomerDialogOpen(false); }}>
        <section role="dialog" aria-modal="true" aria-labelledby="telegram-support-customer-dialog-title" className="max-h-[calc(100vh-1.5rem)] w-full max-w-4xl overflow-hidden rounded-[8px] border border-cyan-400/20 bg-[#0d131f] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
          <div className="flex items-start justify-between gap-4 border-b border-cyan-400/12 px-4 py-3"><div className="min-w-0"><p className="text-[9px] uppercase tracking-[0.14em] text-slate-500">{t('telegram.supportTitle')}</p><h3 id="telegram-support-customer-dialog-title" className="mt-1 flex items-center gap-2 truncate text-sm font-medium text-[#e9f1f8]"><span className={`size-[7px] shrink-0 rounded-full ${selectedSupportCustomer.openCount > 0 ? 'bg-red-400' : 'bg-emerald-400'}`} />{selectedSupportCustomer.emailDisplay}</h3><p className="mt-1 text-[10px] text-slate-500">#{selectedSupportCustomer.telegramUserId} · {t('telegram.supportRequestCount', { count: selectedSupportCustomer.requests.length })}</p></div><button type="button" className={`${buttonClass} h-8 px-2`} onClick={() => setIsSupportCustomerDialogOpen(false)} disabled={Boolean(supportMessageConfirmation)} aria-label={t('telegram.closeCustomer')}><UIIcon name="x" size={15} /></button></div>
          <div className="max-h-[calc(100vh-7rem)] overflow-y-auto p-4"><section className="rounded-[7px] border border-cyan-400/12 bg-[#0a0f19] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.directMessage')}</h4><p className="mt-1 text-[11px] text-slate-500">{t('telegram.directMessageHint')}</p></div></div><label className="mt-3 block text-[10px] uppercase tracking-[0.12em] text-slate-500">{t('telegram.directMessageBody')}<textarea className={`${inputClass} mt-1 min-h-20 resize-y`} maxLength={2000} value={supportMessageBody} onChange={(event) => setSupportMessageBody(event.target.value)} /></label><div className="mt-2 flex justify-end"><button type="button" className={primaryButtonClass} disabled={mutating || !supportMessageBody.trim()} onClick={() => setSupportMessageConfirmation(supportMessageBody.trim())}>{t('telegram.directMessage')}</button></div></section><section className="mt-4"><h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.supportHistoryTitle')}</h4><div className="mt-2 space-y-2">{selectedSupportCustomer.requests.map((request) => <article key={request.support_request_id} className={`rounded border bg-[#0a0e1a] p-3 ${request.status === 'resolved' ? 'border-cyan-500/15' : 'border-red-400/25'}`}><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-[11px] text-slate-300">{t(`telegram.supportCategory.${request.category}`)}</span><span className="font-mono text-[10px] text-slate-600">{formatDate(request.created_at)}</span></div><p className="mt-2 whitespace-pre-wrap text-xs text-slate-400">{request.body}</p>{request.status === 'resolved' ? <><p className="mt-3 text-[10px] font-medium uppercase tracking-[0.12em] text-cyan-200">{t('telegram.supportReplyLabel')}</p><p className="mt-1 whitespace-pre-wrap text-xs text-slate-300">{request.admin_response || t('telegram.supportNoReply')}</p></> : supportReply?.request.support_request_id === request.support_request_id ? <div className="mt-3 rounded border border-cyan-500/20 p-2"><label className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{t('telegram.supportReplyLabel')}<textarea className={`${inputClass} mt-1 min-h-20 resize-y`} maxLength={1000} value={supportReply.body} onChange={(event) => setSupportReply((current) => current ? { ...current, body: event.target.value } : current)} /></label><div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} disabled={mutating || !supportReply.body.trim()} onClick={() => void submitSupportReply()}>{t('telegram.supportSendReply')}</button><button type="button" className={buttonClass} disabled={mutating} onClick={() => setSupportReply(null)}>{t('common.cancel')}</button></div></div> : <button type="button" className={`${buttonClass} mt-3`} disabled={mutating} onClick={() => setSupportReply({ request, body: '' })}>{t('telegram.supportReply')}</button>}</article>)}</div></section></div>
        </section>
      </div>}

      {supportMessageConfirmation && selectedSupportCustomer && <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#02050bd9] p-4" onMouseDown={() => { if (!mutating) setSupportMessageConfirmation(null); }}><section role="dialog" aria-modal="true" aria-labelledby="telegram-direct-message-confirm-title" className="w-full max-w-md rounded-[8px] border border-amber-400/30 bg-[#0d131f] p-4 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}><p className="text-[9px] uppercase tracking-[0.14em] text-amber-200">{t('telegram.directMessage')}</p><h4 id="telegram-direct-message-confirm-title" className="mt-1 text-sm font-medium text-slate-100">{t('common.confirm')}</h4><p className="mt-3 text-xs text-amber-100">{t('telegram.directMessageConfirm')}</p><p className="mt-2 whitespace-pre-wrap rounded border border-cyan-500/15 bg-[#0a0f19] p-3 text-xs text-slate-300">{supportMessageConfirmation}</p><div className="mt-4 flex justify-end gap-2"><button type="button" className={buttonClass} disabled={mutating} onClick={() => setSupportMessageConfirmation(null)}>{t('common.cancel')}</button><button type="button" className={primaryButtonClass} disabled={mutating} onClick={() => void submitSupportCustomerMessage()}>{t('common.confirm')}</button></div></section></div>}

      {isCustomerDialogOpen && selectedCustomer && <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#02050bcc] p-3 sm:p-5" onMouseDown={() => { if (!preview && !nodeAddConfirmation) setIsCustomerDialogOpen(false); }}>
        <section role="dialog" aria-modal="true" aria-labelledby="telegram-customer-dialog-title" className="max-h-[calc(100vh-1.5rem)] w-full max-w-5xl overflow-hidden rounded-[8px] border border-cyan-400/20 bg-[#0d131f] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
          <div className="flex items-start justify-between gap-4 border-b border-cyan-400/12 px-4 py-3">
            <div className="min-w-0"><p className="text-[9px] uppercase tracking-[0.14em] text-slate-500">{t('telegram.customerDetails')}</p><h3 id="telegram-customer-dialog-title" className="mt-1 flex items-center gap-2 truncate text-sm font-medium text-[#e9f1f8]"><span className={`size-[7px] shrink-0 rounded-full ${customerStatusDotClass(selectedCustomer.status)}`} />{selectedTitle}</h3><p className="mt-1 text-[10px] text-slate-500">{selectedCustomer.telegram_username ? `@${selectedCustomer.telegram_username}` : '—'} · {selectedCustomer.telegram_user_id ?? '—'}</p></div>
            <button type="button" className={`${buttonClass} h-8 px-2`} onClick={() => setIsCustomerDialogOpen(false)} disabled={Boolean(preview || nodeAddConfirmation)} aria-label={t('telegram.closeCustomer')}><UIIcon name="x" size={15} /></button>
          </div>
          <div className="max-h-[calc(100vh-7rem)] overflow-y-auto p-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[7px] border border-cyan-400/12 bg-[#0a0f19] p-3"><div><p className="text-[9px] uppercase tracking-[0.12em] text-slate-500">{t('telegram.lifetimeTraffic')}</p><p className="mt-1 font-mono text-sm text-cyan-200">{formatBytes(traffic?.lifetime_bytes ?? selectedCustomer.lifetime_bytes)}</p></div><div className="flex flex-wrap gap-2">{(['suspend', 'resume', 'delete'] as const).map((operationType) => <button key={operationType} type="button" className={operationType === 'delete' ? `${buttonClass} border-rose-400/25 text-rose-200 hover:text-rose-100` : buttonClass} onClick={() => void makePreview(operationType)} disabled={mutating}>{t(`telegram.${operationType}`)}</button>)}</div></div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div className="rounded border border-cyan-500/10 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.tagsTitle')}</h4><button type="button" className={buttonClass} disabled={mutating} onClick={() => void saveTags()}>{t('common.save')}</button></div><input className={`${inputClass} mt-2`} value={tagInput} onChange={(event) => setTagInput(event.target.value)} placeholder={t('telegram.tagsPlaceholder')} />{tags.length > 0 && <p className="mt-1 text-[11px] text-slate-500">{tags.map((tag) => tag.tag).join(' · ')}</p>}</div>
              {selectedCustomer.application_introduction && <div className="rounded border border-amber-400/15 bg-amber-400/[0.03] p-3"><h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-amber-200">{t('telegram.applicationNote')}</h4><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-300">{selectedCustomer.application_introduction}</p></div>}
            </div>
            <h4 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.nodes')}</h4><div className="mt-2 space-y-1">{nodes.map((node) => {
              const isPending = pendingNodeIds.has(node.node_id);
              const isActive = node.state === 'active';
              const isSuspended = node.state === 'suspended';
              const canAdd = node.state === 'available_to_add' && !isPending;
              return <div key={node.node_id} className="flex items-center justify-between gap-2 rounded border border-cyan-500/10 px-2 py-1.5 text-xs"><span className="flex min-w-0 items-center gap-2 truncate text-slate-300"><span className={`size-[7px] shrink-0 rounded-full ${isActive ? 'bg-emerald-400' : 'bg-rose-400'}`} aria-label={isActive ? t('telegram.nodeReady') : t('telegram.nodeNotReady')} />{node.node_name}</span><div className="flex shrink-0 items-center gap-2">{isPending && <span className="text-[10px] text-amber-200">{t('telegram.nodeQueued')}</span>}{canAdd && <button type="button" className={buttonClass} disabled={mutating || selectedCustomer.status !== 'active'} onClick={() => setNodeAddConfirmation(node)}>{t('telegram.addNode')}</button>}{isActive && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void makeNodePreview(node, 'suspend_node')}>{t('telegram.suspendNode')}</button>}{isSuspended && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void makeNodePreview(node, 'resume_node')}>{t('telegram.resumeNode')}</button>}</div></div>;
            })}</div>
            <h4 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.operations')}</h4><div className="mt-2 space-y-2">{operations.map((operation) => <div key={operation.operation_id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-cyan-500/15 px-2 py-2 text-xs"><span className="text-slate-300">{operation.operation_type} · {operation.status}</span>{operation.status === 'partial' && <button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await retryCustomerOperation(operation); toast(t('telegram.operationQueued'), 'success'); await selectCustomer(selectedCustomer); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.reconcile')}</button>}</div>)}</div>
            <h4 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.timelineTitle')}</h4><div className="mt-2 max-h-44 space-y-1 overflow-auto">{timeline.length === 0 ? <p className="text-xs text-slate-500">{t('telegram.timelineEmpty')}</p> : timeline.map((event, index) => <div key={`${event.entity_type}-${event.entity_id}-${event.created_at}-${index}`} className="flex flex-wrap justify-between gap-2 text-[11px] text-slate-400"><span>{event.event_type} · {event.status ?? '—'}</span><span className="font-mono text-slate-500">{formatDate(event.created_at)}</span></div>)}</div>
          </div>
        </section>
      </div>}

      {nodeAddConfirmation && selectedCustomer && <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#02050bd9] p-4" onMouseDown={() => { if (!mutating) setNodeAddConfirmation(null); }}>
        <section role="dialog" aria-modal="true" aria-labelledby="telegram-add-node-dialog-title" className="w-full max-w-sm rounded-[8px] border border-cyan-400/25 bg-[#0d131f] p-4 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
          <p className="text-[9px] uppercase tracking-[0.14em] text-slate-500">{t('telegram.nodes')}</p>
          <h4 id="telegram-add-node-dialog-title" className="mt-1 text-sm font-medium text-slate-100">{t('telegram.addNodeDialogTitle')}</h4>
          <div className="mt-3 flex items-center gap-2 rounded border border-cyan-400/12 bg-[#0a0f19] px-3 py-2 text-xs text-slate-200"><span className="size-[7px] shrink-0 rounded-full bg-rose-400" />{nodeAddConfirmation.node_name}</div>
          <p className="mt-3 text-xs leading-5 text-slate-400">{t('telegram.addNodeConfirm', { node: nodeAddConfirmation.node_name })}</p>
          <div className="mt-4 flex justify-end gap-2"><button type="button" className={buttonClass} disabled={mutating} onClick={() => setNodeAddConfirmation(null)}>{t('common.cancel')}</button><button type="button" className={primaryButtonClass} disabled={mutating} onClick={() => void addNode()}>{t('common.confirm')}</button></div>
        </section>
      </div>}

      {preview && selectedCustomer && <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#02050bd9] p-4" onMouseDown={() => { if (!mutating) { setPreview(null); setPreviewNodeId(null); } }}>
        <section role="dialog" aria-modal="true" aria-labelledby="telegram-operation-confirm-dialog-title" className="w-full max-w-md rounded-[8px] border border-amber-400/30 bg-[#0d131f] p-4 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
          <p className="text-[9px] uppercase tracking-[0.14em] text-amber-200">{t('telegram.operations')}</p>
          <h4 id="telegram-operation-confirm-dialog-title" className="mt-1 text-sm font-medium text-slate-100">{t('common.confirm')}</h4>
          <p className="mt-3 rounded border border-amber-400/25 bg-amber-400/5 p-3 text-xs leading-5 text-amber-100">{t('telegram.previewText', { operation: t(`telegram.${preview.operation_type}`, preview.operation_type), count: preview.targets.length })}</p>
          {preview.blocked_binding_ids.length > 0 && <p className="mt-2 text-xs text-rose-200">{t('telegram.previewBlocked')}</p>}
          {previewNodeId === null && ['suspend', 'delete'].includes(preview.operation_type) && <div className="mt-3 rounded border border-cyan-500/15 p-3"><label className="block text-[10px] uppercase tracking-[0.12em] text-slate-500">{t('telegram.scheduleAt')}<input className={`${inputClass} mt-1`} type="datetime-local" value={scheduleAt} onChange={(event) => setScheduleAt(event.target.value)} /></label><button type="button" className={`${buttonClass} mt-2`} disabled={mutating || !scheduleAt || preview.blocked_binding_ids.length > 0} onClick={() => void schedulePreview()}>{t('telegram.scheduleAction')}</button></div>}
          <div className="mt-4 flex justify-end gap-2"><button type="button" className={buttonClass} disabled={mutating} onClick={() => { setPreview(null); setPreviewNodeId(null); }}>{t('common.cancel')}</button><button type="button" className={primaryButtonClass} disabled={mutating || preview.blocked_binding_ids.length > 0} onClick={() => void confirmPreview()}>{t('common.confirm')}</button></div>
        </section>
      </div>}

      {activeTab === 'operations' && <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
        <section className={panelClass} aria-label={t('telegram.jobsTitle')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.jobsTitle')}</h3>
          <div className="mt-3 space-y-2">{jobs.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noJobs')}</p>}{jobs.map((job) => <article key={job.job_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="truncate text-xs text-slate-200">{job.customer_email}</span><span className="font-mono text-[10px] text-slate-500">{job.status}</span></div><p className="mt-1 text-[11px] text-slate-500">{t('telegram.nodesReady', { ready: job.attempts.filter((attempt) => attempt.status === 'succeeded').length, total: job.attempts.length })}</p>{job.attempts.some((attempt) => ['partial', 'failed', 'ambiguous', 'blocked'].includes(attempt.status)) && <button type="button" className={`${buttonClass} mt-2`} disabled={mutating} onClick={async () => { setMutating(true); try { await reconcileTelegramJob(job); toast(t('telegram.operationQueued'), 'success'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.reconcile')}</button>}</article>)}</div>
        </section>
      </div>}

      {activeTab === 'users' && activeUsersSection === 'support' && <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
        <section className={panelClass} aria-label={t('telegram.appealsTitle')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.appealsTitle')}</h3>
          <div className="mt-3 space-y-2">{appeals.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noAppeals')}</p>}{appeals.map((appeal) => <article key={appeal.appeal_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><span className="block truncate text-xs text-slate-200">{appeal.email_display}</span><p className="mt-2 whitespace-pre-wrap text-xs text-slate-400">{appeal.body}</p><div className="mt-2 flex gap-2"><button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await resolveTelegramAppeal(appeal, 'handled'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.closeAppeal')}</button><button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await resolveTelegramAppeal(appeal, 'rejected'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.reject')}</button></div></article>)}</div>
        </section>
      </div>}

      {activeTab === 'users' && activeUsersSection === 'support' && <section className={`${panelClass} mt-4`} aria-label={t('telegram.supportTitle')}>
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-cyan-400/12 pb-3">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.supportTitle')}</h3>
            <p className="mt-1 text-xs text-slate-500">{t('telegram.supportHint')}</p>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto"><label className="min-w-[190px] flex-1 sm:flex-none"><span className="sr-only">{t('common.search')}</span><input className={inputClass} value={supportSearch} onChange={(event) => { setSupportSearch(event.target.value); setSupportPage(1); }} placeholder={t('common.search')} /></label><span className="self-center font-mono text-xs text-amber-200">{t('telegram.supportOpenCount', { count: openSupportRequests.length })}</span></div>
        </div>
        <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[820px] text-left text-[11px]"><thead className="border-b border-cyan-400/12 bg-[#0a0f19] text-[8px] uppercase tracking-[0.12em] text-slate-500"><tr><th className="w-[30%] px-2 py-2" scope="col">{t('telegram.customers')}</th><th className="w-[29%] px-2 py-2" scope="col">{t('telegram.telegramIdentity')}</th><th className="w-[14%] px-2 py-2" scope="col">{t('telegram.supportRequestCountHeader')}</th><th className="w-[15%] px-2 py-2" scope="col">{t('telegram.status')}</th><th className="w-[18%] px-2 py-2" scope="col">{t('telegram.supportLatestRequest')}</th></tr></thead><tbody>{visibleSupportCustomers.map((customer) => { const profile = customers.find((item) => item.customer_id === customer.customerId); const telegramName = [profile?.telegram_first_name, profile?.telegram_last_name].filter(Boolean).join(' '); const open = () => { setSelectedSupportCustomerId(customer.customerId); setSupportReply(null); setSupportMessageBody(''); setIsSupportCustomerDialogOpen(true); }; return <tr key={customer.customerId} className="h-[49px] border-b border-cyan-400/[0.08] transition hover:bg-cyan-400/[0.035]"><td className="p-0"><button type="button" className="flex h-[49px] w-full items-center gap-2 px-2 text-left text-[10px] text-slate-200 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={open}><span className={`size-[6px] shrink-0 rounded-full ${customer.openCount > 0 ? 'bg-red-400' : 'bg-emerald-400'}`} aria-label={customer.openCount > 0 ? t('telegram.supportStatusOpen') : t('telegram.supportStatusAnswered')} /><span className="truncate">{customer.emailDisplay}</span></button></td><td className="p-0"><button type="button" className="flex h-[49px] w-full flex-col justify-center px-2 text-left leading-[13px] hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={open}><span className="truncate text-[10px] text-slate-300">{profile?.telegram_username ? `@${profile.telegram_username}` : telegramName || '—'}</span><span className="truncate font-mono text-[9px] text-slate-500">{[telegramName, customer.telegramUserId].filter(Boolean).join(' · ')}</span></button></td><td className="p-0"><button type="button" className="h-[49px] w-full px-2 text-left font-mono text-[10px] text-slate-400 hover:text-cyan-100" onClick={open}>{customer.requests.length}</button></td><td className="p-0"><button type="button" className="h-[49px] w-full px-2 text-left text-[10px] text-slate-400 hover:text-cyan-100" onClick={open}>{customer.openCount > 0 ? t('telegram.supportStatusOpen') : t('telegram.supportStatusAnswered')}</button></td><td className="p-0"><button type="button" className="h-[49px] w-full px-2 text-left font-mono text-[10px] text-slate-500 hover:text-cyan-100" onClick={open}>{formatDate(customer.latestAt)}</button></td></tr>; })}</tbody></table></div>
        {filteredSupportCustomers.length === 0 && <p className="py-6 text-center text-sm font-light text-slate-500">{t('telegram.noSupportCustomers')}</p>}
        <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-cyan-400/12 pt-3"><button type="button" className={buttonClass} disabled={supportPage <= 1} onClick={() => setSupportPage((page) => Math.max(1, page - 1))}>{t('telegram.previousPage')}</button><span className="font-mono text-[11px] text-slate-500">{supportPage} / {supportPageCount}</span><button type="button" className={buttonClass} disabled={supportPage >= supportPageCount} onClick={() => setSupportPage((page) => Math.min(supportPageCount, page + 1))}>{t('telegram.nextPage')}</button></div>
      </section>}

      {activeTab === 'operations' && <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
        <section className={panelClass} aria-label={t('telegram.schedulesTitle')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.schedulesTitle')}</h3>
          <div className="mt-3 space-y-2">{schedules.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noSchedules')}</p>}{schedules.map((schedule) => <article key={schedule.schedule_id} className="flex flex-wrap items-center justify-between gap-3 rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div><p className="text-xs text-slate-300">{schedule.customer_email} · {schedule.operation_type}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{formatDate(schedule.execute_not_before)} · {schedule.status}</p></div>{schedule.status === 'scheduled' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void cancelSchedule(schedule)}>{t('common.cancel')}</button>}</article>)}</div>
        </section>
        <section className={panelClass} aria-label={t('telegram.driftTitle')}>
          <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.driftTitle')}</h3><p className="mt-1 text-xs text-slate-500">{t('telegram.driftHint')}</p></div><button type="button" className={buttonClass} disabled={mutating} onClick={() => void runDriftScan()}>{t('telegram.driftScan')}</button></div>
          <div className="mt-3 space-y-2">{driftFindings.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noDrift')}</p>}{driftFindings.map((finding) => <article key={finding.finding_id} className="rounded border border-amber-400/20 bg-[#0a0e1a] p-3"><p className="text-xs text-slate-300">{finding.kind} · {finding.node_name}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{finding.customer_email ?? finding.remote_email}</p><div className="mt-2 flex flex-wrap gap-2">{finding.kind === 'orphan_remote' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void resolveDrift(finding, true)}>{t('telegram.driftAdopt')}</button>}<button type="button" className={buttonClass} disabled={mutating} onClick={() => void resolveDrift(finding)}>{t('telegram.driftResolve')}</button></div></article>)}</div>
        </section>
      </div>}
    </div>
    {applicationNoteTooltip && createPortal(
      <div role="tooltip" className="pointer-events-none fixed z-[70] w-72 whitespace-pre-wrap rounded-[6px] border border-amber-300/25 bg-[#101827] p-2 text-[11px] font-normal leading-4 text-slate-200 shadow-xl" style={{ left: applicationNoteTooltip.left, top: applicationNoteTooltip.top }}>
        {applicationNoteTooltip.note}
      </div>,
      document.body,
    )}
    </>
  );
};
