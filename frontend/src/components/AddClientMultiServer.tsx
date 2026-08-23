import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';

interface NodeOption {
  id: number;
  name: string;
}

interface NodeResult {
  node: string;
  success: boolean;
  error?: string;
}

interface AddResult {
  results: NodeResult[];
  summary: { total: number; successful: number; failed: number };
}

const FLOW_OPTIONS = [
  { value: '', label: 'None' },
  { value: 'xtls-rprx-vision', label: 'vision' },
  { value: 'xtls-rprx-vision-udp443', label: 'vision-udp443' },
];

export const AddClientMultiServer: React.FC = () => {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [flow, setFlow] = useState('');
  const [inboundId, setInboundId] = useState('1');
  const [totalGB, setTotalGB] = useState('0');
  const [expiryTime, setExpiryTime] = useState('');
  const [enable, setEnable] = useState(true);
  const [nodes, setNodes] = useState<NodeOption[]>([]);
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<AddResult | null>(null);
  const [showResultModal, setShowResultModal] = useState(false);

  useEffect(() => {
    loadNodes();
  }, []);

  const loadNodes = async () => {
    try {
      const res = await api.get('/v1/nodes/list', { auth: getAuth() });
      const nodeList: NodeOption[] = res.data || [];
      setNodes(nodeList);
      setSelectedNodeIds(new Set(nodeList.map((node) => node.id)));
    } catch {
      setError(t('clients.addMulti.loadNodesFailed'));
    }
  };

  const handleSelectAll = () => setSelectedNodeIds(new Set(nodes.map((node) => node.id)));
  const handleSelectNone = () => setSelectedNodeIds(new Set());

  const toggleNode = (id: number) => {
    const next = new Set(selectedNodeIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedNodeIds(next);
  };

  const handleSubmit = async () => {
    if (!email.trim()) {
      setError(t('clients.addMulti.emailRequired'));
      return;
    }

    const inboundIdNum = parseInt(inboundId, 10);
    if (Number.isNaN(inboundIdNum) || inboundIdNum < 1) {
      setError(t('clients.addMulti.validInboundRequired'));
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    const expiryMs = expiryTime ? new Date(expiryTime).getTime() : 0;

    try {
      const payload: Record<string, unknown> = {
        email: email.trim(),
        flow,
        inbound_id: inboundIdNum,
        // The panel field is historically named totalGB but the v3 contract
        // carries the quota as bytes.  Keep the operator-facing input in GB.
        totalGB: Math.max(0, Math.round((parseFloat(totalGB) || 0) * 1024 ** 3)),
        expiryTime: expiryMs,
        enable,
      };

      if (selectedNodeIds.size < nodes.length) {
        payload.node_ids = Array.from(selectedNodeIds);
      }

      const res = await api.post('/v1/clients/add-to-nodes', payload, {
        auth: getAuth(),
      });

      setResult(res.data as AddResult);
      setShowResultModal(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || t('clients.addMulti.addFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-3 mb-3" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
      <h6 className="mb-3 d-flex align-items-center gap-2" style={{ color: 'var(--accent)' }}>
        <UIIcon name="servers" size={15} />
        {t('clients.addMulti.title')}
      </h6>

      {error && (
        <div
          className="alert mb-3"
          style={{ backgroundColor: 'color-mix(in srgb, var(--danger) 14%, transparent)', borderColor: 'var(--danger)', color: 'var(--danger)' }}
        >
          {error}
        </div>
      )}

      <div className="panel-grid mb-3">
        <div className="panel-block panel-block--wide">
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('clients.addMulti.profileTitle')}</h6>
              <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                {t('clients.addMulti.profileHint')}
              </p>
            </div>
          </div>

          <div className="panel-field-grid">
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                {t('clients.email')}
              </label>
              <input
                type="email"
                className="form-control form-control-sm"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t('clients.addMulti.emailPlaceholder')}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                {t('clients.inboundIdLabel')}
              </label>
              <input
                type="number"
                className="form-control form-control-sm"
                value={inboundId}
                onChange={(e) => setInboundId(e.target.value)}
                min={1}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                {t('clients.addMulti.totalGbLabel')}
              </label>
              <input
                type="number"
                className="form-control form-control-sm"
                value={totalGB}
                onChange={(e) => setTotalGB(e.target.value)}
                min={0}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                {t('clients.addMulti.expiryDate')}
              </label>
              <input
                type="date"
                className="form-control form-control-sm"
                value={expiryTime}
                onChange={(e) => setExpiryTime(e.target.value)}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
              />
            </div>
          </div>

          <div className="panel-grid panel-grid--compact mt-3">
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                {t('clients.flowLabel')}
              </label>
              <ChoiceChips
                options={FLOW_OPTIONS.map((option) => ({ value: option.value, label: option.label }))}
                value={flow}
                onChange={(value) => setFlow(value)}
                
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>
                Status
              </label>
              <ChoiceChips
                options={[
                  { value: true, label: t('clients.addMulti.enabled') },
                  { value: false, label: t('clients.disabled') },
                ]}
                value={enable}
                onChange={(value) => setEnable(value)}
                
              />
            </div>
          </div>
        </div>

        <div className="panel-block panel-block--wide">
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title" style={{ color: 'var(--text-primary)' }}>{t('clients.addMulti.targetServers')}</h6>
              <p className="panel-block__hint" style={{ color: 'var(--text-secondary)' }}>
                {t('clients.addMulti.targetServersHint')}
              </p>
            </div>
            <div className="panel-inline-actions">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                onClick={handleSelectAll}
              >
                {t('common.all')}
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                onClick={handleSelectNone}
              >
                {t('common.none')}
              </button>
            </div>
          </div>

          <div className="small mb-2" style={{ color: 'var(--text-secondary)' }}>
            {t('clients.addMulti.selectedServers', { selected: selectedNodeIds.size, total: nodes.length })}
          </div>
          <div className="panel-selection-grid">
            {nodes.map((node) => {
              const active = selectedNodeIds.has(node.id);
              return (
                <button
                  key={node.id}
                  type="button"
                  className="btn btn-sm text-start"
                  onClick={() => toggleNode(node.id)}
                  style={{
                    backgroundColor: active ? 'var(--accent)' : 'var(--bg-tertiary)',
                    borderColor: active ? 'var(--accent)' : 'var(--border-color)',
                    color: active ? '#000f14' : 'var(--text-primary)',
                    justifyContent: 'flex-start',
                  }}
                >
                  <span className="d-inline-flex align-items-center gap-1">
                    {active && <UIIcon name="check" size={12} />}
                    {node.name}
                  </span>
                </button>
              );
            })}
            {nodes.length === 0 && (
              <span className="small" style={{ color: 'var(--text-secondary)' }}>{t('clients.addMulti.noServers')}</span>
            )}
          </div>
        </div>
      </div>

      <div className="panel-inline-actions">
        <button
          className="btn btn-sm"
          style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
          onClick={handleSubmit}
          disabled={loading || selectedNodeIds.size === 0}
        >
          <span className="d-inline-flex align-items-center gap-1">
            <UIIcon name={loading ? 'spinner' : 'plus'} size={14} />
            {loading ? t('clients.addMulti.adding') : t('clients.addMulti.addToServers', { count: selectedNodeIds.size })}
          </span>
        </button>
      </div>

      {showResultModal && result && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
          <div className="modal-dialog modal-lg">
            <div
              className="modal-content"
              style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}
            >
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>
                  {t('clients.addMulti.resultsTitle')}
                </h6>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => setShowResultModal(false)}
                />
              </div>
              <div className="modal-body">
                <div className="d-flex gap-3 mb-3">
                  <span className="badge fs-6" style={{ backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-primary)' }}>
                    {t('common.total')}: {result.summary.total}
                  </span>
                  <span className="badge fs-6" style={{ backgroundColor: 'var(--success)' }}>
                    <span className="d-inline-flex align-items-center gap-1"><UIIcon name="check" size={12} />{result.summary.successful}</span>
                  </span>
                  <span className="badge fs-6" style={{ backgroundColor: 'var(--danger)' }}>
                    <span className="d-inline-flex align-items-center gap-1"><UIIcon name="x" size={12} />{result.summary.failed}</span>
                  </span>
                </div>

                <div className="table-responsive">
                  <table className="table table-sm" style={{ color: 'var(--text-primary)' }}>
                    <thead>
                      <tr style={{ borderColor: 'var(--border-color)' }}>
                        <th style={{ color: 'var(--text-secondary)' }}>{t('common.server')}</th>
                        <th style={{ color: 'var(--text-secondary)' }}>{t('common.status')}</th>
                        <th style={{ color: 'var(--text-secondary)' }}>{t('common.details')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.results.map((item, index) => (
                        <tr key={index} style={{ borderColor: 'var(--border-color)' }}>
                          <td>{item.node}</td>
                          <td>
                            {item.success ? (
                              <span className="d-inline-flex align-items-center gap-1" style={{ color: 'var(--success)' }}>
                                <UIIcon name="check" size={13} />
                                {t('common.success')}
                              </span>
                            ) : (
                              <span className="d-inline-flex align-items-center gap-1" style={{ color: 'var(--danger)' }}>
                                <UIIcon name="x" size={13} />
                                {t('common.failed')}
                              </span>
                            )}
                          </td>
                          <td>{item.error && <small style={{ color: 'var(--danger)' }}>{item.error}</small>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="modal-footer" style={{ borderColor: 'var(--border-color)' }}>
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                  onClick={() => setShowResultModal(false)}
                >
                  {t('common.close')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
