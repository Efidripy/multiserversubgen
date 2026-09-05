import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from './Toast';
import { UIIcon } from './UIIcon';
import {
  approveTelegramRequest,
  addCustomerNode,
  CustomerNode,
  CustomerOperation,
  CustomerOperationPreview,
  getCustomerNodes,
  getCustomerOperations,
  listTelegramCustomers,
  listTelegramRequests,
  previewCustomerOperation,
  previewCustomerNodeOperation,
  queueCustomerOperation,
  queueCustomerNodeOperation,
  retryCustomerOperation,
  TelegramCustomer,
  TelegramRequest,
} from '../api/telegram';

const shellClass = 'min-h-screen min-w-0 bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6';
const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]';
const inputClass = 'w-full rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/60';
const buttonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs font-medium uppercase tracking-[0.12em] text-slate-300 transition hover:border-cyan-300/50 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const primaryButtonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-cyan-300/25 bg-cyan-300 px-3 text-xs font-medium uppercase tracking-[0.12em] text-[#06111f] transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';

const formatDate = (value: string | null) => value ? new Date(value.replace(' ', 'T')).toLocaleString() : '—';

export const TelegramAdmin: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [requests, setRequests] = useState<TelegramRequest[]>([]);
  const [customers, setCustomers] = useState<TelegramCustomer[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [nodes, setNodes] = useState<CustomerNode[]>([]);
  const [operations, setOperations] = useState<CustomerOperation[]>([]);
  const [preview, setPreview] = useState<CustomerOperationPreview | null>(null);
  const [previewNodeId, setPreviewNodeId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [emailByRequest, setEmailByRequest] = useState<Record<number, string>>({});
  const selectedCustomer = useMemo(
    () => customers.find((item) => item.customer_id === selectedCustomerId) ?? null,
    [customers, selectedCustomerId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRequests, nextCustomers] = await Promise.all([listTelegramRequests(), listTelegramCustomers(search)]);
      setRequests(nextRequests);
      setCustomers(nextCustomers);
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
      const [nextNodes, nextOperations] = await Promise.all([
        getCustomerNodes(customer.customer_id),
        getCustomerOperations(customer.customer_id),
      ]);
      setNodes(nextNodes);
      setOperations(nextOperations);
    } catch {
      toast(t('telegram.detailsFailed'), 'error');
    }
  }, [t, toast]);

  const approve = async (request: TelegramRequest) => {
    setMutating(true);
    try {
      await approveTelegramRequest(request, emailByRequest[request.telegram_user_id] ?? request.suggested_email);
      toast(t('telegram.approvalQueued'), 'success');
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
                <input className={`${inputClass} mt-3`} value={emailByRequest[request.telegram_user_id] ?? request.suggested_email} onChange={(event) => setEmailByRequest((state) => ({ ...state, [request.telegram_user_id]: event.target.value }))} aria-label={t('telegram.emailForRequest')} />
                <button type="button" className={`${primaryButtonClass} mt-2 w-full`} onClick={() => void approve(request)} disabled={mutating}><UIIcon name="check" size={14} />{t('telegram.approve')}</button>
              </article>
            ))}
          </div>
        </section>

        <section className={panelClass} aria-label={t('telegram.customers')}>
          <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('telegram.customers')}</h3><input className={`${inputClass} max-w-xs`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('common.search')} /></div>
          <div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-[minmax(200px,0.8fr)_minmax(0,1.2fr)]">
            <div className="max-h-[520px] space-y-2 overflow-auto pr-1">
              {customers.map((customer) => <button key={customer.customer_id} type="button" className={`block w-full rounded-lg border p-3 text-left transition ${selectedCustomer?.customer_id === customer.customer_id ? 'border-cyan-300/55 bg-cyan-400/10' : 'border-cyan-500/15 bg-[#0a0e1a] hover:border-cyan-300/35'}`} onClick={() => void selectCustomer(customer)}><span className="block truncate text-sm text-slate-200">{customer.email_display}</span><span className="mt-1 block text-[10px] uppercase tracking-[0.12em] text-slate-500">{customer.status}</span></button>)}
              {customers.length === 0 && <p className="text-sm font-light text-slate-500">{t('telegram.noCustomers')}</p>}
            </div>
            <div className="min-w-0 rounded-lg border border-cyan-500/15 bg-[#0a0e1a] p-3">
              <h4 className="truncate text-sm text-slate-200">{selectedTitle}</h4>
              {!selectedCustomer && <p className="mt-2 text-sm font-light text-slate-500">{t('telegram.selectCustomer')}</p>}
              {selectedCustomer && <>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(['suspend', 'resume', 'delete'] as const).map((operationType) => <button key={operationType} type="button" className={operationType === 'delete' ? `${buttonClass} border-rose-400/25 text-rose-200 hover:text-rose-100` : buttonClass} onClick={() => void makePreview(operationType)} disabled={mutating}>{t(`telegram.${operationType}`)}</button>)}
                </div>
                {preview && <div className="mt-3 rounded-lg border border-amber-400/25 bg-amber-400/5 p-3"><p className="text-xs text-amber-100">{t('telegram.previewText', { operation: t(`telegram.${preview.operation_type}`, preview.operation_type), count: preview.targets.length })}</p>{preview.blocked_binding_ids.length > 0 && <p className="mt-1 text-xs text-rose-200">{t('telegram.previewBlocked')}</p>}<div className="mt-2 flex gap-2"><button type="button" className={primaryButtonClass} disabled={mutating || preview.blocked_binding_ids.length > 0} onClick={() => void confirmPreview()}>{t('common.confirm')}</button><button type="button" className={buttonClass} onClick={() => { setPreview(null); setPreviewNodeId(null); }}>{t('common.cancel')}</button></div></div>}
                <h5 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.nodes')}</h5>
                <div className="mt-2 space-y-1">{nodes.map((node) => <div key={node.node_id} className="flex items-center justify-between gap-2 rounded border border-cyan-500/10 px-2 py-1.5 text-xs"><span className="truncate text-slate-300">{node.node_name}</span><div className="flex shrink-0 items-center gap-2"><span className="font-mono text-[10px] text-slate-500">{node.state}</span>{node.state === 'available_to_add' && <button type="button" className={buttonClass} disabled={mutating || selectedCustomer.status !== 'active'} onClick={() => void addNode(node)}>{t('telegram.addNode')}</button>}{node.state === 'active' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void makeNodePreview(node, 'suspend_node')}>{t('telegram.suspendNode')}</button>}{node.state === 'suspended' && <button type="button" className={buttonClass} disabled={mutating} onClick={() => void makeNodePreview(node, 'resume_node')}>{t('telegram.resumeNode')}</button>}</div></div>)}</div>
                <h5 className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{t('telegram.operations')}</h5>
                <div className="mt-2 space-y-2">{operations.map((operation) => <div key={operation.operation_id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-cyan-500/15 px-2 py-2 text-xs"><span className="text-slate-300">{operation.operation_type} · {operation.status}</span>{operation.status === 'partial' && <button type="button" className={buttonClass} disabled={mutating} onClick={async () => { setMutating(true); try { await retryCustomerOperation(operation); toast(t('telegram.operationQueued'), 'success'); await selectCustomer(selectedCustomer); } catch { toast(t('telegram.actionFailed'), 'error'); } finally { setMutating(false); } }}>{t('telegram.reconcile')}</button>}</div>)}</div>
              </>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
