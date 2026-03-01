import React, { useState, useEffect } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
import { UIIcon } from './UIIcon';

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
}


export const BackupManager: React.FC = () => {
  const { colors } = useTheme();
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
      setError('Failed to load nodes');
    }
  };

  const downloadBackup = async (nodeId: number, nodeName: string) => {
    setLoading(true);
    setError('');
    setBackupProgress({ ...backupProgress, [nodeId]: 'downloading' });

    try {
      const res = await api.get(`/v1/backup/${nodeId}`, {
        auth: getAuth(),
        responseType: 'blob'
      });

      const blob = new Blob([res.data], { type: 'application/x-sqlite3' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `backup_${nodeName}_${new Date().toISOString().split('T')[0]}.db`;
      a.click();
      window.URL.revokeObjectURL(url);

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
    if (!window.confirm('Download backups from all servers?')) return;

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

      alert('All backups downloaded successfully');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to download all backups');
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
      alert('Please select a node and a backup file');
      return;
    }

    if (!window.confirm('This will REPLACE the current database. Are you sure?')) {
      return;
    }

    setLoading(true);
    setError('');

    const formData = new FormData();
    formData.append('file', importFile);

    try {
      await api.post(`/v1/backup/${selectedNode}/import`, formData, {
        auth: getAuth(),
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });

      alert('Database imported successfully. Please restart core service.');
      setImportFile(null);
      setSelectedNode(null);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to import backup');
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

  return (
    <div className="backup-manager">
      <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0 d-flex align-items-center gap-2" style={{ color: colors.accent }}>
            <UIIcon name="backup" size={16} />
            Backup & Restore
          </h5>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
            onClick={downloadAllBackups}
            disabled={loading || nodes.length === 0}
          >
            <span className="d-inline-flex align-items-center gap-1">
              <UIIcon name="download" size={14} />
              Download All Backups
            </span>
          </button>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
            {error}
          </div>
        )}

        <div className="alert" style={{ backgroundColor: colors.info + '22', borderColor: colors.info, color: colors.text.primary }}>
          <strong>Important:</strong> Backups contain the complete database including all client configurations.
          Make sure to store backups securely. When restoring, the core service may need to be restarted.
        </div>
      </div>

      {/* Backup List */}
      <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3 gap-2">
          <h6 className="mb-0 d-flex align-items-center gap-2" style={{ color: colors.text.primary }}>
            <UIIcon name="download" size={14} />
            Download Backups
          </h6>
          <div className="d-flex gap-2">
            <select
              className="form-select form-select-sm"
              value={sortField}
              onChange={(e) => setSortField(e.target.value as 'name' | 'address' | 'status')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, minWidth: 130 }}
            >
              <option value="name">Sort: Node</option>
              <option value="address">Sort: Address</option>
              <option value="status">Sort: Status</option>
            </select>
            <select
              className="form-select form-select-sm"
              value={sortDirection}
              onChange={(e) => setSortDirection(e.target.value as 'asc' | 'desc')}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, minWidth: 90 }}
            >
              <option value="asc">Asc</option>
              <option value="desc">Desc</option>
            </select>
          </div>
        </div>
        
        {nodes.length === 0 ? (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>
            No servers configured. Add servers in the Servers tab.
          </p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-hover" style={{ color: colors.text.primary }}>
              <thead>
                <tr style={{ borderColor: colors.border }}>
                  <th style={{ color: colors.text.secondary }}>Node</th>
                  <th style={{ color: colors.text.secondary }}>Address</th>
                  <th style={{ color: colors.text.secondary }}>Status</th>
                  <th style={{ color: colors.text.secondary }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {sortedNodes.map((node) => (
                  <tr key={node.id} style={{ borderColor: colors.border }}>
                    <td>
                      <strong style={{ color: colors.text.primary }}>{node.name}</strong>
                    </td>
                    <td style={{ color: colors.text.secondary }}>
                      {node.ip}:{node.port}
                    </td>
                    <td>
                      <span className="d-inline-flex align-items-center justify-content-center" style={{ minHeight: '18px' }}>
                        {getProgressIcon(node.id)}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn-sm"
                        style={{ backgroundColor: colors.success, borderColor: colors.success, color: '#ffffff' }}
                        onClick={() => downloadBackup(node.id, node.name)}
                        disabled={loading || backupProgress[node.id] === 'downloading'}
                      >
                        <span className="d-inline-flex align-items-center gap-1">
                          <UIIcon name="download" size={14} />
                          Download
                        </span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Restore Section */}
      <div className="card p-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <h6 className="mb-3 d-flex align-items-center gap-2" style={{ color: colors.text.primary }}>
          <UIIcon name="upload" size={14} />
          Restore from Backup
        </h6>
        
        <div className="alert alert-warning" style={{ backgroundColor: colors.warning + '22', borderColor: colors.warning, color: colors.text.primary }}>
          <strong>Warning:</strong> Restoring a backup will REPLACE the current database. Make sure you have a recent backup before proceeding.
        </div>

        <div className="row g-3">
          <div className="col-md-4">
            <label className="form-label small" style={{ color: colors.text.secondary }}>
              Select Node
            </label>
            <select
              className="form-select"
              value={selectedNode || ''}
              onChange={(e) => setSelectedNode(parseInt(e.target.value))}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">Choose node...</option>
              {nodes.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.name} ({node.ip})
                </option>
              ))}
            </select>
          </div>
          <div className="col-md-5">
            <label className="form-label small" style={{ color: colors.text.secondary }}>
              Select Backup File (.db)
            </label>
            <input
              type="file"
              className="form-control"
              accept=".db,.sqlite,.sqlite3"
              onChange={handleFileChange}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            />
          </div>
          <div className="col-md-3 d-flex align-items-end">
            <button
              className="btn w-100"
              style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: colors.text.primary }}
              onClick={importBackup}
              disabled={loading || !selectedNode || !importFile}
            >
              <span className="d-inline-flex align-items-center gap-1">
                <UIIcon name="upload" size={14} />
                Restore Backup
              </span>
            </button>
          </div>
        </div>

        {importFile && (
          <div className="mt-3 p-2" style={{ backgroundColor: colors.bg.tertiary, borderRadius: '4px' }}>
            <small style={{ color: colors.text.secondary }}>
              Selected file: <strong style={{ color: colors.text.primary }}>{importFile.name}</strong> ({formatBytes(importFile.size)})
            </small>
          </div>
        )}
      </div>

      {/* Automation Info */}
      <div className="card p-3 mt-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <h6 className="mb-3 d-flex align-items-center gap-2" style={{ color: colors.text.primary }}>
          <UIIcon name="backup" size={14} />
          Automated Backups
        </h6>
        <p style={{ color: colors.text.secondary }}>
          For automated backup scheduling, you can set up a cron job on your server:
        </p>
        <div className="p-3" style={{ backgroundColor: colors.bg.tertiary, borderRadius: '4px', fontFamily: 'monospace' }}>
          <code style={{ color: colors.text.primary }}>
            0 3 * * * curl -u username:password https://your-domain/api/v1/backup/all -o /backups/backup_$(date +\%Y\%m\%d).zip
          </code>
        </div>
        <p className="mt-2 mb-0 small" style={{ color: colors.text.secondary }}>
          This example runs daily at 3 AM and saves all backups to /backups directory.
        </p>
      </div>
    </div>
  );
};
