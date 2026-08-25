import React, { useEffect, useRef, useState } from 'react';
import { useToast } from './Toast';
import {
  downloadAllBackups as downloadAllBackupsBlob,
  downloadNodeBackup,
  importNodeBackup,
  sendNodeBackupToTelegram,
} from '../api/backup';
import { listNodes, type NodeRecord } from '../api/nodes';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';
import { useTranslation } from 'react-i18next';

type Node = NodeRecord;

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const shellClass = 'min-h-screen min-w-0 overflow-hidden bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6';
const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]';
const titleClass = 'text-xs font-medium uppercase tracking-[0.14em] text-slate-300';
const hintClass = 'mt-1 text-xs font-light leading-5 text-slate-500';
const metricClass = 'font-mono tabular-nums whitespace-nowrap';
const primaryButtonClass = 'inline-flex h-10 min-w-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/25 bg-gradient-to-r from-cyan-400 to-emerald-300 px-5 text-xs font-medium uppercase tracking-[0.14em] text-[#06111f] shadow-[0_14px_38px_rgba(34,211,238,0.18)] transition hover:from-cyan-300 hover:to-emerald-200 disabled:cursor-not-allowed disabled:opacity-45';
const secondaryButtonClass = 'inline-flex h-10 min-w-0 items-center justify-center gap-2 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 text-xs font-medium uppercase tracking-[0.14em] text-slate-300 transition hover:border-cyan-300/40 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const actionButtonClass = 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] text-slate-300 transition hover:border-cyan-300/50 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const inputClass = 'block w-full min-w-0 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-xs font-light text-slate-100 outline-none file:mr-3 file:rounded-md file:border file:border-cyan-500/20 file:bg-[#0f1420] file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-slate-200 focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10';
const metaLabelClass = 'text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500';
const metaValueClass = 'mt-1 block min-w-0 truncate text-xs font-light text-slate-200';

const isTelegramDeliverySuccess = (result: unknown): boolean => (
  Boolean(result && typeof result === 'object' && (result as { success?: unknown }).success === true)
);

/**
 * A panel DB export is the complete backup body, not a lightweight inventory
 * record. Keep it out of the cold path: list configured nodes first and only
 * request bytes after an explicit operator action.
 */
export const BackupManager: React.FC = () => {
  const { toast } = useToast();
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [nodesLoading, setNodesLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [backupProgress, setBackupProgress] = useState<Record<number, 'downloading' | 'success' | 'error'>>({});
  const [selectedNode, setSelectedNode] = useState<number | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const nodesRequestIdRef = useRef(0);
  const nodesAbortRef = useRef<AbortController | null>(null);

  const nodeAddress = (node: Node) => {
    if (node.ip || node.port) return `${node.ip || '-'}:${node.port || '-'}`;
    return node.url || node.panel_url || '-';
  };

  const loadNodes = async () => {
    nodesAbortRef.current?.abort();
    const controller = new AbortController();
    nodesAbortRef.current = controller;
    const requestId = ++nodesRequestIdRef.current;
    setNodesLoading(true);
    try {
      const nextNodes = await listNodes({ signal: controller.signal });
      if (controller.signal.aborted || requestId !== nodesRequestIdRef.current) return;
      setNodes(nextNodes);
    } catch (err: any) {
      if (controller.signal.aborted || requestId !== nodesRequestIdRef.current
        || err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError' || err?.message === 'canceled') return;
      console.error('Failed to load nodes:', err);
      setNodes([]);
      setError(t('backup.loadNodesFailed'));
    } finally {
      if (requestId === nodesRequestIdRef.current && !controller.signal.aborted) {
        setNodesLoading(false);
        nodesAbortRef.current = null;
      }
    }
  };

  useEffect(() => {
    void loadNodes();
    return () => {
      nodesAbortRef.current?.abort();
      nodesAbortRef.current = null;
    };
  }, []);

  const clearProgressSoon = (nodeId: number) => {
    window.setTimeout(() => {
      setBackupProgress((previous) => {
        const next = { ...previous };
        delete next[nodeId];
        return next;
      });
    }, 3000);
  };

  const downloadBackup = async (nodeId: number, nodeName: string) => {
    setLoading(true);
    setError('');
    setBackupProgress((previous) => ({ ...previous, [nodeId]: 'downloading' }));
    try {
      const blob = await downloadNodeBackup(nodeId);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `backup_${nodeName}_${new Date().toISOString().slice(0, 10)}.db`;
      anchor.click();
      window.URL.revokeObjectURL(url);
      toast(t('backup.downloadedBackup', {
        node: nodeName,
        size: (blob.size / 1024).toFixed(1),
        defaultValue: 'Downloaded backup: {{node}} ({{size}} KB)',
      }), 'success');
      setBackupProgress((previous) => ({ ...previous, [nodeId]: 'success' }));
      clearProgressSoon(nodeId);
    } catch (err: any) {
      setError(err.response?.data?.detail || `${t('backup.downloadFailed', 'Failed to download backup from')} ${nodeName}`);
      setBackupProgress((previous) => ({ ...previous, [nodeId]: 'error' }));
    } finally {
      setLoading(false);
    }
  };

  const sendBackupToTelegram = async (nodeId: number) => {
    setLoading(true);
    setError('');
    try {
      const result = await sendNodeBackupToTelegram(nodeId);
      const success = isTelegramDeliverySuccess(result);
      toast(
        result?.msg || (success ? t('backup.telegramNodeSuccess') : t('common.failed')),
        success ? 'success' : 'error',
      );
      if (!success) setError(result?.error || result?.msg || t('common.failed'));
    } catch (err: any) {
      setError(err.response?.data?.detail || t('common.failed'));
    } finally {
      setLoading(false);
    }
  };

  const downloadAllBackups = async () => {
    if (!window.confirm(t('backup.confirmDownloadAllServers'))) return;
    setLoading(true);
    setError('');
    try {
      const blob = await downloadAllBackupsBlob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `all_backups_${new Date().toISOString().slice(0, 10)}.zip`;
      anchor.click();
      window.URL.revokeObjectURL(url);
      toast(t('backup.downloadAllSuccess'), 'success');
    } catch (err: any) {
      setError(err.response?.data?.detail || t('backup.downloadAllFailed'));
    } finally {
      setLoading(false);
    }
  };

  const importBackup = async () => {
    if (!selectedNode || !importFile) {
      toast(t('backup.selectNodeAndFile'), 'warning');
      return;
    }
    if (!window.confirm(t('backup.confirmReplaceDb'))) return;
    setLoading(true);
    setError('');
    const formData = new FormData();
    formData.append('file', importFile);
    try {
      await importNodeBackup(selectedNode, formData);
      toast(t('backup.importSuccessRestartHint'), 'success');
      setImportFile(null);
      setSelectedNode(null);
    } catch (err: any) {
      setError(err.response?.data?.detail || t('backup.importFailed'));
    } finally {
      setLoading(false);
    }
  };

  const isBusy = loading || nodesLoading;
  const statusLabel = (progress: 'downloading' | 'success' | 'error' | undefined) => {
    if (progress === 'downloading') return t('backup.downloading');
    if (progress === 'success') return t('common.ready', 'Ready');
    if (progress === 'error') return t('common.error', 'Error');
    return t('backup.onDemand');
  };

  return (
    <div className={shellClass}>
      <section className={cn(panelClass, 'mb-4')}>
        <div className="mb-4 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h2 className="flex min-w-0 items-center gap-2 text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">
              <UIIcon name="backup" size={16} />
              {t('backup.backupRestore')}
            </h2>
            <p className={hintClass}>{t('backup.actionsHint')}</p>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button type="button" className={primaryButtonClass} onClick={downloadAllBackups} disabled={isBusy || nodes.length === 0}>
              <UIIcon name="backup" size={15} />
              <span className="whitespace-nowrap">{t('backup.backupAll', 'Backup All Nodes')}</span>
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              title={t('backup.telegramAllTitle')}
              disabled={isBusy || nodes.length === 0}
              onClick={async () => {
                if (!window.confirm(t('backup.confirmTelegramAll', { count: nodes.length }))) return;
                setLoading(true);
                setError('');
                let ok = 0;
                let fail = 0;
                try {
                  for (const node of nodes) {
                    try {
                      const result = await sendNodeBackupToTelegram(node.id);
                      if (isTelegramDeliverySuccess(result)) {
                        ok += 1;
                      } else {
                        fail += 1;
                      }
                    } catch {
                      fail += 1;
                    }
                  }
                  toast(t('backup.telegramAllResult', { ok, fail }), ok > 0 ? 'success' : 'error');
                } finally {
                  setLoading(false);
                }
              }}
            >
              <UIIcon name="backup" size={15} />
              <span className="whitespace-nowrap">{t('backup.telegramAll')}</span>
            </button>
            <button type="button" className={secondaryButtonClass} title={t('common.refresh', 'Refresh')} onClick={() => void loadNodes()} disabled={isBusy}>
              <UIIcon name="refresh" size={15} />
              <span className="whitespace-nowrap">{t('common.refresh', 'Refresh')}</span>
            </button>
          </div>
        </div>

        {error && <div className="mb-4 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>}

        <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
            <h3 className={titleClass}>{t('common.actions')}</h3>
            <div className="mt-4 grid grid-cols-3 gap-2">
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('backup.node')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-slate-100')}>{nodesLoading ? '...' : nodes.length}</strong>
              </div>
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('backup.transferMode')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-cyan-200')}>{t('backup.onDemand')}</strong>
              </div>
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('backup.preloaded')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-emerald-200')}>0</strong>
              </div>
            </div>
          </div>
          <div className="min-w-0 rounded-lg border border-cyan-300/20 bg-cyan-300/5 p-4 text-sm text-slate-300">
            <h3 className={titleClass}>{t('backup.notes')}</h3>
            <p className={hintClass}>{t('backup.onDemandHint')}</p>
            <div className="mt-3 text-slate-200"><strong>{t('backup.important')}:</strong> {t('backup.importantText')}</div>
          </div>
        </div>
      </section>

      <section className={cn(panelClass, 'mb-4')}>
        <div className="mb-4 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h3 className={cn(titleClass, 'flex min-w-0 items-center gap-2')}><UIIcon name="download" size={14} />{t('backup.downloadBackups')}</h3>
          <div className="text-xs text-slate-500">{t('backup.downloadOnDemandHint')}</div>
        </div>
        {nodesLoading ? (
          <div className="grid min-w-0 grid-cols-1 gap-3">
            {Array.from({ length: 4 }).map((_, index) => <div key={index} className="animate-pulse rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4"><div className="h-3 w-1/3 rounded bg-slate-700/60" /><div className="mt-3 h-3 w-2/3 rounded bg-slate-800" /><div className="mt-3 h-8 rounded bg-slate-900/80" /></div>)}
          </div>
        ) : nodes.length === 0 ? (
          <div className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
            <span className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[10px] uppercase tracking-[0.14em] text-cyan-200"><UIIcon name="backup" size={12} />{t('backup.noServers')}</span>
          </div>
        ) : (
          <div className="min-w-0">
            <div className="hidden min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 lg:block">
              <table className="w-full table-fixed border-collapse text-left text-xs">
                <thead className="bg-[#0a0e1a] text-[10px] uppercase tracking-wider text-slate-500"><tr className="border-b border-cyan-500/20"><th className="px-4 py-3">{t('backup.node')}</th><th className="w-48 px-4 py-3">{t('backup.connection')}</th><th className="w-40 px-4 py-3">{t('backup.status', 'Status')}</th><th className="w-32 px-4 py-3 text-right">{t('backup.action')}</th></tr></thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-200">
                  {nodes.map((node) => {
                    const progress = backupProgress[node.id];
                    return <tr key={node.id} className="bg-[#0f1420] transition hover:bg-cyan-400/5">
                      <td className="min-w-0 px-4 py-3"><span className="block min-w-0 truncate font-mono text-sm text-slate-100" title={node.name}>{node.name}</span></td>
                      <td className={cn(metricClass, 'px-4 py-3 text-slate-400')}>{nodeAddress(node)}</td>
                      <td className="px-4 py-3"><span className="inline-flex items-center gap-1 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2.5 py-1 font-mono text-[11px] tabular-nums whitespace-nowrap text-cyan-200"><UIIcon name={progress === 'error' ? 'warning' : progress === 'success' ? 'check' : 'download'} size={12} />{statusLabel(progress)}</span></td>
                      <td className="px-4 py-3"><div className="flex items-center justify-end gap-2">
                        <button type="button" className={cn(actionButtonClass, 'hover:bg-cyan-300/10')} title={t('backup.download')} aria-label={t('backup.download')} onClick={() => void downloadBackup(node.id, node.name)} disabled={isBusy || progress === 'downloading'}><UIIcon name={progress === 'downloading' ? 'spinner' : 'download'} size={15} /></button>
                        <button type="button" className={cn(actionButtonClass, 'hover:bg-emerald-300/10')} title={t('backup.telegramNodeTitle')} aria-label={t('backup.telegramNodeTitle')} onClick={() => void sendBackupToTelegram(node.id)} disabled={isBusy}><UIIcon name="backup" size={15} /></button>
                      </div></td>
                    </tr>;
                  })}
                </tbody>
              </table>
            </div>
            <div className="grid min-w-0 grid-cols-1 gap-3 lg:hidden">
              {nodes.map((node) => {
                const progress = backupProgress[node.id];
                return <article key={node.id} className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4"><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0 flex-1"><strong className="block truncate text-sm text-slate-100" title={node.name}>{node.name}</strong><div className="mt-3 grid min-w-0 grid-cols-2 gap-3"><div className="min-w-0"><span className={metaLabelClass}>{t('backup.connection')}</span><span className={cn(metaValueClass, metricClass)}>{nodeAddress(node)}</span></div><div className="min-w-0 text-right"><span className={metaLabelClass}>{t('backup.status', 'Status')}</span><span className={cn(metaValueClass, metricClass, progress === 'error' ? 'text-rose-200' : 'text-cyan-200')}>{statusLabel(progress)}</span></div></div></div><div className="flex shrink-0 flex-col gap-2"><button type="button" className={cn(actionButtonClass, 'hover:bg-cyan-300/10')} title={t('backup.download')} aria-label={t('backup.download')} onClick={() => void downloadBackup(node.id, node.name)} disabled={isBusy || progress === 'downloading'}><UIIcon name={progress === 'downloading' ? 'spinner' : 'download'} size={15} /></button><button type="button" className={cn(actionButtonClass, 'hover:bg-emerald-300/10')} title={t('backup.telegramNodeTitle')} aria-label={t('backup.telegramNodeTitle')} onClick={() => void sendBackupToTelegram(node.id)} disabled={isBusy}><UIIcon name="backup" size={15} /></button></div></div></article>;
              })}
            </div>
          </div>
        )}
      </section>

      <section className={cn(panelClass, 'mb-4')}>
        <h3 className={cn(titleClass, 'flex items-center gap-2')}><UIIcon name="upload" size={14} />{t('backup.restoreFromBackup')}</h3>
        <div className="mt-4 rounded-md border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100"><strong>{t('backup.warning')}:</strong> {t('backup.restoreWarning')}</div>
        <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4"><h4 className={titleClass}>{t('backup.targetNode')}</h4><p className={hintClass}>{t('backup.targetNodeHint')}</p><div className="mt-4 min-w-0"><ChoiceChips options={[{ value: 0, label: t('backup.chooseNode') }, ...nodes.map((node) => ({ value: node.id, label: `${node.name} (${nodeAddress(node)})` }))]} value={selectedNode || 0} onChange={(value) => setSelectedNode(value || null)} size="md" /></div></div>
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4"><h4 className={titleClass}>{t('backup.backupFile')}</h4><p className={hintClass}>{t('backup.backupFileHint')}</p><input type="file" className={cn(inputClass, 'mt-4')} accept=".db,.sqlite,.sqlite3" onChange={(event) => { if (event.target.files?.[0]) setImportFile(event.target.files[0]); }} /></div>
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4"><h4 className={titleClass}>{t('backup.restore')}</h4><p className={hintClass}>{t('backup.restoreHint')}</p><button type="button" className={cn(primaryButtonClass, 'mt-4 w-full from-amber-300 to-orange-400 hover:from-amber-200 hover:to-orange-300')} onClick={() => void importBackup()} disabled={loading || !selectedNode || !importFile}><UIIcon name="upload" size={14} /><span className="whitespace-nowrap">{t('backup.restoreBackup')}</span></button></div>
        </div>
        {importFile && <div className="mt-3 flex min-w-0 flex-col gap-1 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between"><span className="min-w-0 truncate">{t('backup.selectedFile')}: <strong className="text-slate-100" title={importFile.name}>{importFile.name}</strong></span><span className={cn(metricClass, 'text-slate-300')}>{(importFile.size / 1024).toFixed(1)} KB</span></div>}
      </section>

      <section className={panelClass}>
        <h3 className={cn(titleClass, 'flex items-center gap-2')}><UIIcon name="backup" size={14} />{t('backup.automatedBackups')}</h3>
        <p className={hintClass}>{t('backup.automatedBackupsHint')}</p>
        <div className="mt-4 min-w-0 overflow-x-auto rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4"><code className="block min-w-max font-mono text-xs text-slate-200">0 3 * * * curl -u username:password https://your-domain/api/v1/backup/all -o /backups/backup_$(date +\%Y\%m\%d).zip</code></div>
        <p className={cn(hintClass, 'mb-0')}>{t('backup.automatedBackupsExampleHint')}</p>
      </section>
    </div>
  );
};
