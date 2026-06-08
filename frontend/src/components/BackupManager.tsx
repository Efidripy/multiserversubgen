import React, { useState, useEffect } from 'react';
import { useToast } from './Toast';
import api from '../api';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';
import { useTranslation } from 'react-i18next';

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
}

type SortField = 'name' | 'address' | 'status';

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [backupProgress, setBackupProgress] = useState<Record<number, string>>({});
  const [selectedNode, setSelectedNode] = useState<number | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');

  useEffect(() => {
    loadNodes();
  }, []);

  const loadNodes = async () => {
    try {
      const res = await api.get('/v1/nodes', {
        auth: getAuth()
      });
      setNodes(res.data);
    } catch (err) {
      console.error('Failed to load nodes:', err);
      setError(t('backup.loadNodesFailed'));
    }
  };

  const downloadBackup = async (nodeId: number, nodeName: string) => {
    setLoading(true);
    setError('');
    setBackupProgress({ ...backupProgress, [nodeId]: 'downloading' });

    try {
      const res = await api.get(`/v1/backup/node/${nodeId}`, {
        auth: getAuth(),
        responseType: 'blob'
      });

      const blob = new Blob([res.data], { type: 'application/x-sqlite3' });
      const sizeKB = (blob.size / 1024).toFixed(1);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `backup_${nodeName}_${new Date().toISOString().split('T')[0]}.db`;
      a.click();
      window.URL.revokeObjectURL(url);
      toast(`Downloaded backup: ${nodeName} (${sizeKB} KB)`, 'success');

      setBackupProgress({ ...backupProgress, [nodeId]: 'success' });
      setTimeout(() => {
        setBackupProgress(prev => {
          const newProgress = { ...prev };
          delete newProgress[nodeId];
          return newProgress;
        });
      }, 3000);
    } catch (err: any) {
      setError(err.response?.data?.detail || `Failed to download backup from ${nodeName}`);
      setBackupProgress({ ...backupProgress, [nodeId]: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const downloadAllBackups = async () => {
    if (!window.confirm(t('backup.confirmDownloadAllServers'))) return;

    setLoading(true);
    setError('');

    try {
      const res = await api.get('/v1/backup/all', {
        auth: getAuth(),
        responseType: 'blob'
      });

      const blob = new Blob([res.data], { type: 'application/zip' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `all_backups_${new Date().toISOString().split('T')[0]}.zip`;
      a.click();
      window.URL.revokeObjectURL(url);

      toast(t('backup.downloadAllSuccess'), 'success');
    } catch (err: any) {
      setError(err.response?.data?.detail || t('backup.downloadAllFailed'));
    } finally {
      setLoading(false);
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

    if (!window.confirm(t('backup.confirmReplaceDb'))) {
      return;
    }

    setLoading(true);
    setError('');

    const formData = new FormData();
    formData.append('file', importFile);

    try {
      await api.post(`/v1/backup/node/${selectedNode}/import`, formData, {
        auth: getAuth(),
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });

      toast(t('backup.importSuccessRestartHint'), 'success');
      setImportFile(null);
      setSelectedNode(null);
    } catch (err: any) {
      setError(err.response?.data?.detail || t('backup.importFailed'));
    } finally {
      setLoading(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  };

  const getProgressIcon = (nodeId: number) => {
    const status = backupProgress[nodeId];
    if (status === 'downloading') return <UIIcon name="spinner" size={14} />;
    if (status === 'success') return <UIIcon name="check" size={14} />;
    if (status === 'error') return <UIIcon name="x" size={14} />;
    return null;
  };

  const statusWeight = (nodeId: number) => {
    const status = backupProgress[nodeId];
    if (status === 'downloading') return 3;
    if (status === 'error') return 2;
    if (status === 'success') return 1;
    return 0;
  };
  const compareText = (a: string, b: string) =>
    a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });
  const factor = sortDirection === 'asc' ? 1 : -1;
  const sortedNodes = [...nodes].sort((a, b) => {
    const byName = compareText(a.name, b.name);
    const byAddress = compareText(`${a.ip}:${a.port}`, `${b.ip}:${b.port}`);
    const byStatus = statusWeight(a.id) - statusWeight(b.id);
    if (sortField === 'name') {
      if (byName !== 0) return byName * factor;
      return byAddress * factor;
    }
    if (sortField === 'address') {
      if (byAddress !== 0) return byAddress * factor;
      return byName * factor;
    }
    if (byStatus !== 0) return byStatus * factor;
    if (byName !== 0) return byName;
    return byAddress;
  });

  const applySortFromHeader = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortField(field);
    setSortDirection(field === 'status' ? 'desc' : 'asc');
  };

  const sortIndicator = (field: SortField) =>
    sortField === field ? (sortDirection === 'asc' ? ' ^' : ' v') : '';

  const backupDateLabel = new Date().toISOString().slice(0, 10);
  const getBackupFileName = (node: Node) => `backup_${node.name}_${backupDateLabel}.db`;
  const backupTypeLabel = t('backup.sqliteDb', 'SQLite DB');
  const backupSizeLabel = t('backup.generatedOnDownload', 'Generated on download');
  const renderProgressTone = (nodeId: number) => {
    const status = backupProgress[nodeId];
    if (status === 'downloading') return 'text-cyan-300';
    if (status === 'success') return 'text-emerald-300';
    if (status === 'error') return 'text-rose-300';
    return 'text-slate-600';
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
            <button type="button" className={primaryButtonClass} onClick={downloadAllBackups} disabled={loading || nodes.length === 0}>
              <UIIcon name="backup" size={15} />
              <span className="whitespace-nowrap">{t('backup.backupAll', 'Backup All Nodes')}</span>
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              title={t('backup.telegramAllTitle')}
              disabled={loading || nodes.length === 0}
              onClick={async () => {
                if (!window.confirm(t('backup.confirmTelegramAll', { count: nodes.length }))) return;
                setLoading(true);
                let ok = 0; let fail = 0;
                for (const node of nodes) {
                  try {
                    await api.post(`/v1/nodes/${node.id}/backup-telegram`, {}, { auth: getAuth() });
                    ok++;
                  } catch { fail++; }
                }
                setLoading(false);
                toast(t('backup.telegramAllResult', { ok, fail }), ok > 0 ? 'success' : 'error');
              }}
            >
              <UIIcon name="backup" size={15} />
              <span className="whitespace-nowrap">{t('backup.telegramAll')}</span>
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
                <strong className={cn(metricClass, 'mt-1 block text-sm text-slate-100')}>{nodes.length}</strong>
              </div>
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('backup.backupFile')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-cyan-200')}>.db</strong>
              </div>
              <div className="min-w-0 rounded-md bg-[#0f1420] px-3 py-2">
                <span className="block truncate text-[10px] uppercase tracking-wider text-slate-500">{t('common.created')}</span>
                <strong className={cn(metricClass, 'mt-1 block text-sm text-slate-300')}>{backupDateLabel}</strong>
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

        {nodes.length === 0 ? (
          <p className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
            {t('backup.noServers')}
          </p>
        ) : (
          <div className="min-w-0">
            <div className="hidden min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 lg:block">
              <table className="w-full table-fixed border-collapse text-left text-xs">
                <thead className="bg-[#0a0e1a] text-[10px] uppercase tracking-wider text-slate-500">
                  <tr className="border-b border-cyan-500/20">
                    <th className="w-40 px-4 py-3">
                      <span className={headerButtonClass}>{t('common.created')}</span>
                    </th>
                    <th className="px-4 py-3">
                      <button type="button" className={headerButtonClass} onClick={() => applySortFromHeader('name')}>
                        {t('backup.backupFile')}{sortIndicator('name')}
                      </button>
                    </th>
                    <th className="w-40 px-4 py-3 text-right">
                      <span className={cn(headerButtonClass, 'justify-end')}>{t('backup.size', 'Size')}</span>
                    </th>
                    <th className="w-32 px-4 py-3">
                      <span className={headerButtonClass}>{t('backup.fileType', 'Type')}</span>
                    </th>
                    <th className="w-32 px-4 py-3 text-right">
                      <button type="button" className={cn(headerButtonClass, 'justify-end')} onClick={() => applySortFromHeader('status')}>
                        {t('backup.action')}{sortIndicator('status')}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-200">
                  {sortedNodes.map((node) => {
                    const fileName = getBackupFileName(node);
                    return (
                      <tr key={node.id} className="bg-[#0f1420] transition hover:bg-cyan-400/5">
                        <td className={cn(metricClass, 'px-4 py-3 text-slate-400')}>{backupDateLabel}</td>
                        <td className="min-w-0 px-4 py-3">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className={cn('shrink-0', renderProgressTone(node.id))}>{getProgressIcon(node.id) || <UIIcon name="backup" size={14} />}</span>
                            <div className="min-w-0">
                              <strong className="block truncate text-sm text-slate-100" title={fileName}>{fileName}</strong>
                              <span className="mt-1 block truncate text-[11px] text-slate-500" title={`${node.ip}:${node.port}`}>
                                {node.name} - <span className={metricClass}>{node.ip}:{node.port}</span>
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className={cn(metricClass, 'px-4 py-3 text-right text-slate-500')}>{backupSizeLabel}</td>
                        <td className={cn(metricClass, 'px-4 py-3 text-slate-300')}>{backupTypeLabel}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              className={cn(actionButtonClass, 'hover:bg-cyan-300/10')}
                              title={t('backup.download')}
                              aria-label={t('backup.download')}
                              onClick={() => downloadBackup(node.id, node.name)}
                              disabled={loading || backupProgress[node.id] === 'downloading'}
                            >
                              <UIIcon name="download" size={15} />
                            </button>
                            <button
                              type="button"
                              className={cn(actionButtonClass, 'hover:bg-emerald-300/10')}
                              title={t('backup.telegramNodeTitle')}
                              aria-label={t('backup.telegramNodeTitle')}
                              onClick={async () => {
                                try {
                                  const res = await api.post(`/v1/nodes/${node.id}/backup-telegram`, {}, { auth: getAuth() });
                                  toast(
                                    res.data?.msg || (res.data?.success ? t('backup.telegramNodeSuccess') : t('common.failed')),
                                    res.data?.success !== false ? 'success' : 'error',
                                  );
                                } catch (e: any) { toast(e.response?.data?.detail || t('common.failed'), 'error'); }
                              }}
                            >
                              <UIIcon name="backup" size={15} />
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
              {sortedNodes.map((node) => {
                const fileName = getBackupFileName(node);
                return (
                  <article key={node.id} className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className={cn('shrink-0', renderProgressTone(node.id))}>{getProgressIcon(node.id) || <UIIcon name="backup" size={14} />}</span>
                          <strong className="block min-w-0 truncate text-sm text-slate-100" title={fileName}>{fileName}</strong>
                        </div>
                        <div className="mt-3 grid min-w-0 grid-cols-2 gap-3">
                          <div className="min-w-0">
                            <span className={metaLabelClass}>{t('common.created')}</span>
                            <span className={cn(metaValueClass, metricClass)}>{backupDateLabel}</span>
                          </div>
                          <div className="min-w-0 text-right">
                            <span className={metaLabelClass}>{t('backup.size', 'Size')}</span>
                            <span className={cn(metaValueClass, metricClass)}>{backupSizeLabel}</span>
                          </div>
                          <div className="min-w-0">
                            <span className={metaLabelClass}>{t('backup.fileType', 'Type')}</span>
                            <span className={cn(metaValueClass, metricClass)}>{backupTypeLabel}</span>
                          </div>
                          <div className="min-w-0 text-right">
                            <span className={metaLabelClass}>{t('backup.address')}</span>
                            <span className={cn(metaValueClass, metricClass)} title={`${node.ip}:${node.port}`}>{node.ip}:{node.port}</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col gap-2">
                        <button
                          type="button"
                          className={cn(actionButtonClass, 'hover:bg-cyan-300/10')}
                          title={t('backup.download')}
                          aria-label={t('backup.download')}
                          onClick={() => downloadBackup(node.id, node.name)}
                          disabled={loading || backupProgress[node.id] === 'downloading'}
                        >
                          <UIIcon name="download" size={15} />
                        </button>
                        <button
                          type="button"
                          className={cn(actionButtonClass, 'hover:bg-emerald-300/10')}
                          title={t('backup.telegramNodeTitle')}
                          aria-label={t('backup.telegramNodeTitle')}
                          onClick={async () => {
                            try {
                              const res = await api.post(`/v1/nodes/${node.id}/backup-telegram`, {}, { auth: getAuth() });
                              toast(
                                res.data?.msg || (res.data?.success ? t('backup.telegramNodeSuccess') : t('common.failed')),
                                res.data?.success !== false ? 'success' : 'error',
                              );
                            } catch (e: any) { toast(e.response?.data?.detail || t('common.failed'), 'error'); }
                          }}
                        >
                          <UIIcon name="backup" size={15} />
                        </button>
                      </div>
                    </div>
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
                  ...nodes.map((node) => ({ value: node.id, label: `${node.name} (${node.ip})` })),
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
