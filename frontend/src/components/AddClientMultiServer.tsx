import React, { useState, useEffect } from 'react';
import api from '../api';
import { useTheme } from '../contexts/ThemeContext';

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
  { value: '', label: 'None (empty)' },
  { value: 'xtls-rprx-vision', label: 'xtls-rprx-vision' },
  { value: 'xtls-rprx-vision-udp443', label: 'xtls-rprx-vision-udp443' },
];

export const AddClientMultiServer: React.FC = () => {
  const { colors } = useTheme();

  // Form state
  const [email, setEmail] = useState('');
  const [flow, setFlow] = useState('');
  const [inboundId, setInboundId] = useState('1');
  const [totalGB, setTotalGB] = useState('0');
  const [expiryTime, setExpiryTime] = useState('');
  const [enable, setEnable] = useState(true);

  // Node selection
  const [nodes, setNodes] = useState<NodeOption[]>([]);
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<number>>(new Set());

  // UI state
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
      // Select all by default
      setSelectedNodeIds(new Set(nodeList.map((n) => n.id)));
    } catch {
      setError('Failed to load node list');
    }
  };

  const handleSelectAll = () => setSelectedNodeIds(new Set(nodes.map((n) => n.id)));
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
    if (isNaN(inboundIdNum) || inboundIdNum < 1) {
      setError('A valid inbound ID is required');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    const expiryMs = expiryTime
      ? new Date(expiryTime).getTime()
      : 0;

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
      // If all nodes selected, omit node_ids so the backend adds to all servers

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
      <h6 className="mb-3" style={{ color: colors.accent }}>🌐 Add Client to Multiple Servers</h6>

      {error && (
        <div
          className="alert mb-3"
          style={{ backgroundColor: colors.danger + '22', borderColor: colors.danger, color: colors.danger }}
        >
          {error}
        </div>
      )}

      <div className="row g-2 mb-3">
        {/* Email */}
        <div className="col-md-4">
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

        {/* Flow */}
        <div className="col-md-3">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Flow
          </label>
          <select
            className="form-select form-select-sm"
            value={flow}
            onChange={(e) => setFlow(e.target.value)}
            style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
          >
            {FLOW_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Inbound ID */}
        <div className="col-md-2">
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

        {/* Total GB */}
        <div className="col-md-2">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Total GB (0 = ∞)
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

        {/* Expiry */}
        <div className="col-md-4">
          <label className="form-label small" style={{ color: colors.text.secondary }}>
            Expiry Date (optional)
          </label>
          <input
            type="date"
            className="form-control form-control-sm"
            value={expiryTime}
            onChange={(e) => setExpiryTime(e.target.value)}
            style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
          />
        </div>

        {/* Enable toggle */}
        <div className="col-md-2 d-flex align-items-end">
          <div className="form-check form-switch mb-1">
            <input
              className="form-check-input"
              type="checkbox"
              id="enableToggle"
              checked={enable}
              onChange={(e) => setEnable(e.target.checked)}
            />
            <label className="form-check-label small" htmlFor="enableToggle" style={{ color: colors.text.secondary }}>
              Enabled
            </label>
          </div>
        </div>
      </div>

      {/* Server selection */}
      <div className="mb-3">
        <div className="d-flex align-items-center gap-2 mb-2">
          <span className="small fw-semibold" style={{ color: colors.text.secondary }}>
            Servers ({selectedNodeIds.size}/{nodes.length} selected)
          </span>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary, padding: '0 8px', fontSize: '0.75rem' }}
            onClick={handleSelectAll}
          >
            All
          </button>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.primary, padding: '0 8px', fontSize: '0.75rem' }}
            onClick={handleSelectNone}
          >
            None
          </button>
        </div>
        <div className="d-flex flex-wrap gap-2">
          {nodes.map((node) => (
            <div
              key={node.id}
              className="form-check"
              style={{ minWidth: '150px' }}
            >
              <input
                className="form-check-input"
                type="checkbox"
                id={`node-${node.id}`}
                checked={selectedNodeIds.has(node.id)}
                onChange={() => toggleNode(node.id)}
              />
              <label
                className="form-check-label small"
                htmlFor={`node-${node.id}`}
                style={{ color: colors.text.primary }}
              >
                {node.name}
              </label>
            </div>
          ))}
          {nodes.length === 0 && (
            <span className="small" style={{ color: colors.text.secondary }}>No servers configured</span>
          )}
        </div>
      </div>

      <button
        className="btn btn-sm"
        style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
        onClick={handleSubmit}
        disabled={loading || selectedNodeIds.size === 0}
      >
        {loading ? '⏳ Adding...' : `➕ Add to ${selectedNodeIds.size} Server${selectedNodeIds.size !== 1 ? 's' : ''}`}
      </button>

      {/* Results Modal */}
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
                {/* Summary */}
                <div className="d-flex gap-3 mb-3">
                  <span className="badge fs-6" style={{ backgroundColor: colors.bg.tertiary, color: colors.text.primary }}>
                    Total: {result.summary.total}
                  </span>
                  <span className="badge fs-6" style={{ backgroundColor: colors.success }}>
                    ✓ {result.summary.successful}
                  </span>
                  <span className="badge fs-6" style={{ backgroundColor: colors.danger }}>
                    ✗ {result.summary.failed}
                  </span>
                </div>

                {/* Per-server results */}
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
                      {result.results.map((r, i) => (
                        <tr key={i} style={{ borderColor: colors.border }}>
                          <td>{r.node}</td>
                          <td>
                            {r.success ? (
                              <span style={{ color: colors.success }}>✓ Success</span>
                            ) : (
                              <span style={{ color: colors.danger }}>✗ Failed</span>
                            )}
                          </td>
                          <td>
                            {r.error && (
                              <small style={{ color: colors.danger }}>{r.error}</small>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: '#ffffff' }}
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

function getAuth() {
  if (typeof window !== 'undefined') {
    const auth = localStorage.getItem('sub_auth');
    if (auth) {
      const parsed = JSON.parse(auth);
      return { username: parsed.user, password: parsed.password };
    }
  }
  return { username: '', password: '' };
}
