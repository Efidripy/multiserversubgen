import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
  setCustomerTags,
  unblockTelegramIdentity,
} from '../api/telegram';

const shellClass = 'min-h-screen min-w-0 bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6';
const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]';
const inputClass = 'w-full rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/60';
const buttonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs font-medium uppercase tracking-[0.12em] text-slate-300 transition hover:border-cyan-300/50 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const primaryButtonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-cyan-300/25 bg-cyan-300 px-3 text-xs font-medium uppercase tracking-[0.12em] text-[#06111f] transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';

const formatDate = (value: string | null) => value ? new Date(value.replace(' ', 'T')).toLocaleString() : '—';
const formatBytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
};

export const TelegramAdmin: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [requests, setRequests] = useState<TelegramRequest[]>([]);
  const [blocked, setBlocked] = useState<BlockedIdentity[]>([]);
  const [customers, setCustomers] = useState<TelegramCustomer[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [nodes, setNodes] = useState<CustomerNode[]>([]);
  const [operations, setOperations] = useState<CustomerOperation[]>([]);
  const [traffic, setTraffic] = useState<CustomerTraffic | null>(null);
  const [tags, setTags] = useState<CustomerTag[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [timeline, setTimeline] = useState<CustomerTimelineEvent[]>([]);
  const [preview, setPreview] = useState<CustomerOperationPreview | null>(null);
  const [previewNodeId, setPreviewNodeId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [transport, setTransport] = useState<TelegramTransportStatus | null>(null);
  const [botConfiguration, setBotConfiguration] = useState<TelegramBotConfigurationStatus | null>(null);
  const [botToken, setBotToken] = useState('');
  const [jobs, setJobs] = useState<ProvisioningJob[]>([]);
  const [appeals, setAppeals] = useState<TelegramAppeal[]>([]);
  const [openSupportRequests, setOpenSupportRequests] = useState<TelegramSupportRequest[]>([]);
  const [supportHistory, setSupportHistory] = useState<TelegramSupportRequest[]>([]);
  const [supportReply, setSupportReply] = useState<{ request: TelegramSupportRequest; body: string } | null>(null);
  const [dashboard, setDashboard] = useState<Record<string, number> | null>(null);
  const [schedules, setSchedules] = useState<LifecycleSchedule[]>([]);
  const [driftFindings, setDriftFindings] = useState<DriftFinding[]>([]);
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<number[]>([]);
  const [bulkPreview, setBulkPreview] = useState<BulkLifecyclePreview | null>(null);
  const [scheduleAt, setScheduleAt] = useState('');
  const [approval, setApproval] = useState<{ request: TelegramRequest; mode: 'new' | 'existing'; email: string; candidate?: ExistingDiscoveryCandidate } | null>(null);
  const selectedCustomer = useMemo(
    () => customers.find((item) => item.customer_id === selectedCustomerId) ?? null,
    [customers, selectedCustomerId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRequests, nextCustomers, nextBlocked, nextTransport, nextBotConfiguration, nextJobs, nextAppeals, nextOpenSupport, nextSupportHistory, nextDashboard, nextSchedules, nextDrift] = await Promise.all([
        listTelegramRequests(), listTelegramCustomers(search), listBlockedTelegramIdentities(), getTelegramTransport(), getTelegramBotConfiguration(), listTelegramJobs(), listTelegramAppeals(), listTelegramSupportRequests('open'), listTelegramSupportRequests('resolved'), getTelegramDashboard(), listLifecycleSchedules(), listDriftFindings(),
      ]);
      setRequests(nextRequests);
      setCustomers(nextCustomers);
      setBlocked(nextBlocked);
      setTransport(nextTransport);
      setBotConfiguration(nextBotConfiguration);
      setJobs(nextJobs);
      setAppeals(nextAppeals);
      setOpenSupportRequests(nextOpenSupport);
      setSupportHistory(nextSupportHistory);
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

  const selectCustomer = useCallback(async (customer: TelegramCustomer) => {
    setSelectedCustomerId(customer.customer_id);
    setPreview(null);
    setPreviewNodeId(null);
    try {
      const [nextNodes, nextOperations, nextTraffic, nextTags, nextTimeline] = await Promise.all([
        getCustomerNodes(customer.customer_id),
        getCustomerOperations(customer.customer_id),
        getCustomerTraffic(customer.customer_id),
        getCustomerTags(customer.customer_id),
        getCustomerTimeline(customer.customer_id),
      ]);
      setNodes(nextNodes);
      setOperations(nextOperations);
      setTraffic(nextTraffic);
      setTags(nextTags);
      setTagInput(nextTags.map((tag) => tag.tag).join(', '));
      setTimeline(nextTimeline);
    } catch {
      toast(t('telegram.detailsFailed'), 'error');
    }
  }, [t, toast]);

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

  const addNode = async (node: CustomerNode) => {
    if (!selectedCustomer || !window.confirm(t('telegram.addNodeConfirm', { node: node.node_name }))) return;
    setMutating(true);
    try {
      await addCustomerNode(selectedCustomer, node.node_id);
      toast(t('telegram.nodeOperationQueued'), 'success');
      await load();
      await selectCustomer(selectedCustomer);
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
      await load();
      if (selectedCustomer) await selectCustomer(selectedCustomer);
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

  const selectedTitle = useMemo(() => selectedCustomer?.email_display ?? t('telegram.selectCustomer'), [selectedCustomer, t]);

  return (
    <div className={shellClass}>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-[0.16em] text-cyan-300"><UIIcon name="bell" size={16} />{t('telegram.title')}</h2>
          <p className="mt-1 text-xs font-light text-slate-500">{t('telegram.hint')}</p>
        </div>
        <button type="button" className={buttonClass} onClick={() => void load()} disabled={loading || mutating}><UIIcon name="refresh" size={14} />{t('common.refresh')}</button>
      </div>

      {dashboard && <section className={`${panelClass} mb-4`} aria-label={t('telegram.dashboardTitle')}>
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.dashboardTitle')}</h3>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {[
            ['pending_requests', 'telegram.dashboardPending'], ['active_customers', 'telegram.dashboardActive'], ['suspended_customers', 'telegram.dashboardSuspended'],
            ['provisioning_attention', 'telegram.dashboardProvisioning'], ['lifecycle_attention', 'telegram.dashboardLifecycle'], ['open_drift_findings', 'telegram.dashboardDrift'],
          ].map(([key, label]) => <div key={key} className="rounded border border-cyan-500/15 bg-[#0a0e1a] px-3 py-2"><span className="block font-mono text-lg text-cyan-200">{dashboard[key] ?? 0}</span><span className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{t(label)}</span></div>)}
        </div>
      </section>}

      <section className={`${panelClass} mb-4`} aria-label={t('telegram.botTokenTitle')}>
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
      </section>

      <section className={`${panelClass} mb-4`} aria-label={t('telegram.transportTitle')}>
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
      </section>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(290px,0.9fr)_minmax(0,1.3fr)]">
        <section className={panelClass} aria-label={t('telegram.requests')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.requests')}</h3>
          <div className="mt-3 space-y-3">
            {requests.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noRequests')}</p>}
            {requests.map((request) => (
              <article key={request.telegram_user_id} className="rounded-lg border border-cyan-500/15 bg-[#0a0e1a] p-3">
                <div className="flex items-center justify-between gap-2"><span className="truncate text-sm text-slate-200">{request.username ? `@${request.username}` : request.first_name || t('telegram.unknownUser')}</span><span className="font-mono text-[10px] text-slate-500">#{request.telegram_user_id}</span></div>
                <p className="mt-1 text-[11px] text-slate-500">{formatDate(request.requested_at)}</p>
                {request.introduction_text && <p className="mt-2 whitespace-pre-wrap text-xs font-light text-slate-400">{request.introduction_text}</p>}
                {approval?.request.telegram_user_id === request.telegram_user_id ? (
                  <div className="mt-3 rounded border border-amber-400/25 bg-amber-400/5 p-3">
                    <p className="text-xs text-amber-100">{approval.mode === 'new' ? t('telegram.approvalNewTitle') : t('telegram.approvalExistingTitle')}</p>
                    <input className={`${inputClass} mt-2`} value={approval.email} onChange={(event) => setApproval((current) => current ? { ...current, email: event.target.value, candidate: undefined } : current)} aria-label={t('telegram.emailForRequest')} />
                    {approval.mode === 'new' ? (
                      <div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} onClick={() => void confirmNew()} disabled={mutating}>{t('common.confirm')}</button><button type="button" className={buttonClass} onClick={() => setApproval(null)}>{t('common.cancel')}</button></div>
                    ) : (
                      <>
                        <p className="mt-2 text-xs font-light text-slate-500">{t('telegram.existingDiscoveryHint')}</p>
                        {approval.candidate && <p className="mt-2 text-xs text-emerald-200">{t('telegram.existingFound', { count: approval.candidate.binding_count, nodes: approval.candidate.node_names.join(', ') })}</p>}
                        <div className="mt-2 flex flex-wrap gap-2"><button type="button" className={buttonClass} onClick={() => void discoverExisting()} disabled={mutating}>{t('telegram.existingCheck')}</button>{approval.candidate && <button type="button" className={primaryButtonClass} onClick={() => void confirmExisting()} disabled={mutating}>✓ {t('telegram.existingBind')}</button>}<button type="button" className={buttonClass} onClick={() => setApproval(null)}>{t('common.cancel')}</button></div>
                      </>
                    )}
                  </div>
                ) : <div className="mt-3 grid grid-cols-2 gap-2"><button type="button" className={primaryButtonClass} onClick={() => setApproval({ request, mode: 'new', email: request.suggested_email })} disabled={mutating}>{t('telegram.createNew')}</button><button type="button" className={buttonClass} onClick={() => setApproval({ request, mode: 'existing', email: '' })} disabled={mutating}>{t('telegram.bindExisting')}</button></div>}
                <div className="mt-2 grid grid-cols-2 gap-2"><button type="button" className={buttonClass} onClick={() => void decideRequest(request, 'reject')} disabled={mutating}>{t('telegram.reject')}</button><button type="button" className={`${buttonClass} border-rose-400/25 text-rose-200`} onClick={() => void decideRequest(request, 'block')} disabled={mutating}>{t('telegram.block')}</button></div>
              </article>
            ))}
          </div>
        </section>

        <section className={panelClass} aria-label={t('telegram.blocked')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.blocked')}</h3><div className="mt-3 space-y-2">{blocked.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noBlocked')}</p>}{blocked.map((identity) => <div key={identity.telegram_user_id} className="flex items-center justify-between gap-3 rounded border border-rose-400/15 bg-[#0a0e1a] p-3"><span className="truncate text-sm text-slate-300">{identity.username ? `@${identity.username}` : identity.first_name || `#${identity.telegram_user_id}`}</span><button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await unblockTelegramIdentity(identity); toast(t('telegram.requestUpdated'), 'success'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.unblock')}</button></div>)}</div>
        </section>

        <section className={panelClass} aria-label={t('telegram.customers')}>
          <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.customers')}</h3><input className={`${inputClass} max-w-xs`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('common.search')} /></div>
          <div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-[minmax(200px,0.8fr)_minmax(0,1.2fr)]">
            <div className="max-h-[520px] space-y-2 overflow-auto pr-1">
              {customers.map((customer) => <article key={customer.customer_id} className={`flex w-full items-stretch rounded-lg border transition ${selectedCustomer?.customer_id === customer.customer_id ? 'border-cyan-300/55 bg-cyan-400/10' : 'border-cyan-500/15 bg-[#0a0e1a] hover:border-cyan-300/35'}`}>
                <label className="flex shrink-0 cursor-pointer items-center px-3" title={t('telegram.bulkSelectCustomer', { email: customer.email_display })}><input type="checkbox" checked={selectedCustomerIds.includes(customer.customer_id)} onChange={(event) => setSelectedCustomerIds((current) => event.target.checked ? [...current, customer.customer_id] : current.filter((customerId) => customerId !== customer.customer_id))} /></label>
                <button type="button" className="min-w-0 flex-1 p-3 text-left" onClick={() => void selectCustomer(customer)}><span className="block truncate text-sm text-slate-200">{customer.email_display}</span><span className="mt-1 block text-[10px] uppercase tracking-[0.12em] text-slate-500">{customer.status}</span></button>
              </article>)}
              {customers.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noCustomers')}</p>}
            </div>
            <div className="min-w-0 rounded-lg border border-cyan-500/15 bg-[#0a0e1a] p-3">
              <h4 className="truncate text-sm text-slate-200">{selectedTitle}</h4>
              {!selectedCustomer && <p className="mt-2 text-sm font-light text-slate-500">{t('telegram.selectCustomer')}</p>}
              {selectedCustomer && <>
                <p className="mt-2 text-xs font-light text-slate-400">{t('telegram.lifetimeTraffic')}: <span className="font-mono text-cyan-200">{formatBytes(traffic?.lifetime_bytes ?? 0)}</span></p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(['suspend', 'resume', 'delete'] as const).map((operationType) => <button key={operationType} type="button" className={operationType === 'delete' ? `${buttonClass} border-rose-400/25 text-rose-200 hover:text-rose-100` : buttonClass} onClick={() => void makePreview(operationType)} disabled={mutating}>{t(`telegram.${operationType}`)}</button>)}
                </div>
                {preview && <div className="mt-3 rounded-lg border border-amber-400/25 bg-amber-400/5 p-3"><p className="text-xs text-amber-100">{t('telegram.previewText', { operation: t(`telegram.${preview.operation_type}`, preview.operation_type), count: preview.targets.length })}</p>{preview.blocked_binding_ids.length > 0 && <p className="mt-1 text-xs text-rose-200">{t('telegram.previewBlocked')}</p>}<div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} disabled={mutating || preview.blocked_binding_ids.length > 0} onClick={() => void confirmPreview()}>{t('common.confirm')}</button><button type="button" className={buttonClass} onClick={() => { setPreview(null); setPreviewNodeId(null); }}>{t('common.cancel')}</button></div></div>}
                {preview && previewNodeId === null && ['suspend', 'delete'].includes(preview.operation_type) && <div className="mt-2 flex flex-wrap items-end gap-2 rounded border border-cyan-500/15 p-2"><label className="min-w-[220px] flex-1 text-[10px] uppercase tracking-[0.12em] text-slate-500">{t('telegram.scheduleAt')}<input className={`${inputClass} mt-1`} type="datetime-local" value={scheduleAt} onChange={(event) => setScheduleAt(event.target.value)} /></label><button type="button" className={buttonClass} disabled={mutating || !scheduleAt || preview.blocked_binding_ids.length > 0} onClick={() => void schedulePreview()}>{t('telegram.scheduleAction')}</button></div>}
                <div className="mt-4 rounded border border-cyan-500/10 p-2">
                  <div className="flex flex-wrap items-center justify-between gap-2"><h5 className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.tagsTitle')}</h5><button type="button" className={buttonClass} disabled={mutating} onClick={() => void saveTags()}>{t('common.save')}</button></div>
                  <input className={`${inputClass} mt-2`} value={tagInput} onChange={(event) => setTagInput(event.target.value)} placeholder={t('telegram.tagsPlaceholder')} />
                  {tags.length > 0 && <p className="mt-1 text-[11px] text-slate-500">{tags.map((tag) => tag.tag).join(' · ')}</p>}
                </div>
                <h5 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.nodes')}</h5>
                <div className="mt-2 space-y-1">{nodes.map((node) => <div key={node.node_id} className="flex items-center justify-between gap-2 rounded border border-cyan-500/10 px-2 py-1.5 text-xs"><span className="truncate text-slate-300">{node.node_name}</span><div className="flex shrink-0 items-center gap-2"><span className="font-mono text-[10px] text-slate-500">{node.state}</span>{node.state === 'available_to_add' && <button type="button" className={buttonClass} disabled={mutating || selectedCustomer.status !== 'active'} onClick={() => void addNode(node)}>{t('telegram.addNode')}</button>}{node.state === 'active' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void makeNodePreview(node, 'suspend_node')}>{t('telegram.suspendNode')}</button>}{node.state === 'suspended' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void makeNodePreview(node, 'resume_node')}>{t('telegram.resumeNode')}</button>}</div></div>)}</div>
                <h5 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.operations')}</h5>
                <div className="mt-2 space-y-2">{operations.map((operation) => <div key={operation.operation_id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-cyan-500/15 px-2 py-2 text-xs"><span className="text-slate-300">{operation.operation_type} · {operation.status}</span>{operation.status === 'partial' && <button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await retryCustomerOperation(operation); toast(t('telegram.operationQueued'), 'success'); await selectCustomer(selectedCustomer); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.reconcile')}</button>}</div>)}</div>
                <h5 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.timelineTitle')}</h5>
                <div className="mt-2 max-h-44 space-y-1 overflow-auto">{timeline.length === 0 ? <p className="text-xs text-slate-500">{t('telegram.timelineEmpty')}</p> : timeline.map((event, index) => <div key={`${event.entity_type}-${event.entity_id}-${event.created_at}-${index}`} className="flex flex-wrap justify-between gap-2 text-[11px] text-slate-400"><span>{event.event_type} · {event.status ?? '—'}</span><span className="font-mono text-slate-500">{formatDate(event.created_at)}</span></div>)}</div>
              </>}
            </div>
          </div>
          <div className="mt-4 rounded-lg border border-cyan-500/15 bg-[#0a0e1a] p-3">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.bulkTitle')}</h4><p className="mt-1 text-xs text-slate-500">{t('telegram.bulkHint')}</p></div><span className="font-mono text-xs text-cyan-200">{t('telegram.bulkSelected', { count: selectedCustomerIds.length })}</span></div>
            <div className="mt-3 flex flex-wrap gap-2"><button type="button" className={buttonClass} disabled={mutating || selectedCustomerIds.length === 0} onClick={() => void makeBulkPreview('suspend')}>{t('telegram.suspend')}</button><button type="button" className={buttonClass} disabled={mutating || selectedCustomerIds.length === 0} onClick={() => void makeBulkPreview('resume')}>{t('telegram.resume')}</button></div>
            {bulkPreview && <div className="mt-3 rounded border border-amber-400/25 bg-amber-400/5 p-3"><p className="text-xs text-amber-100">{t('telegram.bulkPreviewText', { operation: t(`telegram.${bulkPreview.operation_type}`), count: bulkPreview.items.length })}</p>{bulkPreview.items.some((item) => item.blocked_binding_ids.length > 0) && <p className="mt-1 text-xs text-rose-200">{t('telegram.previewBlocked')}</p>}<div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} disabled={mutating || bulkPreview.items.some((item) => item.blocked_binding_ids.length > 0)} onClick={() => void confirmBulkPreview()}>{t('common.confirm')}</button><button type="button" className={buttonClass} onClick={() => setBulkPreview(null)}>{t('common.cancel')}</button></div></div>}
          </div>
        </section>
      </div>

      <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
        <section className={panelClass} aria-label={t('telegram.jobsTitle')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.jobsTitle')}</h3>
          <div className="mt-3 space-y-2">{jobs.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noJobs')}</p>}{jobs.map((job) => <article key={job.job_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="truncate text-xs text-slate-200">{job.customer_email}</span><span className="font-mono text-[10px] text-slate-500">{job.status}</span></div><p className="mt-1 text-[11px] text-slate-500">{t('telegram.nodesReady', { ready: job.attempts.filter((attempt) => attempt.status === 'succeeded').length, total: job.attempts.length })}</p>{job.attempts.some((attempt) => ['partial', 'failed', 'ambiguous', 'blocked'].includes(attempt.status)) && <button type="button" className={`${buttonClass} mt-2`} disabled={mutating} onClick={async () => { setMutating(true); try { await reconcileTelegramJob(job); toast(t('telegram.operationQueued'), 'success'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.reconcile')}</button>}</article>)}</div>
        </section>
        <section className={panelClass} aria-label={t('telegram.appealsTitle')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.appealsTitle')}</h3>
          <div className="mt-3 space-y-2">{appeals.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noAppeals')}</p>}{appeals.map((appeal) => <article key={appeal.appeal_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><span className="block truncate text-xs text-slate-200">{appeal.email_display}</span><p className="mt-2 whitespace-pre-wrap text-xs text-slate-400">{appeal.body}</p><div className="mt-2 flex gap-2"><button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await resolveTelegramAppeal(appeal, 'handled'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.closeAppeal')}</button><button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await resolveTelegramAppeal(appeal, 'rejected'); await load(); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.reject')}</button></div></article>)}</div>
        </section>
      </div>

      <section className={`${panelClass} mt-4`} aria-label={t('telegram.supportTitle')}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.supportTitle')}</h3>
            <p className="mt-1 text-xs text-slate-500">{t('telegram.supportHint')}</p>
          </div>
          <span className="font-mono text-xs text-amber-200">{t('telegram.supportOpenCount', { count: openSupportRequests.length })}</span>
        </div>
        <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
          <div className="min-w-0">
            <h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-amber-200">{t('telegram.supportOpenTitle')}</h4>
            <div className="mt-2 space-y-2">
              {openSupportRequests.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noOpenSupport')}</p>}
              {openSupportRequests.map((request) => <article key={request.support_request_id} className="rounded border border-amber-400/20 bg-[#0a0e1a] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="truncate text-xs text-slate-200">{request.email_display}</span><span className="font-mono text-[10px] text-slate-500">#{request.telegram_user_id}</span></div>
                <p className="mt-1 text-[11px] text-amber-100">{t(`telegram.supportCategory.${request.category}`)}</p>
                <p className="mt-2 whitespace-pre-wrap text-xs text-slate-400">{request.body}</p>
                <p className="mt-2 text-[10px] text-slate-600">{formatDate(request.created_at)}</p>
                {supportReply?.request.support_request_id === request.support_request_id ? <div className="mt-3 rounded border border-cyan-500/20 p-2">
                  <label className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{t('telegram.supportReplyLabel')}<textarea className={`${inputClass} mt-1 min-h-20 resize-y`} maxLength={1000} value={supportReply.body} onChange={(event) => setSupportReply((current) => current ? { ...current, body: event.target.value } : current)} /></label>
                  <div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} disabled={mutating || !supportReply.body.trim()} onClick={() => void submitSupportReply()}>{t('telegram.supportSendReply')}</button><button type="button" className={buttonClass} disabled={mutating} onClick={() => setSupportReply(null)}>{t('common.cancel')}</button></div>
                </div> : <button type="button" className={`${buttonClass} mt-3`} disabled={mutating} onClick={() => setSupportReply({ request, body: '' })}>{t('telegram.supportReply')}</button>}
              </article>)}
            </div>
          </div>
          <div className="min-w-0 border-t border-cyan-500/15 pt-4 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0">
            <h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.supportHistoryTitle')}</h4>
            <div className="mt-2 max-h-[430px] space-y-2 overflow-auto pr-1">
              {supportHistory.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noSupportHistory')}</p>}
              {supportHistory.map((request) => <article key={request.support_request_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="truncate text-xs text-slate-300">{request.email_display}</span><span className="font-mono text-[10px] text-slate-500">{formatDate(request.updated_at)}</span></div>
                <p className="mt-1 text-[11px] text-slate-500">{t(`telegram.supportCategory.${request.category}`)}</p>
                <p className="mt-2 whitespace-pre-wrap text-xs text-slate-400">{request.body}</p>
                <p className="mt-3 text-[10px] font-medium uppercase tracking-[0.12em] text-cyan-200">{t('telegram.supportReplyLabel')}</p>
                <p className="mt-1 whitespace-pre-wrap text-xs text-slate-300">{request.admin_response || t('telegram.supportNoReply')}</p>
              </article>)}
            </div>
          </div>
        </div>
      </section>

      <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
        <section className={panelClass} aria-label={t('telegram.schedulesTitle')}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.schedulesTitle')}</h3>
          <div className="mt-3 space-y-2">{schedules.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noSchedules')}</p>}{schedules.map((schedule) => <article key={schedule.schedule_id} className="flex flex-wrap items-center justify-between gap-3 rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div><p className="text-xs text-slate-300">{schedule.customer_email} · {schedule.operation_type}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{formatDate(schedule.execute_not_before)} · {schedule.status}</p></div>{schedule.status === 'scheduled' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void cancelSchedule(schedule)}>{t('common.cancel')}</button>}</article>)}</div>
        </section>
        <section className={panelClass} aria-label={t('telegram.driftTitle')}>
          <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.driftTitle')}</h3><p className="mt-1 text-xs text-slate-500">{t('telegram.driftHint')}</p></div><button type="button" className={buttonClass} disabled={mutating} onClick={() => void runDriftScan()}>{t('telegram.driftScan')}</button></div>
          <div className="mt-3 space-y-2">{driftFindings.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noDrift')}</p>}{driftFindings.map((finding) => <article key={finding.finding_id} className="rounded border border-amber-400/20 bg-[#0a0e1a] p-3"><p className="text-xs text-slate-300">{finding.kind} · {finding.node_name}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{finding.customer_email ?? finding.remote_email}</p><div className="mt-2 flex flex-wrap gap-2">{finding.kind === 'orphan_remote' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void resolveDrift(finding, true)}>{t('telegram.driftAdopt')}</button>}<button type="button" className={buttonClass} disabled={mutating} onClick={() => void resolveDrift(finding)}>{t('telegram.driftResolve')}</button></div></article>)}</div>
        </section>
      </div>
    </div>
  );
};
