import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  checkNodeConnection,
  createNode,
  createNodesBounded,
  dispatchNodesChanged,
  updateNode,
  type NodeRecord,
} from '../api/nodes';
import { useTheme } from '../contexts/ThemeContext';
import { UIIcon } from './UIIcon';
import { useToast } from './Toast';
import {
  buildNodeEditPayload,
  buildPanelUrl,
  emptyNodeConnectionForm,
  nodeToEditForm,
  type NodeConnectionFormData,
} from './nodeEditForm';

type Node = NodeRecord;

interface BatchPreviewRow {
  name: string;
  url: string;
  user?: string;
  password?: string;
  bearer_token?: string;
}

interface NodeManagerProps {
  onReload: () => void;
  showIntake?: boolean;
  showIntakeStrip?: boolean;
  openIntakeSignal?: number;
  editNode?: NodeRecord | null;
  openEditSignal?: number;
}

export const NodeManager: React.FC<NodeManagerProps> = ({
  onReload,
  showIntake = true,
  showIntakeStrip = false,
  openIntakeSignal,
  editNode,
  openEditSignal,
}) => {
  const { colors } = useTheme();
  const { toast } = useToast();
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [addMode, setAddMode] = useState<'form' | 'batch'>('form');
  const [formData, setFormData] = useState<NodeConnectionFormData>(emptyNodeConnectionForm);
  const [batchText, setBatchText] = useState('');
  const [batchPreview, setBatchPreview] = useState<BatchPreviewRow[]>([]);
  const [batchAdded, setBatchAdded] = useState(false);
  const [error, setErrorRaw] = useState('');
  const [success, setSuccessRaw] = useState('');
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setError = useCallback((msg: string) => {
    setErrorRaw(msg);
    if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    if (msg) errorTimerRef.current = setTimeout(() => setErrorRaw(''), 6000);
  }, []);

  const setSuccess = useCallback((msg: string) => {
    setSuccessRaw(msg);
    if (successTimerRef.current) clearTimeout(successTimerRef.current);
    if (msg) successTimerRef.current = setTimeout(() => setSuccessRaw(''), 5000);
  }, []);

  const resetIntake = useCallback(() => {
    setFormData(emptyNodeConnectionForm());
    setBatchText('');
    setBatchPreview([]);
    setBatchAdded(false);
    setAddMode('form');
  }, []);

  const closeIntakeAndNotify = useCallback(() => {
    setShowForm(false);
    window.setTimeout(() => dispatchNodesChanged({ action: 'create' }), 0);
  }, []);

  const [editingNode, setEditingNode] = useState<Node | null>(null);
  const [editingForm, setEditingForm] = useState<NodeConnectionFormData>(emptyNodeConnectionForm);
  const [showEditModal, setShowEditModal] = useState(false);
  const [checkingConnection, setCheckingConnection] = useState(false);
  const showIntakeController = showIntake || showIntakeStrip;

  useEffect(() => {
    if (openIntakeSignal === undefined || openIntakeSignal <= 0) return;
    resetIntake();
    setSuccess('');
    setError('');
    setShowForm(true);
  }, [openIntakeSignal, resetIntake, setError, setSuccess]);

  useEffect(() => {
    if (openEditSignal === undefined || openEditSignal <= 0 || !editNode) return;
    setEditingNode(editNode);
    setEditingForm(nodeToEditForm(editNode));
    setError('');
    setSuccess('');
    setShowEditModal(true);
  }, [editNode, openEditSignal, setError, setSuccess]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');

    const panelUrl = buildPanelUrl(formData.url, formData.port);
    if (!panelUrl) {
      setError(t('nodes.fillConnectionFields'));
      setLoading(false);
      return;
    }

    const hasToken = formData.bearer_token.trim();
    const hasCredentials = formData.user.trim() && formData.password.trim();

    if (!hasToken && !hasCredentials) {
      setError(t('nodes.fillConnectionFields'));
      setLoading(false);
      return;
    }

    try {
      const payload: { name: string; url: string; bearer_token?: string; user?: string; password?: string } = {
        name: formData.name.trim(),
        url: panelUrl,
      };
      
      if (hasToken) {
        payload.bearer_token = formData.bearer_token.trim();
      } else {
        payload.user = formData.user.trim();
        payload.password = formData.password;
      }

      await createNode(payload, { emitChange: false });
      resetIntake();
      closeIntakeAndNotify();
      setSuccess(t('nodes.addSuccess'));
      toast(t('nodes.addSuccess'), 'success');
      onReload();
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.addFailed'));
    } finally {
      setLoading(false);
    }
  };

  const parseBatchText = () => {
    setError('');
    const lines = batchText.split('\n').map((line) => line.trim()).filter(Boolean);
    const rows: BatchPreviewRow[] = lines.map((line, idx) => {
      const parts = line.split(/\s+/);
      const row: BatchPreviewRow = {
        name: `Server-${idx + 1}`,
        url: parts[0] || '',
      };
      
      // Check if second part is bearer token (starts with "bearer:")
      if (parts[1]?.startsWith('bearer:')) {
        row.bearer_token = parts[1].substring(7); // Remove "bearer:" prefix
      } else {
        row.user = parts[1] || '';
        row.password = parts[2] || '';
      }
      
      return row;
    });
    setBatchPreview(rows);
    setBatchAdded(false);
  };

  const handleBatchAddAll = async () => {
    if (batchPreview.length === 0) return;
    setLoading(true);
    setError('');
    setSuccess('');
    try {
      const results = await createNodesBounded(batchPreview, { emitChange: false });
      const succeeded = results.filter((result) => result.status === 'fulfilled').length;
      const failed = results.length - succeeded;
      if (failed > 0) {
        setSuccess(t('nodes.batchAdded', { count: succeeded }));
        setError(t('nodes.batchFailed', { count: failed }));
      } else {
        resetIntake();
        closeIntakeAndNotify();
        setSuccess(t('nodes.batchAdded', { count: succeeded }));
        toast(t('nodes.batchAdded', { count: succeeded }), 'success');
      }
      if (succeeded > 0) {
        if (failed > 0) {
          dispatchNodesChanged({ action: 'create' });
        }
        onReload();
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.batchAddFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleModeSwitch = (mode: 'form' | 'batch') => {
    setAddMode(mode);
    setFormData(emptyNodeConnectionForm());
    setBatchText('');
    setBatchPreview([]);
    setBatchAdded(false);
    setError('');
    setSuccess('');
  };

  const closeEditModal = () => {
    setShowEditModal(false);
    setEditingNode(null);
    setEditingForm(emptyNodeConnectionForm());
    setError('');
  };

  const handleSaveNode = async () => {
    if (!editingNode) return;
    const result = buildNodeEditPayload(editingNode, editingForm);
    if ('error' in result) {
      setError(
        result.error === 'name'
          ? t('nodes.nameEmpty')
          : result.error === 'url'
            ? t('nodes.fillConnectionFields')
            : t('nodes.credentialsIncomplete'),
      );
      return;
    }

    setLoading(true);
    setError('');
    try {
      await updateNode(editingNode.id, result.payload);
      closeEditModal();
      onReload();
      setSuccess(t('nodes.updateSuccess'));
      toast(t('nodes.updateSuccess'), 'success');
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.updateFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleCheckConnection = async () => {
    setError('');
    setSuccess('');
    
    const hasToken = formData.bearer_token.trim();
    const hasCredentials = formData.user.trim() && formData.password.trim();
    
    const panelUrl = buildPanelUrl(formData.url, formData.port);
    if (!panelUrl) {
      setError(t('nodes.fillConnectionFields'));
      return;
    }
    
    if (!hasToken && !hasCredentials) {
      setError(t('nodes.fillConnectionFields'));
      return;
    }

    setCheckingConnection(true);
    try {
      const checkData: { url: string; bearer_token?: string; user?: string; password?: string } = { url: panelUrl };
      if (hasToken) {
        checkData.bearer_token = formData.bearer_token.trim();
      } else {
        checkData.user = formData.user.trim();
        checkData.password = formData.password;
      }
      
      const payload = await checkNodeConnection(checkData);
      if (payload.success) {
        const count = Number.isFinite(payload.inbounds_count) ? payload.inbounds_count : null;
        setSuccess(count !== null ? t('nodes.connectionOkWithInbounds', { count }) : t('nodes.connectionOk'));
      } else {
        setError(payload.message || t('nodes.connectionFailed'));
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || t('nodes.connectionCheckFailed'));
    } finally {
      setCheckingConnection(false);
    }
  };

  return (
    <div className={`node-manager${showIntakeStrip ? ' node-manager--intake-strip-mode' : ''}`}>
      {(showIntakeController || showForm) && (
      <section className={showIntakeController ? `panel-block mb-4${showIntakeStrip ? ' node-intake-strip' : ''}` : undefined}>
          {showIntakeController && (
          <>
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title">{t('nodes.intakeTitle')}</h6>
              <p className="panel-block__hint">{t('nodes.intakeHint')}</p>
            </div>
            <button
              className={showIntakeStrip ? 'node-intake-strip__action' : 'btn btn-sm'}
              style={showIntakeStrip ? undefined : { backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
              onClick={() => { setShowForm(!showForm); setSuccess(''); setError(''); }}
            >
              <span className="d-inline-flex align-items-center gap-1">
                <UIIcon name={showForm ? 'x' : 'plus'} size={14} />
                {showForm ? t('common.cancel') : t('nodes.addNode')}
              </span>
            </button>
          </div>

          {error && <div className="alert alert-danger mb-3">{error}</div>}
          {success && <div className="alert alert-success mb-3">{success}</div>}
          </>
          )}

          {showForm && (
            <div className="modal fade show d-block" tabIndex={-1} role="dialog" style={{ backgroundColor: 'rgba(2, 6, 23, 0.66)' }}>
              <div className="modal-dialog modal-lg modal-dialog-scrollable" role="document">
                <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
                  <div className="modal-header" style={{ borderColor: colors.border }}>
                    <h6 className="modal-title" style={{ color: colors.text.primary }}>{t('nodes.intakeTitle')}</h6>
                    <button type="button" className="btn-close" onClick={() => setShowForm(false)} aria-label="Close" />
                  </div>
                  <div className="modal-body">
            <div className="panel-block__stack">
              <div>
                <label className="form-label small" style={{ color: colors.text.secondary }}>{t('nodes.addMode')}</label>
                <div className="panel-inline-actions">
                  <button
                    type="button"
                    className={`seg-tab${addMode === 'form' ? ' seg-tab--active' : ''}`}
                    onClick={() => handleModeSwitch('form')}
                  >
                    {t('nodes.singleForm')}
                  </button>
                  <button
                    type="button"
                    className={`seg-tab${addMode === 'batch' ? ' seg-tab--active' : ''}`}
                    onClick={() => handleModeSwitch('batch')}
                  >
                    {t('nodes.batchText')}
                  </button>
                </div>
              </div>

              {addMode === 'form' ? (
                <form onSubmit={handleSubmit} className="panel-block__stack">
                  <div className="panel-field-grid">
                    <input
                      type="text"
                      name="name"
                      className="form-control"
                      placeholder={t('nodes.nodeLabel')}
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                    <input
                      type="text"
                      name="url"
                      className="form-control"
                      placeholder={t('nodes.nodeUrlPlaceholder')}
                      value={formData.url}
                      onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      required
                    />
                    <input
                      type="text"
                      inputMode="numeric"
                      name="port"
                      className="form-control"
                      placeholder={t('inbounds.port')}
                      value={formData.port}
                      onChange={(e) => setFormData({ ...formData, port: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                    <input
                      type="text"
                      name="user"
                      className="form-control"
                      placeholder={t('auth.username')}
                      value={formData.user}
                      onChange={(e) => setFormData({ ...formData, user: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                    <input
                      type="password"
                      name="password"
                      className="form-control"
                      placeholder={t('auth.password')}
                      value={formData.password}
                      onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                      style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    />
                  </div>

                  <div className="d-flex align-items-center gap-2 my-1">
                    <hr style={{ flex: 1, borderColor: colors.border, margin: 0 }} />
                    <span className="small" style={{ color: colors.text.secondary, whiteSpace: 'nowrap' }}>{t('common.or').toUpperCase()}</span>
                    <hr style={{ flex: 1, borderColor: colors.border, margin: 0 }} />
                  </div>

                  <div className="panel-block__stack">
                    <div>
                      <label className="form-label small" htmlFor="node-bearer-token" style={{ color: colors.text.secondary }}>
                        {t('nodes.bearerTokenLabel')}
                      </label>
                      <input
                        id="node-bearer-token"
                        type="password"
                        name="bearer_token"
                        className="form-control"
                        placeholder={t('nodes.bearerTokenPlaceholder')}
                        value={formData.bearer_token}
                        onChange={(e) => setFormData({ ...formData, bearer_token: e.target.value })}
                        style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                      />
                      <div className="form-text small mt-1" style={{ color: colors.text.secondary }}>
                        {t('nodes.bearerTokenHint')}
                      </div>
                    </div>
                  </div>

                  <div className="panel-inline-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.warning + '33', borderColor: colors.warning + '66', color: colors.warning }}
                      onClick={handleCheckConnection}
                      disabled={loading || checkingConnection}
                    >
                      {checkingConnection ? t('nodes.checking') : t('nodes.checkConnection')}
                    </button>
                    <button
                      type="submit"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                      disabled={loading || checkingConnection}
                    >
                      {loading ? t('nodes.saving') : t('common.save')}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="panel-block__stack">
                  <p className="small mb-0" style={{ color: colors.text.secondary }}>
                    {t('nodes.batchFormat')}: <span className="mono-inline">{t('nodes.batchFormatPasswordExample')}</span> • <span className="mono-inline">{t('nodes.batchFormatBearerExample')}</span>
                  </p>
                  <textarea
                    className="form-control form-control-sm"
                    rows={6}
                    aria-label={t('nodes.batchText')}
                    value={batchText}
                    onChange={(e) => { setBatchText(e.target.value); setBatchPreview([]); setBatchAdded(false); }}
                    placeholder={t('nodes.batchPlaceholder')}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <div className="panel-inline-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }}
                      onClick={parseBatchText}
                      disabled={!batchText.trim()}
                    >
                      {t('nodes.parsePreview')}
                    </button>
                    {batchPreview.length > 0 && (
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ backgroundColor: colors.success, borderColor: colors.success, color: colors.successText }}
                        onClick={handleBatchAddAll}
                        disabled={loading || batchAdded}
                      >
                        {loading ? t('nodes.adding') : t('nodes.addAll', { count: batchPreview.length })}
                      </button>
                    )}
                  </div>

                  {batchPreview.length > 0 && (
                    <div className="table-responsive table-shell">
                      <table className="table table-sm align-middle mb-0" style={{ color: colors.text.primary }}>
                        <thead>
                          <tr style={{ borderColor: colors.border }}>
                            <th>{t('common.name')}</th>
                            <th>{t('nodes.nodeUrl')}</th>
                            <th>{t('auth.username')}</th>
                            <th>{t('auth.password')}</th>
                            <th>{t('nodes.bearerTokenLabel')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {batchPreview.map((row, idx) => (
                            <tr key={idx} style={{ borderColor: colors.border }}>
                              <td>{row.name}</td>
                              <td><small className="mono-inline">{row.url}</small></td>
                              <td>{row.bearer_token ? '—' : row.user}</td>
                              <td>{row.bearer_token ? '—' : row.password}</td>
                              <td>
                                {row.bearer_token
                                  ? <span className="badge" style={{ backgroundColor: colors.accent, color: colors.accentText }}>token</span>
                                  : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {showEditModal && editingNode && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-dialog-centered modal-lg">
            <div className="modal-content" style={{ backgroundColor: colors.bg.secondary, borderColor: colors.border }}>
              <div className="modal-header" style={{ borderColor: colors.border }}>
                <h6 className="modal-title" style={{ color: colors.text.primary }}>{t('nodes.editNode')}</h6>
                <button type="button" className="btn-close" aria-label={t('common.close')} onClick={closeEditModal} />
              </div>
              <form onSubmit={(event) => { event.preventDefault(); handleSaveNode(); }}>
              <div className="modal-body panel-block__stack">
                {error && <div className="alert alert-danger">{error}</div>}
                <div className="panel-field-grid">
                  <input
                    type="text"
                    name="edit-name"
                    className="form-control"
                    aria-label={t('nodes.nodeLabel')}
                    placeholder={t('nodes.nodeLabel')}
                    value={editingForm.name}
                    onChange={(e) => setEditingForm({ ...editingForm, name: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    autoFocus
                    required
                  />
                  <input
                    type="text"
                    name="edit-url"
                    className="form-control"
                    aria-label={t('nodes.nodeUrl')}
                    placeholder={t('nodes.nodeUrlPlaceholder')}
                    value={editingForm.url}
                    onChange={(e) => setEditingForm({ ...editingForm, url: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                    required
                  />
                  <input
                    type="text"
                    inputMode="numeric"
                    name="edit-port"
                    className="form-control"
                    aria-label={t('inbounds.port')}
                    placeholder={t('inbounds.port')}
                    value={editingForm.port}
                    onChange={(e) => setEditingForm({ ...editingForm, port: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <input
                    type="text"
                    name="edit-user"
                    className="form-control"
                    aria-label={t('auth.username')}
                    placeholder={t('auth.username')}
                    value={editingForm.user}
                    onChange={(e) => setEditingForm({ ...editingForm, user: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <input
                    type="password"
                    name="edit-password"
                    className="form-control"
                    aria-label={t('nodes.newPasswordOptional')}
                    placeholder={t('nodes.newPasswordOptional')}
                    value={editingForm.password}
                    onChange={(e) => setEditingForm({ ...editingForm, password: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                </div>
                <div>
                  <label className="form-label small" htmlFor="edit-node-bearer-token" style={{ color: colors.text.secondary }}>
                    {t('nodes.bearerTokenLabel')}
                  </label>
                  <input
                    id="edit-node-bearer-token"
                    type="password"
                    name="edit-bearer_token"
                    className="form-control"
                    placeholder={t('nodes.newBearerTokenOptional')}
                    value={editingForm.bearer_token}
                    onChange={(e) => setEditingForm({ ...editingForm, bearer_token: e.target.value })}
                    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }}
                  />
                  <div className="form-text small mt-1" style={{ color: colors.text.secondary }}>
                    {t('nodes.editCredentialsHint')}
                  </div>
                </div>
              </div>
              <div className="modal-footer" style={{ borderColor: colors.border }}>
                <button type="button" className="btn btn-sm" style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary }} onClick={closeEditModal}>
                  {t('common.cancel')}
                </button>
                <button type="submit" className="btn btn-sm" style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText }} disabled={loading}>
                  {loading ? t('nodes.saving') : t('nodes.saveChanges')}
                </button>
              </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
