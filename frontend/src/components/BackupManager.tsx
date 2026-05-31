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


export const BackupManager: React.FC = () => {
  const { toast } = useToast();
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [backupProgress, setBackupProgress] = useState<Record<number, string>>({});
  const [selectedNode, setSelectedNode] = useState<number | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [sortField, setSortField] = useState<'name' | 'address' | 'status'>('name');
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

  const applySortFromHeader = (field: 'name' | 'address' | 'status') => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortField(field);
    setSortDirection(field === 'status' ? 'desc' : 'asc');
  };

  const sortIndicator = (field: 'name' | 'address' | 'status') =>
    sortField === field ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : '';

  return (
    <div className="backup-manager">
      <div className="card p-3 mb-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0 d-flex align-items-center gap-2" style={{ color: 'var(--accent)' }}>
            <UIIcon name="backup" size={16} />
            {t('backup.backupRestore')}
          </h5>
        </div>

        {error && (
          <div className="alert alert-danger">
            {error}
          </div>
        )}

        <div className="panel-grid">
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('common.actions')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('backup.actionsHint')}
                </p>
              </div>
            </div>
            <div className="panel-inline-actions">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                onClick={downloadAllBackups}
                disabled={loading || nodes.length === 0}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="download" size={14} />
                  {t('backup.downloadAllBackups')}
                </span>
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
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
                <span className="d-inline-flex align-items-center gap-1">
                  {t('backup.telegramAll')}
                </span>
              </button>
            </div>
          </div>
          <div className="panel-block panel-block--wide">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('backup.notes')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('backup.notesHint')}
                </p>
              </div>
            </div>
            <div className="alert mb-0" style={{ backgroundColor: 'color-mix(in srgb, var(--info) 14%, transparent)', borderColor: 'var(--info)', color: 'var(--text-primary)' }}>
              <strong>{t('backup.important')}:</strong> {t('backup.importantText')}
            </div>
          </div>
        </div>
      </div>

      {/* Backup List */}
      <div className="card p-3 mb-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        <div className="d-flex justify-content-between align-items-center mb-3 gap-2">
          <h6 className="mb-0 d-flex align-items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <UIIcon name="download" size={14} />
            {t('backup.downloadBackups')}
          </h6>
          <div className="small" style={{ color: 'var(--text-secondary)' }}>
            {t('backup.sortHint')}
          </div>
        </div>
        
        {nodes.length === 0 ? (
          <p className="text-center py-3" style={{ color: 'var(--text-secondary)' }}>
            {t('backup.noServers')}
          </p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-hover" style={{ color: 'var(--text-primary)' }}>
              <thead>
                <tr style={{ borderColor: 'var(--border-color)' }}>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('name')}>
                      {t('backup.node')}{sortIndicator('name')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('address')}>
                      {t('backup.address')}{sortIndicator('address')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applySortFromHeader('status')}>
                      {t('common.status')}{sortIndicator('status')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>{t('backup.action')}</th>
                </tr>
              </thead>
              <tbody>
                {sortedNodes.map((node) => (
                  <tr key={node.id} style={{ borderColor: 'var(--border-color)' }}>
                    <td>
                      <strong style={{ color: 'var(--text-primary)' }}>{node.name}</strong>
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>
                      {node.ip}:{node.port}
                    </td>
                    <td>
                      <span className="d-inline-flex align-items-center justify-content-center" style={{ minHeight: '18px' }}>
                        {getProgressIcon(node.id)}
                      </span>
                    </td>
                    <td>
                      <div className="d-flex gap-1">
                        <button
                          className="btn btn-sm"
                          style={{ backgroundColor: 'var(--success)', borderColor: 'var(--success)', color: '#ffffff' }}
                          onClick={() => downloadBackup(node.id, node.name)}
                          disabled={loading || backupProgress[node.id] === 'downloading'}
                        >
                          <span className="d-inline-flex align-items-center gap-1">
                            <UIIcon name="download" size={14} />
                            {t('backup.download')}
                          </span>
                        </button>
                        <button
                          className="btn btn-sm"
                          style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                          title={t('backup.telegramNodeTitle')}
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
                          {t('backup.telegramIcon')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Restore Section */}
      <div className="card p-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        <h6 className="mb-3 d-flex align-items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <UIIcon name="upload" size={14} />
          {t('backup.restoreFromBackup')}
        </h6>
        
        <div className="alert alert-warning">
          <strong>{t('backup.warning')}:</strong> {t('backup.restoreWarning')}
        </div>

        <div className="panel-grid">
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('backup.targetNode')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('backup.targetNodeHint')}
                </p>
              </div>
            </div>
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
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('backup.backupFile')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('backup.backupFileHint')}
                </p>
              </div>
            </div>
            <input
              type="file"
              className="form-control"
              accept=".db,.sqlite,.sqlite3"
              onChange={handleFileChange}
              style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
            />
          </div>
          <div className="panel-block">
            <div className="panel-block__header">
              <div>
                <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('backup.restore')}</h6>
                <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                  {t('backup.restoreHint')}
                </p>
              </div>
            </div>
            <button
              className="btn w-100"
              style={{ backgroundColor: 'var(--warning)', borderColor: 'var(--warning)', color: 'var(--text-primary)' }}
              onClick={importBackup}
              disabled={loading || !selectedNode || !importFile}
            >
              <span className="d-inline-flex align-items-center gap-1">
                <UIIcon name="upload" size={14} />
                {t('backup.restoreBackup')}
              </span>
            </button>
          </div>
        </div>

        {importFile && (
          <div className="mt-3 p-2" style={{ backgroundColor: 'var(--bg-tertiary)', borderRadius: '4px' }}>
            <small style={{ color: 'var(--text-secondary)' }}>
              {t('backup.selectedFile')}: <strong style={{ color: 'var(--text-primary)' }}>{importFile.name}</strong> ({formatBytes(importFile.size)})
            </small>
          </div>
        )}
      </div>

      {/* Automation Info */}
      <div className="card p-3 mt-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
        <h6 className="mb-3 d-flex align-items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <UIIcon name="backup" size={14} />
          {t('backup.automatedBackups')}
        </h6>
        <p style={{ color: 'var(--text-secondary)' }}>
          {t('backup.automatedBackupsHint')}
        </p>
        <div className="p-3" style={{ backgroundColor: 'var(--bg-tertiary)', borderRadius: '4px', fontFamily: 'monospace' }}>
          <code style={{ color: 'var(--text-primary)' }}>
            0 3 * * * curl -u username:password https://your-domain/api/v1/backup/all -o /backups/backup_$(date +\%Y\%m\%d).zip
          </code>
        </div>
        <p className="mt-2 mb-0 small" style={{ color: 'var(--text-secondary)' }}>
          {t('backup.automatedBackupsExampleHint')}
        </p>
      </div>
    </div>
  );
};
