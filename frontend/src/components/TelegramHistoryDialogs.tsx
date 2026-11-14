import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from './Toast';
import {
  adoptDriftFinding,
  clearTelegramDriftHistory,
  clearTelegramJobHistory,
  clearTelegramOperationHistory,
  dismissTelegramJob,
  DriftFinding,
  forgetTelegramMissingBindings,
  getTelegramHistoryClearCount,
  listTelegramMissingBindingNodes,
  listTelegramHistoryAudit,
  listTelegramHistoryBindings,
  listTelegramHistoryDrift,
  listTelegramHistoryOperations,
  listTelegramJobsPage,
  ProvisioningJob,
  retryCustomerOperation,
  TelegramHistoryAudit,
  TelegramHistoryBinding,
  TelegramHistoryOverview,
  CustomerOperation,
  reconcileTelegramJob,
  ignoreDriftFinding,
} from '../api/telegram';

type Section = 'jobs' | 'operations' | 'drift' | 'bindings' | 'audit';
type Props = {
  overview: TelegramHistoryOverview;
  canClear: boolean;
  mutating: boolean;
  setMutating: (value: boolean) => void;
  onChanged: () => Promise<void>;
};

const buttonClass = 'inline-flex h-8 items-center justify-center gap-2 rounded-[6px] border border-cyan-400/18 bg-[#0a0f19] px-2.5 text-[11px] font-medium uppercase tracking-[0.08em] text-slate-300 transition hover:border-cyan-300/55 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70 disabled:cursor-not-allowed disabled:opacity-45';
const primaryButtonClass = 'inline-flex h-8 items-center justify-center gap-2 rounded-[6px] border border-cyan-200/35 bg-cyan-300 px-2.5 text-[11px] font-medium uppercase tracking-[0.08em] text-[#06111f] transition hover:bg-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-100 disabled:cursor-not-allowed disabled:opacity-45';

const dateText = (value: string | null | undefined) => value ? new Date(value.replace(' ', 'T')).toLocaleString() : '—';

