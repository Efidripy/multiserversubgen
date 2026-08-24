/**
 * ClientEditModal.tsx
 *
 * Form-based client editor matching 3x-ui "Edit Client" style.
 *
 * Screenshots reference:
 *   D632-PC.png  → VLESS + Reality/TCP  — shows Flow dropdown (xtls-rprx-vision)
 *   firstWs.png  → VLESS + WebSocket   — no Flow field
 *   firstX.png   → VLESS + XHTTP       — no Flow field
 *
 * Flow is shown ONLY when: protocol === 'vless' AND (security === 'reality' OR network === 'tcp')
 * API: PUT /v1/clients/{uuid}  body: { node_id, inbound_id, updates: { email, enable, flow, totalGB, expiryTime, limitIp, remark } }
 */

import React, { useState, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useToast } from './Toast';
import api from '../api';
import { getAuth } from '../auth';
import { useTranslation } from 'react-i18next';
import { generateNodeMldsa65, generateNodeUuid, generateNodeVlessEncryption } from '../api/serverOps';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ClientForEdit {
  id?: string | null;           // UUID
  email: string;
  enable: boolean;
  up: number;
  down: number;
  total: number;
  expiryTime: number;
  node_id?: number;
  inbound_id: number;
  protocol: string;
  security?: string;             // 'none' | 'reality' | 'tls'
  network?: string;              // 'tcp' | 'ws' | 'grpc' | 'xhttp' …
  flow?: string;
  comment?: string;
  remark?: string;
  limitIp?: number;
  totalGB?: number;
  notes?: string;
}

interface Props {
  client: ClientForEdit;
  onClose: () => void;
  onSaved: () => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(Math.max(1, bytes)) / Math.log(k));
  return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
};

const toDateInput = (ms: number): string => {
  if (!ms || ms <= 0) return '';
  return new Date(ms).toISOString().slice(0, 10);
};

const fromDateInput = (d: string): number =>
  d ? new Date(d + 'T00:00:00').getTime() : 0;

const GIB_BYTES = 1024 ** 3;

const quotaBytesToGbInput = (value: number | undefined): string => {
  if (!Number.isFinite(value)) return '';
  return String((value as number) / GIB_BYTES);
};

const quotaGbInputToBytes = (value: string): number | undefined => {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const gigabytes = Number(normalized);
  if (!Number.isFinite(gigabytes) || gigabytes < 0) return undefined;
  return Math.round(gigabytes * GIB_BYTES);
};

const ipLimitInputToValue = (value: string): number | undefined => {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const limit = Number(normalized);
  if (!Number.isInteger(limit) || limit < 0) return undefined;
  return limit;
};

// Flow is relevant only for VLESS with Reality or plain TCP
const showFlowField = (protocol: string, security?: string, network?: string): boolean =>
  protocol === 'vless' && (security === 'reality' || network === 'tcp' || !network);

const FLOW_OPTIONS = [
  { value: '', label: 'none' },
  { value: 'xtls-rprx-vision', label: 'xtls-rprx-vision' },
  { value: 'xtls-rprx-vision-udp443', label: 'xtls-rprx-vision-udp443' },
];

// ─── Row layout helper ────────────────────────────────────────────────────────

const Row: React.FC<{ label: string; hint?: string; children: React.ReactNode; colors: any }> = ({ label, hint, children, colors }) => (
  <div className="d-flex align-items-center mb-3">
    <div style={{ width: '130px', flexShrink: 0, textAlign: 'right', paddingRight: '14px' }}>
      <span style={{ fontSize: '0.83rem', color: colors.text.secondary, fontWeight: 500 }}>{label}</span>
      {hint && <span style={{ fontSize: '0.65rem', color: colors.text.tertiary, marginLeft: '3px', cursor: 'default' }} title={hint}>ⓘ</span>}
    </div>
    <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
  </div>
);

// ─── Main component ───────────────────────────────────────────────────────────

