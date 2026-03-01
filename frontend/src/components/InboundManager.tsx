import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
import { getAuth } from '../auth';
import { UIIcon } from './UIIcon';

interface Inbound {
  id: number;
  node_name: string;
  node_ip: string;
  protocol: string;
  port: number;
  remark: string;
  enable: boolean;
  security: string;
  is_reality: boolean;
}

interface NodeInfo {
  id: number;
  name: string;
}

interface InboundManagerProps {
  onReload?: () => void;
}

const inboundKey = (ib: Inbound) => `${ib.node_name}:${ib.id}`;

export const InboundManager: React.FC<InboundManagerProps> = ({ onReload }) => {
  const { colors } = useTheme();
  const { t } = useTranslation();

  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [filteredInbounds, setFilteredInbounds] = useState<Inbound[]>([]);
  const [nodeNameToId, setNodeNameToId] = useState<Record<string, number>>({});

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [filterProtocol, setFilterProtocol] = useState('');
  const [filterSecurity, setFilterSecurity] = useState('');
  const [filterNode, setFilterNode] = useState('');

  const [showCloneModal, setShowCloneModal] = useState(false);
  const [cloneSource, setCloneSource] = useState<Inbound | null>(null);
  const [cloneRemark, setCloneRemark] = useState('');
  const [clonePort, setClonePort] = useState('');

  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [batchRemark, setBatchRemark] = useState('');
  const [batchEnableMode, setBatchEnableMode] = useState<'none' | 'enable' | 'disable'>('none');

  useEffect(() => {
    loadInbounds();
  }, []);

  useEffect(() => {
    let filtered = inbounds;

    if (filterProtocol) {
      filtered = filtered.filter((ib) => ib.protocol === filterProtocol);
    }

    if (filterSecurity) {
      filtered = filtered.filter((ib) => ib.security === filterSecurity);
    }

    if (filterNode) {
      filtered = filtered.filter((ib) => ib.node_name === filterNode);
    }

    setFilteredInbounds(filtered);
  }, [inbounds, filterProtocol, filterSecurity, filterNode]);

  const loadInbounds = async () => {
    setLoading(true);
    setError('');

    try {
      const [inboundsRes, nodesRes] = await Promise.all([
        api.get('/v1/inbounds', { auth: getAuth() }),
        api.get('/v1/nodes', { auth: getAuth() }),
      ]);

      const nodes: NodeInfo[] = nodesRes.data || [];
      const nameMap: Record<string, number> = {};
      nodes.forEach((n) => {
        nameMap[n.name] = n.id;
      });

      setNodeNameToId(nameMap);
      setInbounds(inboundsRes.data.inbounds || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || t('messages.operationFailed'));
    } finally {
      setLoading(false);
    }
  };

  const selectedInbounds = inbounds.filter((ib) => selectedKeys.has(inboundKey(ib)));
  const selectedInboundIds = Array.from(new Set(selectedInbounds.map((ib) => ib.id)));
  const selectedNodeIds = Array.from(
    new Set(selectedInbounds.map((ib) => nodeNameToId[ib.node_name]).filter((id): id is number => Number.isInteger(id)))
  );

  const toggleSelectAllFiltered = () => {
    const next = new Set(selectedKeys);
    const filteredKeys = filteredInbounds.map((ib) => inboundKey(ib));
    const allSelected = filteredKeys.length > 0 && filteredKeys.every((k) => next.has(k));

    if (allSelected) {
      filteredKeys.forEach((k) => next.delete(k));
    } else {
      filteredKeys.forEach((k) => next.add(k));
    }

    setSelectedKeys(next);
  };

  const toggleSelectOne = (ib: Inbound) => {
    const key = inboundKey(ib);
    const next = new Set(selectedKeys);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setSelectedKeys(next);
  };

  const clearSelection = () => {
    setSelectedKeys(new Set());
  };

  const handleDelete = async (inbound: Inbound) => {
    if (!window.confirm(`${t('inbounds.confirmDeleteSingle')} \"${inbound.remark || inbound.id}\"?`)) return;

    const nodeId = nodeNameToId[inbound.node_name];
    if (!nodeId) {
      setError(t('inbounds.nodeResolveFailed'));
      return;
    }

    setLoading(true);
    try {
      await api.delete(`/v1/inbounds/${inbound.id}`, {
        params: { node_id: nodeId },
        auth: getAuth(),
      });

      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.deleteFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleCloneClick = (inbound: Inbound) => {
    setCloneSource(inbound);
    setCloneRemark(`${inbound.remark} (Clone)`);
    setClonePort(String(inbound.port));
    setShowCloneModal(true);
  };

  const handleCloneSubmit = async () => {
    if (!cloneSource) return;

    const sourceNodeId = nodeNameToId[cloneSource.node_name];
    if (!sourceNodeId) {
      setError(t('inbounds.nodeResolveFailed'));
      return;
    }

    setLoading(true);
    setError('');

    try {
      const payload = {
        source_node_id: sourceNodeId,
        source_inbound_id: cloneSource.id,
        target_node_ids: null,
        modifications: {
          remark: cloneRemark,
          port: parseInt(clonePort, 10) || cloneSource.port,
        },
      };

      await api.post('/v1/inbounds/clone', payload, {
        auth: getAuth(),
      });

      setShowCloneModal(false);
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.cloneFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchEnable = async (enable: boolean) => {
    if (selectedInboundIds.length === 0 || selectedNodeIds.length === 0) return;

    setLoading(true);
    setError('');

    try {
      await api.post(
        '/v1/inbounds/batch-enable',
        {
          node_ids: selectedNodeIds,
          inbound_ids: selectedInboundIds,
          enable,
        },
        { auth: getAuth() }
      );

      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.batchEnableFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchUpdate = async () => {
    if (selectedInboundIds.length === 0 || selectedNodeIds.length === 0) return;

    const updates: Record<string, any> = {};
    if (batchRemark.trim()) updates.remark = batchRemark.trim();
    if (batchEnableMode === 'enable') updates.enable = true;
    if (batchEnableMode === 'disable') updates.enable = false;

    if (Object.keys(updates).length === 0) {
      setError(t('inbounds.batchUpdateEmpty'));
      return;
    }

    setLoading(true);
    setError('');

    try {
      await api.post(
        '/v1/inbounds/batch-update',
        {
          node_ids: selectedNodeIds,
          inbound_ids: selectedInboundIds,
          updates,
        },
        { auth: getAuth() }
      );

      setBatchRemark('');
      setBatchEnableMode('none');
      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.batchUpdateFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchDelete = async () => {
    if (selectedInboundIds.length === 0 || selectedNodeIds.length === 0) return;

    if (!window.confirm(t('inbounds.confirmBatchDelete', { count: selectedKeys.size }))) return;

    setLoading(true);
    setError('');

    try {
      await api.post(
        '/v1/inbounds/batch-delete',
        {
          node_ids: selectedNodeIds,
          inbound_ids: selectedInboundIds,
        },
        { auth: getAuth() }
      );

      clearSelection();
      await loadInbounds();
      onReload?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('inbounds.batchDeleteFailed'));
    } finally {
      setLoading(false);
    }
  };

  const protocols = Array.from(new Set(inbounds.map((ib) => ib.protocol)));
  const securities = Array.from(new Set(inbounds.map((ib) => ib.security)));
  const nodes = Array.from(new Set(inbounds.map((ib) => ib.node_name)));

  const allFilteredSelected =
    filteredInbounds.length > 0 && filteredInbounds.every((ib) => selectedKeys.has(inboundKey(ib)));

  return (
    <div className="inbound-manager">
      <div className="card p-3 mb-4" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h5 className="mb-0 d-flex align-items-center gap-2" style={{ color: colors.accent }}>
            <UIIcon name="inbounds" size={16} />
            {t('inbounds.title')}
          </h5>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
            onClick={loadInbounds}
            disabled={loading}
          >
            <span className="d-inline-flex align-items-center gap-1">
              <UIIcon name="refresh" size={14} />
              {t('common.refresh')}
            </span>
          </button>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}>
            {error}
          </div>
        )}

        <div className="row g-2 mb-3">
          <div className="col-md-3">
            <select
              className="form-select form-select-sm"
              value={filterProtocol}
              onChange={(e) => setFilterProtocol(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">{t('inbounds.allProtocols')}</option>
              {protocols.map((p) => (
                <option key={p} value={p}>{p.toUpperCase()}</option>
              ))}
            </select>
          </div>
          <div className="col-md-3">
            <select
              className="form-select form-select-sm"
              value={filterSecurity}
              onChange={(e) => setFilterSecurity(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">{t('inbounds.allSecurity')}</option>
              {securities.map((s) => (
                <option key={s} value={s}>{s || 'none'}</option>
              ))}
            </select>
          </div>
          <div className="col-md-3">
            <select
              className="form-select form-select-sm"
              value={filterNode}
              onChange={(e) => setFilterNode(e.target.value)}
              style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
            >
              <option value="">{t('inbounds.allNodes')}</option>
              {nodes.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
          <div className="col-md-3">
            <button
              className="btn btn-sm w-100"
              style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
              onClick={() => {
                setFilterProtocol('');
                setFilterSecurity('');
                setFilterNode('');
              }}
            >
              {t('inbounds.clearFilters')}
            </button>
          </div>
        </div>

        <div className="card p-2 mb-3" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border }}>
          <div className="row g-2 align-items-end">
            <div className="col-lg-3 col-md-6">
              <div className="small" style={{ color: colors.text.secondary }}>
                {t('inbounds.selectedCount', { count: selectedKeys.size })}
              </div>
              <div className="d-flex gap-2 mt-1">
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                  onClick={toggleSelectAllFiltered}
                >
                  {allFilteredSelected ? t('common.deselectAll') : t('common.selectAll')}
                </button>
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                  onClick={clearSelection}
                  disabled={selectedKeys.size === 0}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </div>

            <div className="col-lg-3 col-md-6">
              <label className="form-label small mb-1" style={{ color: colors.text.secondary }}>{t('inbounds.batchRemark')}</label>
              <input
                className="form-control form-control-sm"
                value={batchRemark}
                onChange={(e) => setBatchRemark(e.target.value)}
                placeholder={t('inbounds.batchRemarkPlaceholder')}
                style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}
              />
            </div>

            <div className="col-lg-2 col-md-6">
              <label className="form-label small mb-1" style={{ color: colors.text.secondary }}>{t('inbounds.batchEnableMode')}</label>
              <select
                className="form-select form-select-sm"
                value={batchEnableMode}
                onChange={(e) => setBatchEnableMode(e.target.value as 'none' | 'enable' | 'disable')}
                style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border, color: colors.text.primary }}
              >
                <option value="none">{t('common.no')}</option>
                <option value="enable">{t('inbounds.batchEnable')}</option>
                <option value="disable">{t('inbounds.batchDisable')}</option>
              </select>
            </div>

            <div className="col-lg-4 col-md-12 d-flex gap-2 flex-wrap">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.success, borderColor: colors.success, color: '#fff' }}
                onClick={() => handleBatchEnable(true)}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchEnable')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.warning, borderColor: colors.warning, color: colors.text.primary }}
                onClick={() => handleBatchEnable(false)}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchDisable')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.info, borderColor: colors.info, color: '#fff' }}
                onClick={handleBatchUpdate}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchUpdate')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: '#fff' }}
                onClick={handleBatchDelete}
                disabled={loading || selectedKeys.size === 0}
              >
                {t('inbounds.batchDelete')}
              </button>
            </div>
          </div>
        </div>

        {loading && <div className="text-center py-3"><div className="spinner-border spinner-border-sm" role="status"></div></div>}

        {!loading && filteredInbounds.length === 0 && (
          <p className="text-center py-3" style={{ color: colors.text.secondary }}>{t('messages.noDataAvailable')}</p>
        )}

        <div className="table-responsive">
          <table className="table table-sm table-hover" style={{ color: colors.text.primary }}>
            <thead>
              <tr style={{ borderColor: colors.border }}>
                <th style={{ color: colors.text.secondary, width: '40px' }}>
                  <input
                    type="checkbox"
                    checked={allFilteredSelected}
                    onChange={toggleSelectAllFiltered}
                    aria-label="Select all"
                  />
                </th>
                <th style={{ color: colors.text.secondary }}>{t('common.name')}</th>
                <th style={{ color: colors.text.secondary }}>{t('inbounds.remark')}</th>
                <th style={{ color: colors.text.secondary }}>{t('inbounds.protocol')}</th>
                <th style={{ color: colors.text.secondary }}>{t('inbounds.port')}</th>
                <th style={{ color: colors.text.secondary }}>{t('inbounds.security')}</th>
                <th style={{ color: colors.text.secondary }}>{t('common.status')}</th>
                <th style={{ color: colors.text.secondary }}>{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {filteredInbounds.map((ib) => (
                <tr key={inboundKey(ib)} style={{ borderColor: colors.border }}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedKeys.has(inboundKey(ib))}
                      onChange={() => toggleSelectOne(ib)}
                      aria-label={`Select ${ib.remark || ib.id}`}
                    />
                  </td>
                  <td>
                    <span className="badge" style={{ backgroundColor: colors.bg.tertiary, color: colors.text.primary }}>{ib.node_name}</span>
                  </td>
                  <td>{ib.remark || <span style={{ color: colors.text.secondary }}>-</span>}</td>
                  <td>
                    <span className="badge" style={{ backgroundColor: colors.accent }}>
                      {ib.protocol.toUpperCase()}
                    </span>
                  </td>
                  <td className="text-monospace">{ib.port}</td>
                  <td>
                    {ib.is_reality && <span className="badge" style={{ backgroundColor: colors.success }}>Reality</span>}
                    {!ib.is_reality && ib.security && <span className="badge" style={{ backgroundColor: colors.info }}>{ib.security}</span>}
                    {!ib.security && <span style={{ color: colors.text.secondary }}>-</span>}
                  </td>
                  <td>
                    {ib.enable ? (
                      <span style={{ color: colors.success }}>● {t('common.enabled')}</span>
                    ) : (
                      <span style={{ color: colors.text.secondary }}>○ {t('common.disabled')}</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm me-1"
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                      onClick={() => handleCloneClick(ib)}
                      title={t('inbounds.cloneInbound')}
                    >
                      <UIIcon name="copy" size={14} />
                    </button>
                    <button
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.danger, borderColor: colors.danger, color: '#ffffff' }}
                      onClick={() => handleDelete(ib)}
                      title={t('inbounds.deleteInbound')}
                    >
                      <UIIcon name="trash" size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-2 small" style={{ color: colors.text.secondary }}>
          {t('inbounds.showingCount', { filtered: filteredInbounds.length, total: inbounds.length })}
        </div>
      </div>

      {showCloneModal && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
          <div className="modal-dialog">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>
                  {t('inbounds.cloneInbound')}: {cloneSource?.remark || cloneSource?.id}
                </h6>
                <button
                  type="button"
                  className="btn-close btn-close-white"
                  onClick={() => setShowCloneModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <div className="mb-3">
                  <label className="form-label small" style={{ color: colors.text.secondary }}>{t('inbounds.newRemark')}</label>
                  <input
                    type="text"
                    className="form-control"
                    value={cloneRemark}
                    onChange={(e) => setCloneRemark(e.target.value)}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                </div>
                <div className="mb-3">
                  <label className="form-label small" style={{ color: colors.text.secondary }}>{t('inbounds.newPortOptional')}</label>
                  <input
                    type="number"
                    className="form-control"
                    value={clonePort}
                    onChange={(e) => setClonePort(e.target.value)}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                </div>
                <p className="small" style={{ color: colors.text.secondary }}>
                  {t('inbounds.cloneHint')}
                </p>
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button
                  className="btn"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                  onClick={() => setShowCloneModal(false)}
                  disabled={loading}
                >
                  {t('common.cancel')}
                </button>
                <button
                  className="btn"
                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
                  onClick={handleCloneSubmit}
                  disabled={loading}
                >
                  {loading ? t('inbounds.cloning') : t('inbounds.cloneInbound')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