export const TelegramHistoryDialogs: React.FC<Props> = ({ overview, canClear, mutating, setMutating, onChanged }) => {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [section, setSection] = useState<Section | null>(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('all');
  const [nodeId, setNodeId] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const [jobs, setJobs] = useState<ProvisioningJob[]>([]);
  const [operations, setOperations] = useState<CustomerOperation[]>([]);
  const [drift, setDrift] = useState<DriftFinding[]>([]);
  const [nodeOptions, setNodeOptions] = useState<Array<{ node_id: number; node_name: string }>>([]);
  const [bindings, setBindings] = useState<TelegramHistoryBinding[]>([]);
  const [audit, setAudit] = useState<TelegramHistoryAudit[]>([]);
  const [total, setTotal] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);
  const [confirm, setConfirm] = useState<{ kind: 'jobs' | 'operations' | 'drift' | 'bindings'; count: number } | null>(null);
  const perPage = 15;

  const open = (next: Section) => { setSection(next); setPage(1); setStatus('all'); setNodeId(undefined); setConfirm(null); };
  useEffect(() => {
    if (!section) return;
    let cancelled = false;
    setLoading(true);
    const run = async () => {
      try {
        if (section === 'jobs') {
          const result = await listTelegramJobsPage(perPage, (page - 1) * perPage);
          if (!cancelled) { setJobs(result.items); setTotal(result.total); }
        } else if (section === 'operations') {
          const result = await listTelegramHistoryOperations(perPage, (page - 1) * perPage);
          if (!cancelled) { setOperations(result.items); setTotal(result.total); }
        } else if (section === 'drift') {
          const result = await listTelegramHistoryDrift(status, perPage, (page - 1) * perPage);
          const count = status === 'all' ? overview.drift.open + overview.drift.ignored + overview.drift.resolved + overview.drift.adopted : overview.drift[status as keyof TelegramHistoryOverview['drift']];
          if (!cancelled) { setDrift(result); setTotal(count ?? 0); }
        } else if (section === 'bindings') {
          const [result, nodes] = await Promise.all([listTelegramHistoryBindings(undefined, perPage, (page - 1) * perPage), listTelegramMissingBindingNodes()]);
          if (!cancelled) setNodeOptions(nodes);
          if (!cancelled) { setBindings(result.items); setTotal(result.total); }
        } else {
          const result = await listTelegramHistoryAudit(perPage, (page - 1) * perPage);
          if (!cancelled) { setAudit(result.items); setTotal(result.total); }
        }
      } catch { if (!cancelled) toast(t('telegram.actionFailed'), 'error'); }
      finally { if (!cancelled) setLoading(false); }
    };
    void run();
    return () => { cancelled = true; };
  }, [page, section, status, reloadToken, t, toast, overview.drift]);

  const pages = Math.max(1, Math.ceil(total / perPage));


  const runMutation = async (action: () => Promise<unknown>, successKey: string) => {
    setMutating(true);
    try { const result = await action(); toast(t(successKey, { count: typeof result === 'number' ? result : 0 }), 'success'); setConfirm(null); setReloadToken((value) => value + 1); await onChanged(); }
    catch { toast(t('telegram.actionFailed'), 'error'); }
    finally { setMutating(false); }
  };

  const clearSection = async () => {
    if (!section || section === 'audit' || !canClear) return;
    setMutating(true);
    try {
      const count = await getTelegramHistoryClearCount(section, section === 'bindings' ? nodeId : undefined);
      if (count <= 0) toast(t('telegram.historyClearEmpty'), 'info');
      else setConfirm({ kind: section, count });
    } catch { toast(t('telegram.actionFailed'), 'error'); }
    finally { setMutating(false); }
  };

  if (!section) return <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
    {([
      ['jobs', t('telegram.historyJobs'), overview.jobs.total, overview.jobs.terminal],
      ['operations', t('telegram.historyOperations'), overview.operations.total, overview.operations.needs_attention],
      ['drift', t('telegram.historyDrift'), overview.drift.open + overview.drift.ignored + overview.drift.resolved + overview.drift.adopted, overview.drift.open],
      ['bindings', t('telegram.historyMissing'), overview.missing_bindings.missing + overview.missing_bindings.conflict, overview.missing_bindings.missing],
      ['audit', t('telegram.historyAudit'), overview.audit.total, 0],
    ] as const).map(([key, label, count, attention]) => <button type="button" key={key} className="rounded border border-cyan-400/12 bg-[#0a0f19] px-3 py-3 text-left hover:border-cyan-300/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70" onClick={() => open(key)} aria-label={`${t('telegram.historyOpenSection')}: ${label}`}>
      <span className="block text-[12px] text-slate-400">{label}</span><span className="mt-1 block font-mono text-[20px] text-cyan-100">{count}</span><span className="text-[11px] text-amber-200">{attention > 0 ? `${attention} ${t('telegram.attentionItems')}` : t('telegram.historyClean')}</span>
    </button>)}
  </div>;

  const title = section === 'jobs' ? t('telegram.historyJobs') : section === 'operations' ? t('telegram.historyOperations') : section === 'drift' ? t('telegram.historyDrift') : section === 'bindings' ? t('telegram.historyMissing') : t('telegram.historyAudit');
  return <>
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#02050bd9] p-3 sm:p-5" onMouseDown={() => { if (!confirm && !mutating) setSection(null); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="telegram-history-dialog-title" className="flex max-h-[calc(100vh-1.5rem)] w-full max-w-4xl flex-col overflow-hidden rounded-[8px] border border-cyan-400/20 bg-[#0d131f] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-cyan-400/12 px-4 py-3"><div><p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">{t('telegram.historyTitle')}</p><h3 id="telegram-history-dialog-title" className="mt-1 text-[14px] font-medium text-[#e9f1f8]">{title}</h3></div><button type="button" className={buttonClass} onClick={() => setSection(null)}>{t('telegram.historyClose')}</button></div>
        <div className="flex flex-wrap items-center gap-2 border-b border-cyan-400/12 px-4 py-3">
          {section === 'drift' && <label className="flex items-center gap-2 text-[11px] text-slate-400">{t('telegram.historyFilterStatus')}<select className="rounded border border-cyan-400/20 bg-[#0a0f19] px-2 py-1.5 text-slate-200" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="all">{t('telegram.historyAllStatuses')}</option>{['open', 'ignored', 'resolved', 'adopted'].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>}
          {section === 'bindings' && <label className="flex items-center gap-2 text-[11px] text-slate-400">{t('telegram.historyForgetNode')}<select className="rounded border border-cyan-400/20 bg-[#0a0f19] px-2 py-1.5 text-slate-200" value={nodeId ?? ''} onChange={(event) => setNodeId(event.target.value ? Number(event.target.value) : undefined)}><option value="">{t('telegram.historyAllNodes')}</option>{nodeOptions.map(({ node_id, node_name }) => <option key={node_id} value={node_id}>{node_name}</option>)}</select></label>}
          {section !== 'audit' && <button type="button" className={`${buttonClass} ml-auto border-rose-400/25 text-rose-200`} disabled={!canClear || mutating} onClick={() => void clearSection()}>{section === 'bindings' ? t('telegram.historyForget') : t('telegram.historyClear')}</button>}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{loading && <p className="py-7 text-center text-[14px] font-light text-slate-500">{t('telegram.historyLoading')}</p>}{!loading && ((section === 'jobs' && jobs.length === 0) || (section === 'operations' && operations.length === 0) || (section === 'drift' && drift.length === 0) || (section === 'bindings' && bindings.length === 0) || (section === 'audit' && audit.length === 0)) && <p className="py-7 text-center text-[14px] font-light text-slate-500">{t('telegram.historyNoRecords')}</p>}
          <div className="space-y-2">{section === 'jobs' && jobs.map((job) => <article key={job.job_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div className="flex justify-between gap-2"><span className="truncate text-[13px] text-slate-200">{job.customer_email}</span><span className="font-mono text-[12px] text-slate-500">{job.status}</span></div><p className="mt-1 text-[12px] text-slate-500">{dateText(job.created_at)}</p>{['partial', 'failed'].includes(job.status) && <button type="button" className={`${buttonClass} mt-2`} disabled={mutating} onClick={() => void runMutation(() => reconcileTelegramJob(job), 'telegram.operationQueued')}>{t('telegram.historyRetry')}</button>}{['partial', 'failed'].includes(job.status) && <button type="button" className={`${buttonClass} ml-2 mt-2`} disabled={mutating} onClick={() => void runMutation(() => dismissTelegramJob(job), 'telegram.requestUpdated')}>{t('telegram.historyHide')}</button>}</article>)}
            {section === 'operations' && operations.map((operation) => <article key={operation.operation_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div className="flex justify-between gap-2"><span className="truncate text-[13px] text-slate-200">{operation.customer_email} · {operation.operation_type}</span><span className="font-mono text-[12px] text-slate-500">{operation.status}</span></div><p className="mt-1 text-[12px] text-slate-500">{dateText(operation.created_at)}</p>{['partial', 'failed'].includes(operation.status) && !operation.dismissed && <button type="button" className={`${buttonClass} mt-2`} disabled={mutating} onClick={() => void runMutation(() => retryCustomerOperation(operation), 'telegram.operationQueued')}>{t('telegram.historyRetry')}</button>}</article>)}
            {section === 'drift' && drift.map((finding) => <article key={finding.finding_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div className="flex justify-between gap-2"><span className="truncate text-[13px] text-slate-200">{finding.customer_email || finding.remote_email} · {finding.node_name}</span><span className="font-mono text-[12px] text-slate-500">{finding.status}</span></div><p className="mt-1 text-[12px] text-slate-500">{finding.kind}</p>{finding.status === 'open' && <><button type="button" className={`${buttonClass} mt-2`} disabled={mutating} onClick={() => void runMutation(() => ignoreDriftFinding(finding), 'telegram.requestUpdated')}>{t('telegram.historyHide')}</button>{finding.kind === 'orphan_remote' && <button type="button" className={`${buttonClass} ml-2 mt-2`} disabled={mutating} onClick={() => void runMutation(() => adoptDriftFinding(finding), 'telegram.requestUpdated')}>{t('telegram.historyAdopt')}</button>}</>}</article>)}
            {section === 'bindings' && bindings.map((binding) => <article key={binding.binding_id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div className="flex justify-between gap-2"><span className="truncate text-[13px] text-slate-200">{binding.customer_email} · {binding.node_name}</span><span className="font-mono text-[12px] text-slate-500">{binding.management_state}</span></div><p className="mt-1 text-[12px] text-slate-500">{binding.desired_enabled == null ? '—' : String(binding.desired_enabled)}</p></article>)}
            {section === 'audit' && audit.map((entry) => <article key={entry.id} className="rounded border border-cyan-500/15 bg-[#0a0e1a] p-3"><div className="flex justify-between gap-2"><span className="text-[13px] text-slate-200">{entry.event_type}</span><span className="font-mono text-[11px] text-slate-500">{dateText(entry.created_at)}</span></div><p className="mt-1 text-[12px] text-slate-500">{entry.entity_type} · {entry.entity_id} · {entry.actor_id || entry.actor_type}</p></article>)}</div>
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-cyan-400/12 px-4 py-3"><span className="font-mono text-[12px] text-slate-500">{t('telegram.historyPage', { page, pages })}</span><div className="flex gap-2"><button type="button" className={buttonClass} disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)}>{t('telegram.previousPage')}</button><button type="button" className={buttonClass} disabled={loading || page >= pages} onClick={() => setPage((value) => value + 1)}>{t('telegram.nextPage')}</button></div></div>
      </section>
    </div>
    {confirm && <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#02050be8] p-4" onMouseDown={() => { if (!mutating) setConfirm(null); }}><section role="dialog" aria-modal="true" aria-labelledby="telegram-history-clear-title" className="w-full max-w-md rounded-[8px] border border-rose-400/30 bg-[#0d131f] p-4 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}><h4 id="telegram-history-clear-title" className="text-[14px] font-medium text-slate-100">{confirm.kind === 'bindings' ? t('telegram.historyForget') : t('telegram.historyClear')}</h4><p className="mt-3 rounded border border-rose-400/20 bg-rose-400/[0.04] p-3 text-[13px] leading-5 text-rose-100">{confirm.kind === 'bindings' ? t('telegram.historyForgetConfirm', { count: confirm.count }) : t('telegram.historyClearConfirm', { count: confirm.count })}</p><div className="mt-4 flex justify-end gap-2"><button type="button" className={buttonClass} disabled={mutating} onClick={() => setConfirm(null)}>{t('common.cancel')}</button><button type="button" className={`${primaryButtonClass} bg-rose-300 hover:bg-rose-200`} disabled={mutating} onClick={() => { if (confirm.kind === 'jobs') void runMutation(clearTelegramJobHistory, 'telegram.historyClearDone'); else if (confirm.kind === 'operations') void runMutation(clearTelegramOperationHistory, 'telegram.historyClearDone'); else if (confirm.kind === 'drift') void runMutation(clearTelegramDriftHistory, 'telegram.historyClearDone'); else void runMutation(() => forgetTelegramMissingBindings(nodeId), 'telegram.historyForgottenDone'); }}>{t('common.confirm')}</button></div></section></div>}
  </>;
};

export default TelegramHistoryDialogs;
