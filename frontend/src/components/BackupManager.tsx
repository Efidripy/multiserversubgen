import React, { useEffect, useState } from 'react';
import { useToast } from './Toast';
import api from '../api';
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
type BackupSortField = 'created' | 'name' | 'size' | 'status';

interface RawBackupPoint {
  node?: string;
  backup_b64?: string;
  encoding?: string;
  timestamp?: string;
  error?: string;
}

interface BackupPoint {
  id: string;
  nodeName: string;
  nodeId: number | null;
  backupB64: string;
  encoding: string;
  createdAt: string;
  sizeBytes: number;
  sizeLabel: string;
  hash: string;
  error: string;
  status: 'ready' | 'error';
}

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const shellClass = 'min-h-screen min-w-0 overflow-hidden bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6';
const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]';
const titleClass = 'text-xs font-medium uppercase tracking-[0.14em] text-slate-300';
const hintClass = 'mt-1 text-xs font-light leading-5 text-slate-500';
const metricClass = 'font-mono tabular-nums whitespace-nowrap';
const headerButtonClass = 'inline-flex whitespace-nowrap text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500 transition hover:text-cyan-300';
const actionButtonClass = 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] text-slate-300 transition hover:border-cyan-300/50 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const primaryButtonClass = 'inline-flex h-10 min-w-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/25 bg-gradient-to-r from-cyan-400 to-emerald-300 px-5 text-xs font-medium uppercase tracking-[0.14em] text-[#06111f] shadow-[0_14px_38px_rgba(34,211,238,0.18)] transition hover:from-cyan-300 hover:to-emerald-200 disabled:cursor-not-allowed disabled:opacity-45';
const secondaryButtonClass = 'inline-flex h-10 min-w-0 items-center justify-center gap-2 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 text-xs font-medium uppercase tracking-[0.14em] text-slate-300 transition hover:border-cyan-300/40 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const inputClass = 'block w-full min-w-0 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-xs font-light text-slate-100 outline-none file:mr-3 file:rounded-md file:border file:border-cyan-500/20 file:bg-[#0f1420] file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-slate-200 focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10';
const metaLabelClass = 'text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500';
const metaValueClass = 'mt-1 block min-w-0 truncate text-xs font-light text-slate-200';

export const BackupManager: React.FC = () => {
  const { toast } = useToast();
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [backupPoints, setBackupPoints] = useState<BackupPoint[]>([]);
  const [nodesLoading, setNodesLoading] = useState(false);
  const [pointsLoading, setPointsLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [backupProgress, setBackupProgress] = useState<Record<number, 'downloading' | 'success' | 'error'>>({});
  const [selectedNode, setSelectedNode] = useState<number | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [sortField, setSortField] = useState<BackupSortField>('created');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [restoringPointId, setRestoringPointId] = useState('');

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
    return `${Math.round((bytes / Math.pow(k, i)) * 100) / 100} ${sizes[i]}`;
  };

  const estimateBase64Bytes = (value: string) => {
    const normalized = value.replace(/\s/g, '');
    if (!normalized) return 0;
    const padding = normalized.endsWith('==') ? 2 : normalized.endsWith('=') ? 1 : 0;
    return Math.max(0, Math.floor((normalized.length * 3) / 4) - padding);
  };

  const hashBackupPayload = (value: string) => {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  };

  const nodeAddress = (node: Node) => {
    if (node.ip || node.port) return `${node.ip || '-'}:${node.port || '-'}`;
    return node.url || node.panel_url || '-';
  };

  const getNodeByName = (nodeName: string, nodeList = nodes) =>
    nodeList.find((node) => node.name === nodeName) || null;

  const normalizeBackupPoints = (rawBackups: RawBackupPoint[], nodeList: Node[]): BackupPoint[] =>
    rawBackups.map((raw, index) => {
      const nodeName = raw.node || `node-${index + 1}`;
      const node = getNodeByName(nodeName, nodeList);
      const backupB64 = raw.backup_b64 || '';
      const createdAt = raw.timestamp || new Date().toISOString();
      const sizeBytes = estimateBase64Bytes(backupB64);
      const hasPayload = backupB64.length > 0;
      const status = raw.error || !hasPayload ? 'error' : 'ready';

      return {
        id: `${nodeName}-${createdAt}-${index}`,
        nodeName,
        nodeId: node?.id ?? null,
        backupB64,
        encoding: raw.encoding || 'base64',
        createdAt,
        sizeBytes,
        sizeLabel: formatBytes(sizeBytes),
        hash: hasPayload ? hashBackupPayload(backupB64) : '-',
        error: raw.error || (!hasPayload ? t('backup.emptyBackupPayload', 'Empty backup payload') : ''),
        status,
      };
    });

  const loadNodes = async () => {
    setNodesLoading(true);
    try {
      const nodeList = await listNodes();
      setNodes(nodeList);
      return nodeList;
    } catch (err) {
      console.error('Failed to load nodes:', err);
      setError(t('backup.loadNodesFailed'));
      return [];
    } finally {
      setNodesLoading(false);
    }
  };

  const loadBackupPoints = async (nodeList = nodes) => {
    setPointsLoading(true);
    try {
      const res = await api.get('/v1/backup/all', {
        params: { format: 'json', _ts: Date.now() },
      });
      const rawBackups: RawBackupPoint[] = Array.isArray(res.data?.backups) ? res.data.backups : [];
      setBackupPoints(normalizeBackupPoints(rawBackups, nodeList));
    } catch (err: any) {
      console.error('Failed to load backup points:', err);
      setBackupPoints([]);
      setError(err.response?.data?.detail || t('backup.loadBackupsFailed', 'Failed to load backups'));
    } finally {
      setPointsLoading(false);
    }
  };

  const loadInitialData = async () => {
    setError('');
    const nodeList = await loadNodes();
    await loadBackupPoints(nodeList);
  };

  useEffect(() => {
    void loadInitialData();
  }, []);

  const refreshBackups = async () => {
    setError('');
    const nodeList = nodes.length > 0 ? nodes : await loadNodes();
    await loadBackupPoints(nodeList);
  };

  const downloadBackup = async (nodeId: number, nodeName: string) => {
    setLoading(true);
    setError('');
    setBackupProgress((prev) => ({ ...prev, [nodeId]: 'downloading' }));

    try {
      const blob = await downloadNodeBackup(nodeId);
      const sizeKB = (blob.size / 1024).toFixed(1);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `backup_${nodeName}_${new Date().toISOString().slice(0, 10)}.db`;
      anchor.click();
      window.URL.revokeObjectURL(url);
      toast(t('backup.downloadedBackup', {
        node: nodeName,
        size: sizeKB,
        defaultValue: 'Downloaded backup: {{node}} ({{size}} KB)',
      }), 'success');
      setBackupProgress((prev) => ({ ...prev, [nodeId]: 'success' }));
      window.setTimeout(() => {
        setBackupProgress((prev) => {
          const next = { ...prev };
          delete next[nodeId];
          return next;
        });
      }, 3000);
      await refreshBackups();
    } catch (err: any) {
      setError(err.response?.data?.detail || `${t('backup.downloadFailed', 'Failed to download backup from')} ${nodeName}`);
      setBackupProgress((prev) => ({ ...prev, [nodeId]: 'error' }));
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
      await refreshBackups();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('backup.downloadAllFailed'));
    } finally {
      setLoading(false);
    }
  };

  const restoreBackupPoint = async (point: BackupPoint) => {
    const targetNodeId = selectedNode || point.nodeId;
    if (!targetNodeId || !point.backupB64) {
      toast(t('backup.selectNodeAndFile'), 'warning');
      return;
    }
    if (!window.confirm(t('backup.confirmReplaceDb'))) return;

    setRestoringPointId(point.id);
    setError('');

    try {
      await api.post(`/v1/backup/database/${targetNodeId}`, { backup_data: point.backupB64 });
      toast(t('backup.importSuccessRestartHint'), 'success');
      await refreshBackups();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('backup.importFailed'));
    } finally {
      setRestoringPointId('');
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setImportFile(e.target.files[0]);
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
      await refreshBackups();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('backup.importFailed'));
    } finally {
      setLoading(false);
    }
  };

  const sortedBackupPoints = [...backupPoints].sort((a, b) => {
    const factor = sortDirection === 'asc' ? 1 : -1;
    const byName = a.nodeName.localeCompare(b.nodeName, undefined, { sensitivity: 'base', numeric: true });
    const byCreated = Date.parse(a.createdAt) - Date.parse(b.createdAt);
    const bySize = a.sizeBytes - b.sizeBytes;
    const byStatus = a.status === b.status ? 0 : a.status === 'error' ? 1 : -1;

    if (sortField === 'name') {
      if (byName !== 0) return byName * factor;
      return byCreated * factor;
    }
    if (sortField === 'size') {
      if (bySize !== 0) return bySize * factor;
      return byName;
    }
    if (sortField === 'status') {
      if (byStatus !== 0) return byStatus * factor;
      return byCreated * factor;
    }
    if (byCreated !== 0) return byCreated * factor;
    return byName;
  });

  const applySortFromHeader = (field: BackupSortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortField(field);
    setSortDirection(field === 'created' || field === 'size' ? 'desc' : 'asc');
  };

  const sortIndicator = (field: BackupSortField) =>
    sortField === field ? (sortDirection === 'asc' ? ' ^' : ' v') : '';

  const renderSkeletonRows = () => Array.from({ length: 4 }).map((_, index) => (
    <div key={index} className="animate-pulse rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
      <div className="h-3 w-1/3 rounded bg-slate-700/60" />
      <div className="mt-3 h-3 w-2/3 rounded bg-slate-800" />
      <div className="mt-3 h-8 rounded bg-slate-900/80" />
    </div>
  ));

  const isBusy = loading || nodesLoading || pointsLoading || Boolean(restoringPointId);

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
            <button
              type="button"
              className={primaryButtonClass}
              onClick={downloadAllBackups}
              disabled={isBusy || nodes.length === 0}
            >
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
                let ok = 0;
                let fail = 0;
                for (const node of nodes) {
                  try {
                    await sendNodeBackupToTelegram(node.id);
                    ok += 1;
                  } catch {
                    fail += 1;
                  }
                }
                setLoading(false);
                toast(t('backup.telegramAllResult', { ok, fail }), ok > 0 ? 'success' : 'error');
              }}
            >
              <UIIcon name="backup" size={15} />
              <span className="whitespace-nowrap">{t('backup.telegramAll')}</span>
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              title={t('common.refresh', 'Refresh')}
              onClick={refreshBackups}
              disabled={isBusy}
            >
              <UIIcon name="refresh" size={15} />
              <span className="whitespace-nowrap">{t('common.refresh', 'Refresh')}</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </div>
        )}

        <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
            <h3 className={titleClass}>{t('common.actions')}</h3>
            <div className="mt-4 grid grid-cols-3 gap-2">
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('backup.node')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-slate-100')}>{nodesLoading ? '...' : nodes.length}</strong>
              </div>
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('backup.backups', 'Backups')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-cyan-200')}>
                  {pointsLoading ? '...' : backupPoints.length}
                </strong>
              </div>
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('backup.ready', 'Ready')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-emerald-200')}>
                  {pointsLoading ? '...' : backupPoints.filter((point) => point.status === 'ready').length}
                </strong>
              </div>
            </div>
          </div>
          <div className="min-w-0 rounded-lg border border-cyan-300/20 bg-cyan-300/5 p-4 text-sm text-slate-300">
            <h3 className={titleClass}>{t('backup.notes')}</h3>
            <p className={hintClass}>{t('backup.notesHint')}</p>
            <div className="mt-3 text-slate-200">
              <strong>{t('backup.important')}:</strong> {t('backup.importantText')}
            </div>
          </div>
        </div>
      </section>

      <section className={cn(panelClass, 'mb-4')}>
        <div className="mb-4 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h3 className={cn(titleClass, 'flex min-w-0 items-center gap-2')}>
            <UIIcon name="download" size={14} />
            {t('backup.downloadBackups')}
          </h3>
          <div className="text-xs text-slate-500">{t('backup.sortHint')}</div>
        </div>

        {pointsLoading ? (
          <div className="grid min-w-0 grid-cols-1 gap-3">
            {renderSkeletonRows()}
          </div>
        ) : backupPoints.length === 0 ? (
          <div className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
            <span className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[10px] uppercase tracking-[0.14em] text-cyan-200">
              <UIIcon name="backup" size={12} />
              {t('backup.noBackupsFound', 'No backups found')}
            </span>
          </div>
        ) : (
          <div className="min-w-0">
            <div className="hidden min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 lg:block">
              <table className="w-full table-fixed border-collapse text-left text-xs">
                <thead className="bg-[#0a0e1a] text-[10px] uppercase tracking-wider text-slate-500">
                  <tr className="border-b border-cyan-500/20">
                    <th className="w-40 px-4 py-3">
                      <button type="button" className={headerButtonClass} onClick={() => applySortFromHeader('created')}>
                        {t('common.created')}{sortIndicator('created')}
                      </button>
                    </th>
                    <th className="px-4 py-3">
                      <button type="button" className={headerButtonClass} onClick={() => applySortFromHeader('name')}>
                        {t('backup.backupFile')}{sortIndicator('name')}
                      </button>
                    </th>
                    <th className="w-32 px-4 py-3 text-right">
                      <button type="button" className={cn(headerButtonClass, 'justify-end')} onClick={() => applySortFromHeader('size')}>
                        {t('backup.size', 'Size')}{sortIndicator('size')}
                      </button>
                    </th>
                    <th className="w-28 px-4 py-3">
                      <span className={headerButtonClass}>{t('backup.fileType', 'Type')}</span>
                    </th>
                    <th className="w-36 px-4 py-3">
                      <button type="button" className={headerButtonClass} onClick={() => applySortFromHeader('status')}>
                        {t('backup.status', 'Status')}{sortIndicator('status')}
                      </button>
                    </th>
                    <th className="w-36 px-4 py-3">
                      <span className={headerButtonClass}>{t('backup.hash', 'Hash')}</span>
                    </th>
                    <th className="w-32 px-4 py-3 text-right">{t('backup.action')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-200">
                  {sortedBackupPoints.map((point) => {
                    const fileName = `backup_${point.nodeName}_${point.createdAt.slice(0, 10)}.db`;
                    const pointBusy = restoringPointId === point.id;
                    const pointDownloadState = point.nodeId ? backupProgress[point.nodeId] : undefined;
                    return (
                      <tr key={point.id} className="bg-[#0f1420] transition hover:bg-cyan-400/5">
                        <td className={cn(metricClass, 'px-4 py-3 text-slate-400 font-mono whitespace-nowrap')}>
                          {point.createdAt}
                        </td>
                        <td className="min-w-0 px-4 py-3">
                          <div className="min-w-0">
                            <strong className="block truncate text-sm text-slate-100" title={fileName}>{fileName}</strong>
                            <span className="mt-1 block truncate text-[11px] text-slate-500" title={point.nodeName}>
                              {point.nodeName}
                            </span>
                          </div>
                        </td>
                        <td className={cn(metricClass, 'px-4 py-3 text-right text-slate-300')}>
                          {point.sizeLabel}
                        </td>
                        <td className={cn(metricClass, 'px-4 py-3 text-slate-300')}>
                          {point.encoding}
                        </td>
                        <td className="px-4 py-3">
                          {point.error ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/20 bg-rose-500/10 px-2.5 py-1 font-mono text-[11px] tabular-nums whitespace-nowrap text-rose-200">
                              <UIIcon name="warning" size={12} />
                              {t('common.error', 'Error')}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 font-mono text-[11px] tabular-nums whitespace-nowrap text-emerald-200">
                              <UIIcon name="check" size={12} />
                              {t('common.ready', 'Ready')}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span className="block min-w-0 truncate font-mono text-[11px] tabular-nums whitespace-nowrap text-slate-300" title={point.hash}>
                            {point.hash}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              className={cn(actionButtonClass, 'hover:bg-cyan-300/10')}
                              title={t('backup.download')}
                              aria-label={t('backup.download')}
                              onClick={() => {
                                if (!point.nodeId) return;
                                void downloadBackup(point.nodeId, point.nodeName);
                              }}
                              disabled={isBusy || !point.nodeId || pointDownloadState === 'downloading'}
                            >
                              <UIIcon name={pointDownloadState === 'downloading' ? 'spinner' : 'download'} size={15} />
                            </button>
                            <button
                              type="button"
                              className={cn(actionButtonClass, 'hover:bg-emerald-300/10')}
                              title={t('backup.telegramNodeTitle')}
                              aria-label={t('backup.telegramNodeTitle')}
                              onClick={async () => {
                                if (!point.nodeId) return;
                                try {
                                  const res = await sendNodeBackupToTelegram(point.nodeId);
                                  toast(
                                    res?.msg || (res?.success ? t('backup.telegramNodeSuccess') : t('common.failed')),
                                    res?.success !== false ? 'success' : 'error',
                                  );
                                } catch (e: any) {
                                  toast(e.response?.data?.detail || t('common.failed'), 'error');
                                }
                              }}
                              disabled={isBusy || !point.nodeId}
                            >
                              <UIIcon name="backup" size={15} />
                            </button>
                            <button
                              type="button"
                              className={cn(actionButtonClass, 'hover:bg-rose-300/10')}
                              title={t('backup.restoreBackup')}
                              aria-label={t('backup.restoreBackup')}
                              onClick={() => void restoreBackupPoint(point)}
                              disabled={isBusy || !point.backupB64 || pointBusy}
                            >
                              <UIIcon name="upload" size={15} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="grid min-w-0 grid-cols-1 gap-3 lg:hidden">
              {sortedBackupPoints.map((point) => {
                const fileName = `backup_${point.nodeName}_${point.createdAt.slice(0, 10)}.db`;
                const pointBusy = restoringPointId === point.id;
                const pointDownloadState = point.nodeId ? backupProgress[point.nodeId] : undefined;
                return (
                  <article key={point.id} className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <strong className="block truncate text-sm text-slate-100" title={fileName}>{fileName}</strong>
                        <div className="mt-3 grid min-w-0 grid-cols-2 gap-3">
                          <div className="min-w-0">
                            <span className={metaLabelClass}>{t('common.created')}</span>
                            <span className={cn(metaValueClass, metricClass)}>{point.createdAt}</span>
                          </div>
                          <div className="min-w-0 text-right">
                            <span className={metaLabelClass}>{t('backup.size', 'Size')}</span>
                            <span className={cn(metaValueClass, metricClass)}>{point.sizeLabel}</span>
                          </div>
                          <div className="min-w-0">
                            <span className={metaLabelClass}>{t('backup.node')}</span>
                            <span className={cn(metaValueClass, metricClass)} title={point.nodeName}>{point.nodeName}</span>
                          </div>
                          <div className="min-w-0 text-right">
                            <span className={metaLabelClass}>{t('backup.hash', 'Hash')}</span>
                            <span className={cn(metaValueClass, metricClass)} title={point.hash}>{point.hash}</span>
                          </div>
                          <div className="min-w-0">
                            <span className={metaLabelClass}>{t('backup.fileType', 'Type')}</span>
                            <span className={cn(metaValueClass, metricClass)}>{point.encoding}</span>
                          </div>
                          <div className="min-w-0 text-right">
                            <span className={metaLabelClass}>{t('backup.status', 'Status')}</span>
                            <span className={cn(metaValueClass, metricClass, point.error ? 'text-rose-200' : 'text-emerald-200')}>
                              {point.error ? t('common.error', 'Error') : t('common.ready', 'Ready')}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col gap-2">
                        <button
                          type="button"
                          className={cn(actionButtonClass, 'hover:bg-cyan-300/10')}
                          title={t('backup.download')}
                          aria-label={t('backup.download')}
                          onClick={() => {
                            if (!point.nodeId) return;
                            void downloadBackup(point.nodeId, point.nodeName);
                          }}
                          disabled={isBusy || !point.nodeId || pointDownloadState === 'downloading'}
                        >
                          <UIIcon name={pointDownloadState === 'downloading' ? 'spinner' : 'download'} size={15} />
                        </button>
                        <button
                          type="button"
                          className={cn(actionButtonClass, 'hover:bg-emerald-300/10')}
                          title={t('backup.telegramNodeTitle')}
                          aria-label={t('backup.telegramNodeTitle')}
                          onClick={async () => {
                            if (!point.nodeId) return;
                            try {
                              const res = await sendNodeBackupToTelegram(point.nodeId);
                              toast(
                                res?.msg || (res?.success ? t('backup.telegramNodeSuccess') : t('common.failed')),
                                res?.success !== false ? 'success' : 'error',
                              );
                            } catch (e: any) {
                              toast(e.response?.data?.detail || t('common.failed'), 'error');
                            }
                          }}
                          disabled={isBusy || !point.nodeId}
                        >
                          <UIIcon name="backup" size={15} />
                        </button>
                        <button
                          type="button"
                          className={cn(actionButtonClass, 'hover:bg-rose-300/10')}
                          title={t('backup.restoreBackup')}
                          aria-label={t('backup.restoreBackup')}
                          onClick={() => void restoreBackupPoint(point)}
                          disabled={isBusy || !point.backupB64 || pointBusy}
                        >
                          <UIIcon name="upload" size={15} />
                        </button>
                      </div>
                    </div>
                    {point.error && (
                      <div className="mt-3 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                        {point.error}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </div>
        )}
      </section>

      <section className={cn(panelClass, 'mb-4')}>
        <h3 className={cn(titleClass, 'flex items-center gap-2 text-amber-200')}>
          <UIIcon name="upload" size={14} />
          {t('backup.restoreFromBackup')}
        </h3>

        <div className="mt-4 rounded-md border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
          <strong>{t('backup.warning')}:</strong> {t('backup.restoreWarning')}
        </div>

        <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
            <h4 className={titleClass}>{t('backup.targetNode')}</h4>
            <p className={hintClass}>{t('backup.targetNodeHint')}</p>
            <div className="mt-4 min-w-0">
              <ChoiceChips
                options={[
                  { value: 0, label: t('backup.chooseNode') },
                  ...nodes.map((node) => ({ value: node.id, label: `${node.name} (${nodeAddress(node)})` })),
                ]}
                value={selectedNode || 0}
                onChange={(value) => setSelectedNode(value || null)}
                size="md"
              />
            </div>
          </div>
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
            <h4 className={titleClass}>{t('backup.backupFile')}</h4>
            <p className={hintClass}>{t('backup.backupFileHint')}</p>
            <input
              type="file"
              className={cn(inputClass, 'mt-4')}
              accept=".db,.sqlite,.sqlite3"
              onChange={handleFileChange}
            />
          </div>
          <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
            <h4 className={titleClass}>{t('backup.restore')}</h4>
            <p className={hintClass}>{t('backup.restoreHint')}</p>
            <button
              type="button"
              className={cn(primaryButtonClass, 'mt-4 w-full from-amber-300 to-orange-400 hover:from-amber-200 hover:to-orange-300')}
              onClick={importBackup}
              disabled={loading || !selectedNode || !importFile}
            >
              <UIIcon name="upload" size={14} />
              <span className="whitespace-nowrap">{t('backup.restoreBackup')}</span>
            </button>
          </div>
        </div>

        {importFile && (
          <div className="mt-3 flex min-w-0 flex-col gap-1 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <span className="min-w-0 truncate">
              {t('backup.selectedFile')}: <strong className="text-slate-100" title={importFile.name}>{importFile.name}</strong>
            </span>
            <span className={cn(metricClass, 'text-slate-300')}>{formatBytes(importFile.size)}</span>
          </div>
        )}
      </section>

      <section className={panelClass}>
        <h3 className={cn(titleClass, 'flex items-center gap-2')}>
          <UIIcon name="backup" size={14} />
          {t('backup.automatedBackups')}
        </h3>
        <p className={hintClass}>{t('backup.automatedBackupsHint')}</p>
        <div className="mt-4 min-w-0 overflow-x-auto rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
          <code className="block min-w-max font-mono text-xs text-slate-200">
            0 3 * * * curl -u username:password https://your-domain/api/v1/backup/all -o /backups/backup_$(date +\%Y\%m\%d).zip
          </code>
        </div>
        <p className={cn(hintClass, 'mb-0')}>{t('backup.automatedBackupsExampleHint')}</p>
      </section>
    </div>
  );
};
