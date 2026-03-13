import React, { useEffect, useState } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';
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
  const { colors } = useTheme();
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
      setError('Failed to load node list');
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
      setError('Email is required');
      return;
    }

    const inboundIdNum = parseInt(inboundId, 10);
    if (Number.isNaN(inboundIdNum) || inboundIdNum < 1) {
      setError('A valid inbound ID is required');
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
        totalGB: parseInt(totalGB, 10) || 0,
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
      setError(err.response?.data?.detail || 'Failed to add client');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-3 mb-3" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
      <h6 className="mb-3 d-flex align-items-center gap-2" style={{ color: colors.accent }}>
        <UIIcon name="servers" size={15} />
        Add Client to Multiple Servers
      </h6>

      {error && (
        <div
          className="alert mb-3"
          style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}
        >
          {error}
        </div>
      )}

      <div className="panel-grid mb-3">
        <div className="panel-block panel-block--wide">
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title" style={{ color: colors.text.primary }}>Client Profile</h6>
              <p className="panel-block__hint" style={{ color: colors.text.secondary }}>
                Basic client settings in one place.
              </p>
            </div>
          </div>

          <div className="panel-field-grid">
            <div>
              <label className="form-label small" style={{ color: colors.text.secondary }}>
                Email
              </label>
              <input
                type="email"
                className="form-control form-control-sm"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: colors.text.secondary }}>
                Inbound ID
              </label>
              <input
                type="number"
                className="form-control form-control-sm"
                value={inboundId}
                onChange={(e) => setInboundId(e.target.value)}
                min={1}
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: colors.text.secondary }}>
                Total GB (0 = inf)
              </label>
              <input
                type="number"
                className="form-control form-control-sm"
                value={totalGB}
                onChange={(e) => setTotalGB(e.target.value)}
                min={0}
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: colors.text.secondary }}>
                Expiry Date
              </label>
              <input
                type="date"
                className="form-control form-control-sm"
                value={expiryTime}
                onChange={(e) => setExpiryTime(e.target.value)}
                style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
              />
            </div>
          </div>

          <div className="panel-grid panel-grid--compact mt-3">
            <div>
              <label className="form-label small" style={{ color: colors.text.secondary }}>
                Flow
              </label>
              <ChoiceChips
                options={FLOW_OPTIONS.map((option) => ({ value: option.value, label: option.label }))}
                value={flow}
                onChange={(value) => setFlow(value)}
                colors={colors}
              />
            </div>
            <div>
              <label className="form-label small" style={{ color: colors.text.secondary }}>
                Status
              </label>
              <ChoiceChips
                options={[
                  { value: true, label: 'Enabled' },
                  { value: false, label: 'Disabled' },
                ]}
                value={enable}
                onChange={(value) => setEnable(value)}
                colors={colors}
              />
            </div>
          </div>
        </div>

        <div className="panel-block panel-block--wide">
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title" style={{ color: colors.text.primary }}>Target Servers</h6>
              <p className="panel-block__hint" style={{ color: colors.text.secondary }}>
                Select one, many or all servers for this client.
              </p>
            </div>
            <div className="panel-inline-actions">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                onClick={handleSelectAll}
              >
                All
              </button>
              <button
                className="btn btn-sm"
                style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary }}
                onClick={handleSelectNone}
              >
                None
              </button>
            </div>
          </div>

          <div className="small mb-2" style={{ color: colors.text.secondary }}>
            {selectedNodeIds.size}/{nodes.length} selected
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
                    backgroundColor: active ? colors.accent : colors.bg.tertiary,
                    borderColor: active ? colors.accent : colors.border,
                    color: active ? colors.accentText : colors.text.primary,
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
              <span className="small" style={{ color: colors.text.secondary }}>No servers configured</span>
            )}
          </div>
        </div>
      </div>

      <div className="panel-inline-actions">
        <button
          className="btn btn-sm"
          style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
          onClick={handleSubmit}
          disabled={loading || selectedNodeIds.size === 0}
        >
          <span className="d-inline-flex align-items-center gap-1">
            <UIIcon name={loading ? 'spinner' : 'plus'} size={14} />
            {loading ? 'Adding...' : `Add to ${selectedNodeIds.size} Server${selectedNodeIds.size !== 1 ? 's' : ''}`}
          </span>
        </button>
      </div>

      {showResultModal && result && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
          <div className="modal-dialog modal-lg">
            <div
              className="modal-content"
              style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}
            >
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>
                  Add Client Results
                </h6>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => setShowResultModal(false)}
                />
              </div>
              <div className="modal-body">
                <div className="d-flex gap-3 mb-3">
                  <span className="badge fs-6" style={{ backgroundColor: colors.bg.tertiary, color: colors.text.primary }}>
                    Total: {result.summary.total}
                  </span>
                  <span className="badge fs-6" style={{ backgroundColor: colors.success }}>
                    <span className="d-inline-flex align-items-center gap-1"><UIIcon name="check" size={12} />{result.summary.successful}</span>
                  </span>
                  <span className="badge fs-6" style={{ backgroundColor: colors.danger }}>
                    <span className="d-inline-flex align-items-center gap-1"><UIIcon name="x" size={12} />{result.summary.failed}</span>
                  </span>
                </div>

                <div className="table-responsive">
                  <table className="table table-sm" style={{ color: colors.text.primary }}>
                    <thead>
                      <tr style={{ borderColor: colors.border }}>
                        <th style={{ color: colors.text.secondary }}>Server</th>
                        <th style={{ color: colors.text.secondary }}>Status</th>
                        <th style={{ color: colors.text.secondary }}>Details</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.results.map((item, index) => (
                        <tr key={index} style={{ borderColor: colors.border }}>
                          <td>{item.node}</td>
                          <td>
                            {item.success ? (
                              <span className="d-inline-flex align-items-center gap-1" style={{ color: colors.success }}>
                                <UIIcon name="check" size={13} />
                                Success
                              </span>
                            ) : (
                              <span className="d-inline-flex align-items-center gap-1" style={{ color: colors.danger }}>
                                <UIIcon name="x" size={13} />
                                Failed
                              </span>
                            )}
                          </td>
                          <td>{item.error && <small style={{ color: colors.danger }}>{item.error}</small>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                  onClick={() => setShowResultModal(false)}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