export const ClientEditModal: React.FC<Props> = ({ client, onClose, onSaved }) => {
  const { colors } = useTheme();
  const { toast } = useToast();
  const { t } = useTranslation();

  // ── Form state ──────────────────────────────────────────────────────────────
  const [email, setEmail] = useState(client.email);
  const [uuid, setUuid] = useState(client.id || '');
  const [enable, setEnable] = useState(client.enable);
  // 3x-ui stores the operator-visible annotation in `comment`.  `remark`
  // remains a legacy fallback for older cached rows only.
  const [comment, setComment] = useState(client.comment ?? client.remark ?? '');
  const [notes, setNotes] = useState(client.notes || '');
  const [flow, setFlow] = useState(client.flow || '');
  // `total` is the traffic response's byte counter/limit; `totalGB` is the
  // separately configured quota.  Never derive one from the other.
  const [security, setSecurity] = useState(client.security || 'none');
  const [totalGB, setTotalGB] = useState(() => quotaBytesToGbInput(client.totalGB));
  // An absent value means the cached row did not carry this field.  Keep it
  // absent on save rather than unintentionally resetting the panel to zero.
  const [limitIp, setLimitIp] = useState(() =>
    client.limitIp == null ? '' : String(client.limitIp),
  );
  const [expiryDate, setExpiryDate] = useState(toDateInput(client.expiryTime));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [resetTrafficLoading, setResetTrafficLoading] = useState(false);
  const [uuidLoading, setUuidLoading] = useState(false);
  const [vlessEncLoading, setVlessEncLoading] = useState(false);
  const [mldsa65Loading, setMldsa65Loading] = useState(false);
  const [mldsa65Key, setMldsa65Key] = useState('');

  const showFlow = showFlowField(client.protocol, client.security, client.network);
  const showVlessEncryption = client.protocol === 'vless';

  // ── Computed traffic values ─────────────────────────────────────────────────
  const usedBytes = client.up + client.down;
  const totalBytes = client.total ?? 0;
  const usagePct = totalBytes > 0 ? Math.min(100, (usedBytes / totalBytes) * 100) : 0;
  const usageColor = usagePct >= 90 ? colors.danger : usagePct >= 70 ? colors.warning : '#c45bcc'; // purple like 3x-ui

  const inputStyle = {
    backgroundColor: colors.bg.primary,
    borderColor: colors.border,
    color: colors.text.primary,
    fontSize: '0.83rem',
  };

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleGenerateUuid = async () => {
    if (!client.node_id) {
      toast(t('clients.nodeRequiredForGeneration'), 'warning');
      return;
    }
    setUuidLoading(true);
    try {
      setUuid(await generateNodeUuid(client.node_id));
      toast(t('clients.uuidGenerated'), 'success');
    } catch (e: any) {
      toast(e?.message || t('clients.uuidGenerationFailed'), 'error');
    } finally {
      setUuidLoading(false);
    }
  };

  const handleGenerateVlessEncryption = async () => {
    if (!client.node_id) {
      toast(t('clients.nodeRequiredForGeneration'), 'warning');
      return;
    }
    setVlessEncLoading(true);
    try {
      const auths = await generateNodeVlessEncryption(client.node_id);
      const selected = auths.find((item) => item.encryption) || auths[0];
      const encryption = String(selected?.encryption || '').trim();
      if (!encryption) {
        throw new Error(t('clients.vlessEncryptionGenerationFailed'));
      }
      setSecurity(encryption);
      toast(t('clients.vlessEncryptionGenerated'), 'success');
    } catch (e: any) {
      toast(e?.message || t('clients.vlessEncryptionGenerationFailed'), 'error');
    } finally {
      setVlessEncLoading(false);
    }
  };

  const handleGenerateMldsa65 = async () => {
    if (!client.node_id) {
      toast(t('clients.nodeRequiredForGeneration'), 'warning');
      return;
    }
    setMldsa65Loading(true);
    try {
      const keyPair = await generateNodeMldsa65(client.node_id);
      const serialized = JSON.stringify(keyPair, null, 2);
      setMldsa65Key(serialized);
      try {
        await navigator.clipboard.writeText(serialized);
      } catch {}
      toast(t('clients.mldsa65Generated', { defaultValue: 'ML-DSA-65 keypair generated' }), 'success');
    } catch (e: any) {
      toast(e?.message || t('clients.mldsa65GenerationFailed', { defaultValue: 'ML-DSA-65 generation failed' }), 'error');
    } finally {
      setMldsa65Loading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const expiryMs = fromDateInput(expiryDate);
      const totalGBBytes = quotaGbInputToBytes(totalGB);
      const limitIpValue = ipLimitInputToValue(limitIp);
      if (totalGB.trim() && totalGBBytes === undefined) {
        setError(t('clients.invalidTrafficLimit', { defaultValue: 'Enter a non-negative traffic limit.' }));
        return;
      }
      if (limitIp.trim() && limitIpValue === undefined) {
        setError(t('clients.invalidIpLimit', { defaultValue: 'Enter a non-negative whole IP limit.' }));
        return;
      }

      const updates: Record<string, any> = {
        email,
        enable,
        expiryTime: expiryMs,
        // Always send `comment`, including an empty string, so an operator can
        // intentionally clear it and the SYSTEM classifier remains stable.
        comment,
        notes,
      };
      if (totalGBBytes !== undefined) updates.totalGB = totalGBBytes;
      if (limitIpValue !== undefined) updates.limitIp = limitIpValue;
      if (flow !== undefined) updates.flow = flow;
      if (showVlessEncryption) updates.security = security.trim() || 'none';
      // Send UUID update if changed
      if (uuid && uuid !== client.id) updates.id = uuid;

      await api.put(`/v1/clients/${encodeURIComponent(client.id || email)}`, {
        node_id: client.node_id,
        inbound_id: client.inbound_id,
        updates,
      }, { auth: getAuth() });

      toast(t('clients.savedClient', { email }), 'success');
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.response?.data?.detail || t('clients.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleResetTraffic = async () => {
    if (!window.confirm(t('clients.confirmResetTrafficForEmail', { email }))) return;
    setResetTrafficLoading(true);
    try {
      await api.post(`/v1/clients/${encodeURIComponent(client.id || email)}/reset-traffic`, {
        node_id: client.node_id,
        inbound_id: client.inbound_id,
        email,
      }, { auth: getAuth() });
      toast(t('clients.trafficResetForEmail', { email }), 'success');
      onSaved();
    } catch (e: any) {
      toast(e.response?.data?.detail || t('clients.resetFailed'), 'error');
    } finally {
      setResetTrafficLoading(false); }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={t('messages.editClient')}>
      <div className="drawer__backdrop" onClick={onClose} />
      <div className="drawer__panel">

        {/* Header */}
        <div className="drawer__header">
          <div>
            <div className="drawer__title">{t('messages.editClient')}</div>
            {client.email && <div className="drawer__subtitle">{client.email}</div>}
          </div>
          <button className="drawer__close" aria-label={t('common.close')} onClick={onClose}>✕</button>
        </div>

        {/* Body */}
        <div className="drawer__body">
            {error && <div className="alert alert-danger mb-3">{error}</div>}

            {/* Enabled */}
            <Row label={t('common.enabled')} colors={colors}>
              <div className="form-check form-switch mb-0">
                <input className="form-check-input" type="checkbox" role="switch"
                  id="ce-enable" checked={enable} onChange={e => setEnable(e.target.checked)} />
              </div>
            </Row>

            {/* Email */}
            <Row label={t('clients.email')} colors={colors}>
              <div className="d-flex align-items-center gap-2">
                <input
                  className="form-control form-control-sm"
                  style={inputStyle}
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                />
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary, flexShrink: 0, fontSize: '0.82rem' }}
                  title={t('clients.generateRandomEmail')}
                  onClick={() => setEmail(`user_${Math.random().toString(36).slice(2, 8)}`)}
                >↻</button>
              </div>
            </Row>

            {/* ID / UUID */}
            <Row label="ID" colors={colors}>
              <div className="d-flex align-items-center gap-2">
                <input
                  className="form-control form-control-sm"
                  style={{ ...inputStyle, fontFamily: 'monospace', fontSize: '0.74rem', letterSpacing: '0.02em' }}
                  value={uuid}
                  onChange={e => setUuid(e.target.value)}
                  placeholder="UUID"
                />
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary, flexShrink: 0, fontSize: '0.82rem' }}
                  title={t('clients.generateNewUuid')}
                  onClick={handleGenerateUuid}
                  disabled={uuidLoading || !client.node_id}
                >{uuidLoading ? '…' : '↻'}</button>
              </div>
            </Row>

            {/* Comment / Remark */}
            <Row label={t('clients.comment')} colors={colors}>
              <input
                className="form-control form-control-sm"
                style={inputStyle}
                value={comment}
                onChange={e => setComment(e.target.value)}
                placeholder=""
              />
            </Row>

            {/* Flow — only for VLESS + Reality/TCP */}
            <Row label={t('clients.noteTitle')} colors={colors}>
              <textarea
                className="form-control form-control-sm"
                style={inputStyle}
                rows={3}
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder=""
              />
            </Row>

            {showFlow && (
              <Row label={t('clients.flowLabel')} colors={colors}>
                <select
                  className="form-select form-select-sm"
                  style={inputStyle}
                  value={flow}
                  onChange={e => setFlow(e.target.value)}
                >
                  {FLOW_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </Row>
            )}

            {showVlessEncryption && (
              <Row label={t('clients.vlessEncryption')} colors={colors}>
                <div className="d-flex align-items-center gap-2">
                  <input
                    className="form-control form-control-sm"
                    style={{ ...inputStyle, fontFamily: 'monospace', fontSize: '0.74rem' }}
                    value={security}
                    onChange={e => setSecurity(e.target.value)}
                    placeholder="none"
                  />
                  <button
                    className="btn btn-sm"
                    style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary, flexShrink: 0, fontSize: '0.82rem' }}
                    title={t('clients.generateVlessEncryption')}
                    onClick={handleGenerateVlessEncryption}
                    disabled={vlessEncLoading || !client.node_id}
                  >{vlessEncLoading ? '…' : '↻'}</button>
                </div>
              </Row>
            )}

            <Row label="ML-DSA-65" colors={colors}>
              <div className="d-flex align-items-start gap-2">
                <textarea
                  className="form-control form-control-sm"
                  style={{ ...inputStyle, fontFamily: 'monospace', fontSize: '0.72rem' }}
                  rows={3}
                  value={mldsa65Key}
                  readOnly
                  placeholder={t('clients.mldsa65Placeholder', { defaultValue: 'privateKey / publicKey' })}
                />
                <button
                  className="btn btn-sm"
                  style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary, flexShrink: 0, fontSize: '0.82rem' }}
                  title={t('clients.generateMldsa65', { defaultValue: 'Generate ML-DSA-65' })}
                  onClick={handleGenerateMldsa65}
                  disabled={mldsa65Loading || !client.node_id}
                >{mldsa65Loading ? '...' : '↻'}</button>
              </div>
            </Row>

            {/* Total Flow (GB) */}
            <Row label={t('clients.totalFlow')} hint={t('clients.totalFlowHint')} colors={colors}>
              <input
                type="number"
                step="0.1"
                min="0"
                className="form-control form-control-sm"
                style={{ ...inputStyle, width: '120px' }}
                value={totalGB}
                onChange={e => setTotalGB(e.target.value)}
              />
            </Row>

            {/* IP Limit */}
            <Row label={t('clients.ipLimit')} hint={t('clients.ipLimitHint')} colors={colors}>
              <input
                type="number"
                min="0"
                className="form-control form-control-sm"
                style={{ ...inputStyle, width: '120px' }}
                value={limitIp}
                onChange={e => setLimitIp(e.target.value)}
              />
            </Row>

            {/* Usage */}
            <Row label={t('clients.usage')} colors={colors}>
              <div className="d-flex align-items-center gap-2 flex-wrap">
                <span className="usage-badge" style={{ color: usageColor }}>
                  {formatBytes(client.up)} / {formatBytes(client.down)} ({formatBytes(usedBytes)})
                </span>
                <button
                  className="btn btn-sm p-1"
                  style={{ background: 'none', border: 'none', color: colors.text.tertiary, fontSize: '0.85rem' }}
                  title={t('clients.resetTraffic')}
                  disabled={resetTrafficLoading}
                  onClick={handleResetTraffic}
                >
                  {resetTrafficLoading ? '…' : '⇄'}
                </button>
              </div>
              {totalBytes > 0 && (
                <div className="mt-1">
                  <div className="progress-track">
                    <div className="progress-track__fill" style={{ width: `${usagePct}%`, background: usageColor }} />
                  </div>
                  <div style={{ fontSize: '0.68rem', color: colors.text.tertiary, marginTop: '2px' }}>
                    {t('clients.usageOfTotal', { pct: usagePct.toFixed(1), total: formatBytes(totalBytes) })}
                  </div>
                </div>
              )}
            </Row>

            {/* Duration / Expiry */}
            <Row label={t('clients.duration')} hint={t('clients.durationHint')} colors={colors}>
              <div className="d-flex align-items-center gap-2">
                <input
                  type="date"
                  className="form-control form-control-sm"
                  style={{ ...inputStyle, maxWidth: '160px' }}
                  value={expiryDate}
                  onChange={e => setExpiryDate(e.target.value)}
                />
                {expiryDate && (
                  <button
                    className="btn btn-sm"
                    style={{ background: 'none', border: 'none', color: colors.text.tertiary, fontSize: '0.8rem' }}
                    title={t('clients.clearExpiryTitle')}
                    onClick={() => setExpiryDate('')}
                  >✕</button>
                )}
              </div>
              {expiryDate && (
                <div style={{ fontSize: '0.7rem', color: colors.text.tertiary, marginTop: '3px' }}>
                  {(() => {
                    const ms = fromDateInput(expiryDate);
                    const now = Date.now();
                    const diff = ms - now;
                    const days = Math.ceil(diff / 86400000);
                    if (days < 0) return <span style={{ color: colors.danger }}>{t('clients.expiredDaysAgo', { days: Math.abs(days) })}</span>;
                    if (days === 0) return <span style={{ color: colors.warning }}>{t('clients.expiresToday')}</span>;
                    return <span style={{ color: colors.text.tertiary }}>{t('clients.daysRemaining', { days })}</span>;
                  })()}
                </div>
              )}
            </Row>

            {/* Quick expiry buttons */}
            <Row label="" colors={colors}>
              <div className="d-flex flex-wrap gap-1">
                {[7, 14, 30, 60, 90, 180, 365].map(days => (
                  <button key={days} className="btn btn-sm"
                    style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '6px',
                      backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary }}
                    onClick={() => {
                      const base = expiryDate ? fromDateInput(expiryDate) : Date.now();
                      const past = base < Date.now() ? Date.now() : base;
                      setExpiryDate(toDateInput(past + days * 86400000));
                    }}
                    title={t('clients.setExpiryDaysTitle', { days })}
                  >+{days}d</button>
                ))}
                <button className="btn btn-sm"
                  style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '6px',
                    backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.tertiary }}
                  onClick={() => setExpiryDate('')}
                  title={t('clients.noExpiry')}
                >∞</button>
              </div>
            </Row>

          </div>

        {/* Footer */}
        <div className="drawer__footer">
          <button
            className="btn btn-sm btn-ghost-accent"
            onClick={onClose}
          >{t('common.close')}</button>
          <button
            className="btn btn-sm"
            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText, fontWeight: 700 }}
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? '…' : 'Save Changes'}
          </button>
        </div>

      </div>
    </div>
  );
};
