/**
 * InboundEditModal.tsx
 *
 * Form-based inbound editor matching 3x-ui style.
 * Screenshots reference:
 *   146-AM-E.png  → VLESS + TCP RAW   + Reality security
 *   NL WS.png     → VLESS + WebSocket + None / TLS security
 *   NL xhttp.png  → VLESS + XHTTP     + TLS security
 *
 * Sections: Basic → Transmission → Security → Sniffing → Raw JSON fallback
 */
import React, { useState, useCallback, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useToast } from './Toast';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { generateNodeVlessEncryption, generateNodeX25519 } from '../api/serverOps';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Inbound {
  id: number;
  node_name: string;
  protocol: string;
  port: number;
  remark: string;
  enable: boolean;
  security: string;
  is_reality: boolean;
  streamSettings?: Record<string, any>;
  settings?: Record<string, any>;
  sniffing?: Record<string, any> | string;
  listen?: string;
}

interface Props {
  inbound: Inbound;
  nodeId: number;
  onClose: () => void;
  onSaved: () => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const parseJ = (v: any): Record<string, any> => {
  if (!v) return {};
  if (typeof v === 'object' && !Array.isArray(v)) return v;
  if (typeof v === 'string') { try { return JSON.parse(v) || {}; } catch { return {}; } }
  return {};
};

const commaSeparated = (value: unknown): string => Array.isArray(value) ? value.join(',') : '';
const csvValues = (value: string): string[] => value.split(',').map((item) => item.trim()).filter(Boolean);

const NETWORKS = ['tcp', 'ws', 'grpc', 'xhttp', 'httpupgrade', 'quic'] as const;
type Network = typeof NETWORKS[number];
type Security = 'none' | 'tls' | 'reality';

const FINGERPRINTS = ['', 'chrome', 'firefox', 'safari', 'ios', 'android', 'edge', 'qq', 'random', 'randomized'];
const XHTTP_MODES = ['auto', 'packet-up', 'stream-up', 'stream-one'];
const DOMAIN_STRATEGIES = ['', 'AsIs', 'UseIP', 'UseIPv4', 'UseIPv6', 'ForceIP', 'ForceIPv4', 'ForceIPv6'];

// ─── Sub-components ───────────────────────────────────────────────────────────

const Toggle: React.FC<{ id: string; checked: boolean; onChange: (v: boolean) => void; label: string; colors: any }> = ({ id, checked, onChange, label, colors }) => (
  <div className="d-flex align-items-center justify-content-between py-1">
    <label htmlFor={id} style={{ color: colors.text.secondary, fontSize: '0.82rem', cursor: 'pointer', userSelect: 'none' }}>{label}</label>
    <div className="form-check form-switch mb-0">
      <input className="form-check-input" type="checkbox" role="switch" id={id} checked={checked} onChange={e => onChange(e.target.checked)} />
    </div>
  </div>
);

const Field: React.FC<{ label: string; children: React.ReactNode; colors: any; hint?: string }> = ({ label, children, colors, hint }) => (
  <div className="row align-items-center mb-2">
    <div className="col-4 text-end">
      <span style={{ fontSize: '0.8rem', color: colors.text.secondary }}>{label}</span>
      {hint && <span title={hint} style={{ fontSize: '0.68rem', color: colors.text.tertiary, marginLeft: '3px' }}>ⓘ</span>}
    </div>
    <div className="col-8">{children}</div>
  </div>
);

const TextInput: React.FC<{ value: string; onChange: (v: string) => void; placeholder?: string; mono?: boolean; colors: any }> = ({ value, onChange, placeholder, mono, colors }) => (
  <input
    type="text"
    className="form-control form-control-sm"
    value={value}
    onChange={e => onChange(e.target.value)}
    placeholder={placeholder}
    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, fontFamily: mono ? 'monospace' : undefined, fontSize: '0.8rem' }}
  />
);

const NumInput: React.FC<{ value: string | number; onChange: (v: string) => void; placeholder?: string; colors: any; style?: React.CSSProperties }> = ({ value, onChange, placeholder, colors, style }) => (
  <input
    type="number"
    className="form-control form-control-sm"
    value={value}
    onChange={e => onChange(e.target.value)}
    placeholder={placeholder}
    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, fontSize: '0.8rem', width: '120px', ...style }}
  />
);

const Select: React.FC<{ value: string; onChange: (v: string) => void; options: string[]; colors: any }> = ({ value, onChange, options, colors }) => (
  <select
    className="form-select form-select-sm"
    value={value}
    onChange={e => onChange(e.target.value)}
    style={{ backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, fontSize: '0.8rem' }}
  >
    {options.map(o => <option key={o} value={o}>{o || '(default)'}</option>)}
  </select>
);

const SectionHeader: React.FC<{ title: string; colors: any; collapsible?: boolean; open?: boolean; onToggle?: () => void }> = ({ title, colors, collapsible, open, onToggle }) => (
  <div
    className="d-flex align-items-center gap-2 mb-2 mt-3"
    onClick={collapsible ? onToggle : undefined}
    style={{ cursor: collapsible ? 'pointer' : undefined, userSelect: 'none' }}
  >
    {collapsible && <span style={{ color: colors.text.tertiary, fontSize: '0.75rem' }}>{open ? '▾' : '▸'}</span>}
    <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: colors.text.tertiary }}>{title}</span>
    <div style={{ flex: 1, height: '1px', background: colors.border }} />
  </div>
);

// ─── Main component ───────────────────────────────────────────────────────────

export const InboundEditModal: React.FC<Props> = ({ inbound, nodeId, onClose, onSaved }) => {
  const { colors } = useTheme();
  const { toast } = useToast();
  const { t } = useTranslation();

  // ── Parse raw data ──────────────────────────────────────────────────────────
  const ss0 = parseJ(inbound.streamSettings);
  const settings0 = parseJ(inbound.settings);
  const sn0 = parseJ(inbound.sniffing);
  const wsS0 = ss0.wsSettings || {};
  const grpcS0 = ss0.grpcSettings || {};
  const xhttpS0 = ss0.xhttpSettings || {};
  const huS0 = ss0.httpupgradeSettings || {};
  const realS0 = ss0.realitySettings || {};
  const tlsS0 = ss0.tlsSettings || {};
  const sockS0 = ss0.sockopt || {};

  // ── Basic state ─────────────────────────────────────────────────────────────
  const [remark, setRemark] = useState(inbound.remark || '');
  const [port, setPort] = useState(String(inbound.port || ''));
  const [listenIP, setListenIP] = useState(inbound.listen || '');
  const [enable, setEnable] = useState(inbound.enable);

  // ── Network / Transmission ──────────────────────────────────────────────────
  const [network, setNetwork] = useState<Network>((ss0.network as Network) || 'tcp');
  const [security, setSecurity] = useState<Security>(
    ss0.security === 'reality' ? 'reality' : ss0.security === 'tls' ? 'tls' : 'none'
  );
  const [vlessDecryption, setVlessDecryption] = useState(settings0.decryption || 'none');

  // WS settings
  const [wsHost, setWsHost] = useState(wsS0.host || '');
  const [wsPath, setWsPath] = useState(wsS0.path || '/');
  const [wsHeartbeat, setWsHeartbeat] = useState(String(wsS0.heartbeatPeriod || 0));

  // gRPC settings
  const [grpcService, setGrpcService] = useState(grpcS0.serviceName || '');
  const [grpcMultiMode, setGrpcMultiMode] = useState<boolean>(Boolean(grpcS0.multiMode));

  // XHTTP settings
  const [xhttpHost, setXhttpHost] = useState((xhttpS0.host || []).join(','));
  const [xhttpPath, setXhttpPath] = useState(xhttpS0.path || '/');
  const [xhttpMode, setXhttpMode] = useState(xhttpS0.mode || 'auto');
  const [xhttpNoSSE, setXhttpNoSSE] = useState<boolean>(Boolean(xhttpS0.noSSEHeader));
  const [xhttpMaxBuf, setXhttpMaxBuf] = useState(String(xhttpS0.maxBufferedSize ?? 30));
  const [xhttpMaxUpload, setXhttpMaxUpload] = useState(String(xhttpS0.uploadSizeLimit ?? 1000000));
  const [xhttpPadMin, setXhttpPadMin] = useState(String((xhttpS0.paddingBytes || '').toString().split('-')[0] || 100));
  const [xhttpPadMax, setXhttpPadMax] = useState(String((xhttpS0.paddingBytes || '').toString().split('-')[1] || 1000));

  // HTTPUpgrade settings
  const [huHost, setHuHost] = useState(huS0.host || '');
  const [huPath, setHuPath] = useState(huS0.path || '/');

  // Sockopt
  const sockEnabled = Boolean(ss0.sockopt && Object.keys(ss0.sockopt).length);
  const [tcpFastOpen, setTcpFastOpen] = useState<boolean>(Boolean(sockS0.tcpFastOpen));
  const [multiPath, setMultiPath] = useState<boolean>(Boolean(sockS0.tcpMultiPath));
  const [domainStrategy, setDomainStrategy] = useState(sockS0.domainStrategy || '');
  const [tcpCongestion, setTcpCongestion] = useState(sockS0.tcpCongestion || '');
  const [tproxy, setTproxy] = useState(sockS0.tproxy || 'off');
  const [v6Only, setV6Only] = useState<boolean>(Boolean(sockS0.v6only));

  // Reality settings
  const [realShow, setRealShow] = useState<boolean>(Boolean(realS0.show));
  const [realDest, setRealDest] = useState(realS0.dest || '');
  const [realXver, setRealXver] = useState(String(realS0.xver ?? 0));
  const [realServerNames, setRealServerNames] = useState(
    Array.isArray(realS0.serverNames) ? realS0.serverNames.join(',') : (realS0.serverNames || '')
  );
  const [realPrivateKey, setRealPrivateKey] = useState(realS0.privateKey || '');
  const [realShortIds, setRealShortIds] = useState(
    Array.isArray(realS0.shortIds) ? realS0.shortIds.join(',') : (realS0.shortIds || '')
  );
  const [realSpiderX, setRealSpiderX] = useState(
    realS0.settings?.spiderX || realS0.spiderX || '/'
  );
  const [realPublicKey, setRealPublicKey] = useState(realS0.settings?.publicKey || realS0.publicKey || '');
  const [realFingerprint, setRealFingerprint] = useState(
    realS0.settings?.fingerprint || realS0.fingerprint || 'chrome'
  );
  const [realUtls, setRealUtls] = useState(realS0.settings?.fingerprint || realS0.fingerprint || 'chrome');

  // TLS settings
  const [tlsServerName, setTlsServerName] = useState(tlsS0.serverName || '');
  const [tlsAllowInsecure, setTlsAllowInsecure] = useState<boolean>(Boolean(tlsS0.allowInsecure));

  // Sniffing
  const [sniffEnabled, setSniffEnabled] = useState<boolean>(Boolean(sn0.enabled));
  const [sniffHTTP, setSniffHTTP] = useState<boolean>((sn0.destOverride || []).includes('http'));
  const [sniffTLS, setSniffTLS] = useState<boolean>((sn0.destOverride || []).includes('tls'));
  const [sniffQUIC, setSniffQUIC] = useState<boolean>((sn0.destOverride || []).includes('quic'));
  const [sniffFAKEDNS, setSniffFAKEDNS] = useState<boolean>((sn0.destOverride || []).includes('fakedns'));
  const [sniffMetaOnly, setSniffMetaOnly] = useState<boolean>(Boolean(sn0.metadataOnly));
  const [sniffRouteOnly, setSniffRouteOnly] = useState<boolean>(Boolean(sn0.routeOnly));
  const [sniffIPsExcl, setSniffIPsExcl] = useState(commaSeparated(sn0.excludeForInbound));
  const [sniffDomsExcl, setSniffDomsExcl] = useState(commaSeparated(sn0.domainsExcluded));

  // UI state
  const [activeTab, setActiveTab] = useState<'form' | 'raw'>('form');
  const [sniffOpen, setSniffOpen] = useState(Boolean(sn0.enabled));
  const [sockOpen, setSockOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [genKeyLoading, setGenKeyLoading] = useState(false);
  const [genVlessEncLoading, setGenVlessEncLoading] = useState(false);

  // ── Computed streamSettings ─────────────────────────────────────────────────
  const buildStreamSettings = useCallback((): Record<string, any> => {
    const result: Record<string, any> = { ...ss0, network, security };

    // Clean up old network settings
    delete result.wsSettings;
    delete result.grpcSettings;
    delete result.xhttpSettings;
    delete result.httpupgradeSettings;
    delete result.tcpSettings;

    if (network === 'ws') {
      result.wsSettings = { host: wsHost, path: wsPath, heartbeatPeriod: Number(wsHeartbeat) };
    } else if (network === 'grpc') {
      result.grpcSettings = { serviceName: grpcService, multiMode: grpcMultiMode };
    } else if (network === 'xhttp') {
      result.xhttpSettings = {
        // Current Xray adds session-ID/XMUX fields faster than the form can
        // expose them.  Preserve unknown values on a form save; only the
        // fields represented by this UI are intentionally overwritten.
        ...xhttpS0,
        host: xhttpHost ? xhttpHost.split(',').map((s: string) => s.trim()).filter(Boolean) : [],
        path: xhttpPath,
        mode: xhttpMode,
        noSSEHeader: xhttpNoSSE,
        maxBufferedSize: Number(xhttpMaxBuf) || 30,
        uploadSizeLimit: Number(xhttpMaxUpload) || 1000000,
        paddingBytes: `${xhttpPadMin}-${xhttpPadMax}`,
      };
    } else if (network === 'httpupgrade') {
      result.httpupgradeSettings = { host: huHost, path: huPath };
    }

    // Security
    delete result.realitySettings;
    delete result.tlsSettings;
    if (security === 'reality') {
      result.realitySettings = {
        show: realShow,
        dest: realDest,
        xver: Number(realXver) || 0,
        serverNames: realServerNames.split(',').map((s: string) => s.trim()).filter(Boolean),
        privateKey: realPrivateKey,
        shortIds: realShortIds.split(',').map((s: string) => s.trim()).filter(Boolean),
        settings: { publicKey: realPublicKey, fingerprint: realFingerprint, spiderX: realSpiderX, show: realShow },
      };
    } else if (security === 'tls') {
      result.tlsSettings = { serverName: tlsServerName, allowInsecure: tlsAllowInsecure };
    }

    // Sockopt
    if (sockEnabled) {
      result.sockopt = {
        ...sockS0,
        tcpFastOpen,
        tcpMultiPath: multiPath,
        domainStrategy: domainStrategy || undefined,
        tcpCongestion: tcpCongestion || undefined,
        tproxy: tproxy !== 'off' ? tproxy : undefined,
        v6only: v6Only,
      };
    } else {
      delete result.sockopt;
    }

    return result;
  }, [network, security, wsHost, wsPath, wsHeartbeat, grpcService, grpcMultiMode,
    xhttpHost, xhttpPath, xhttpMode, xhttpNoSSE, xhttpMaxBuf, xhttpMaxUpload, xhttpPadMin, xhttpPadMax, xhttpS0,
    huHost, huPath, realShow, realDest, realXver, realServerNames, realPrivateKey, realShortIds,
    realPublicKey, realFingerprint, realSpiderX, tlsServerName, tlsAllowInsecure,
    sockEnabled, tcpFastOpen, multiPath, domainStrategy, tcpCongestion, tproxy, v6Only]);

  const buildSniffing = (): Record<string, any> => {
    const destOverride: string[] = [];
    if (sniffHTTP) destOverride.push('http');
    if (sniffTLS) destOverride.push('tls');
    if (sniffQUIC) destOverride.push('quic');
    if (sniffFAKEDNS) destOverride.push('fakedns');
    // Keep fields introduced by newer Xray/3x-ui versions when an operator
    // changes one of the controls represented by this form.
    return {
      ...sn0,
      enabled: sniffEnabled,
      destOverride,
      metadataOnly: sniffMetaOnly,
      routeOnly: sniffRouteOnly,
      excludeForInbound: csvValues(sniffIPsExcl),
      domainsExcluded: csvValues(sniffDomsExcl),
    };
  };

  const sniffingChanged = (): boolean => {
    const initialDestOverride = Array.isArray(sn0.destOverride) ? sn0.destOverride : [];
    const currentDestOverride = buildSniffing().destOverride as string[];
    return (
      sniffEnabled !== Boolean(sn0.enabled)
      || sniffMetaOnly !== Boolean(sn0.metadataOnly)
      || sniffRouteOnly !== Boolean(sn0.routeOnly)
      || currentDestOverride.join('\u0000') !== initialDestOverride.join('\u0000')
      || sniffIPsExcl !== commaSeparated(sn0.excludeForInbound)
      || sniffDomsExcl !== commaSeparated(sn0.domainsExcluded)
    );
  };

  const buildInboundSettings = (): Record<string, any> => {
    const result = { ...settings0 };
    if (inbound.protocol === 'vless') {
      result.decryption = String(vlessDecryption || '').trim() || 'none';
    }
    return result;
  };

  // ── Generate Reality keys ───────────────────────────────────────────────────
  const handleGenKeys = async () => {
    setGenKeyLoading(true);
    try {
      const keypair = await generateNodeX25519(nodeId);
      if (keypair.privateKey) setRealPrivateKey(keypair.privateKey);
      if (keypair.publicKey) setRealPublicKey(keypair.publicKey);
      toast(t('inbounds.realityKeysGenerated'), 'success');
    } catch {
      // fallback: generate short IDs at least
      const arr = new Uint8Array(8);
      crypto.getRandomValues(arr);
      const hex = Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
      setRealShortIds(hex);
      toast(t('inbounds.keyGenUnavailable'), 'warning');
    } finally { setGenKeyLoading(false); }
  };

  const handleGenVlessEnc = async () => {
    setGenVlessEncLoading(true);
    try {
      const auths = await generateNodeVlessEncryption(nodeId);
      const selected = auths.find((item) => item.decryption) || auths[0];
      const decryption = String(selected?.decryption || '').trim();
      if (!decryption) {
        throw new Error(t('inbounds.vlessDecryptionGenerationFailed'));
      }
      setVlessDecryption(decryption);
      toast(t('inbounds.vlessDecryptionGenerated'), 'success');
    } catch (e: any) {
      toast(e?.message || t('inbounds.vlessDecryptionGenerationFailed'), 'error');
    } finally { setGenVlessEncLoading(false); }
  };

  // ── Save ────────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const updates: Record<string, any> = {
        remark,
        port: parseInt(port) || inbound.port,
        enable,
        streamSettings: buildStreamSettings(),
      };
      // Avoid touching values that this request did not edit.  This protects
      // old cached/realtime rows that predate the v3 list DTO additions and
      // makes a remark-only edit safe even if the panel has extra sniffing
      // keys not represented by the form.
      if (listenIP !== (typeof inbound.listen === 'string' ? inbound.listen : '')) {
        updates.listen = listenIP;
      }
      if (sniffingChanged()) {
        updates.sniffing = buildSniffing();
      }
      if (inbound.protocol === 'vless' && String(settings0.decryption || 'none') !== String(vlessDecryption || 'none')) {
        updates.settings = buildInboundSettings();
      }
      await api.put(`/v1/inbounds/${nodeId}/${inbound.id}`, updates, { auth: getAuth() });
      toast(t('inbounds.savedInbound', { name: remark || inbound.id }), 'success');
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.response?.data?.detail || t('inbounds.saveFailed'));
    } finally { setSaving(false); }
  };

  // ── Style helpers ───────────────────────────────────────────────────────────
  const inputStyle = { backgroundColor: colors.bg.primary, borderColor: colors.border, color: colors.text.primary, fontSize: '0.8rem' };
  const secTabCls = (active: boolean) => `seg-tab${active ? ' seg-tab--active' : ''}`;
  const netTabCls = (n: Network) => `seg-tab seg-tab--xs${network === n ? ' seg-tab--active' : ''}`;

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

  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={t('inbounds.modifyInbound')}>
      <div className="drawer__backdrop" onClick={onClose} />
      <div className="drawer__panel">

        {/* Header */}
        <div className="drawer__header">
          <div>
            <div className="drawer__title">{t('inbounds.modifyInbound')}</div>
            <div className="drawer__subtitle">{inbound.protocol.toUpperCase()} · {inbound.node_name}</div>
          </div>
          <div className="d-flex align-items-center gap-2">
            <button className={`${secTabCls(activeTab === 'form')} seg-tab--sm`} role="tab" aria-selected={activeTab === 'form'} onClick={() => setActiveTab('form')}>{t('inbounds.form')}</button>
            <button className={`${secTabCls(activeTab === 'raw')} seg-tab--sm`} role="tab" aria-selected={activeTab === 'raw'} onClick={() => setActiveTab('raw')}>{t('inbounds.rawJson')}</button>
            <button className="drawer__close" aria-label={t('common.close')} onClick={onClose}>✕</button>
          </div>
        </div>

        {/* Body */}
        <div className="drawer__body">
          {error && <div className="alert alert-danger">{error}</div>}

            {activeTab === 'raw' ? (
              // Raw JSON view (read-only info)
              <div>
                <p style={{ fontSize: '0.78rem', color: colors.text.secondary, marginBottom: '8px' }}>
                  {t('inbounds.fullConfigReadOnlyHint')}
                </p>
                <pre style={{ ...inputStyle, borderRadius: '8px', border: `1px solid ${colors.border}`, padding: '10px', fontSize: '0.73rem', overflowX: 'auto', maxHeight: '500px' }}>
                  {JSON.stringify({ remark, port, enable, listen: listenIP, settings: buildInboundSettings(), streamSettings: buildStreamSettings(), sniffing: buildSniffing() }, null, 2)}
                </pre>
              </div>
            ) : (
              <>
                {/* ─── BASIC ──────────────────────────────────────────────── */}
                <Toggle id="ib-enable" checked={enable} onChange={setEnable} label={t('common.enabled')} colors={colors} />
                <div style={{ height: '1px', background: colors.border, margin: '8px 0' }} />

                <Field label={t('inbounds.remark')} colors={colors}>
                  <TextInput value={remark} onChange={setRemark} placeholder={t('inbounds.inboundNamePlaceholder')} colors={colors} />
                </Field>
                <Field label={t('inbounds.protocol')} colors={colors}>
                  <input className="form-control form-control-sm" value={inbound.protocol} readOnly style={{ ...inputStyle, opacity: 0.6 }} />
                </Field>
                <Field label={t('inbounds.listenIp')} colors={colors} hint={t('inbounds.listenAllIpHint')}>
                  <TextInput value={listenIP} onChange={setListenIP} placeholder={t('inbounds.listenPlaceholder')} colors={colors} />
                </Field>
                <Field label={t('inbounds.port')} colors={colors}>
                  <NumInput value={port} onChange={setPort} colors={colors} />
                </Field>

                {/* ─── TRANSMISSION ───────────────────────────────────────── */}
                <SectionHeader title={t('inbounds.transmission')} colors={colors} />

                <div className="d-flex flex-wrap gap-1 mb-3">
                  {NETWORKS.map(n => (
                    <button key={n} className={netTabCls(n)} role="tab" aria-selected={network === n} onClick={() => setNetwork(n)}>
                      {n === 'tcp' ? 'TCP (RAW)' : n === 'ws' ? 'WebSocket' : n === 'grpc' ? 'gRPC' : n === 'xhttp' ? 'XHTTP' : n === 'httpupgrade' ? 'HTTPUpgrade' : 'QUIC'}
                    </button>
                  ))}
                </div>

                {/* WS */}
                {network === 'ws' && (
                  <>
                    <Field label={t('inbounds.host')} colors={colors}>
                      <TextInput value={wsHost} onChange={setWsHost} placeholder={t('inbounds.exampleDomainPlaceholder')} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.path')} colors={colors}>
                      <TextInput value={wsPath} onChange={setWsPath} placeholder="/path" colors={colors} />
                    </Field>
                    <Field label={t('inbounds.heartbeatPeriod')} colors={colors} hint={t('inbounds.heartbeatHint')}>
                      <NumInput value={wsHeartbeat} onChange={setWsHeartbeat} colors={colors} />
                    </Field>
                  </>
                )}

                {/* gRPC */}
                {network === 'grpc' && (
                  <>
                    <Field label={t('inbounds.serviceName')} colors={colors}>
                      <TextInput value={grpcService} onChange={setGrpcService} placeholder="serviceName" colors={colors} />
                    </Field>
                    <Toggle id="grpc-multi" checked={grpcMultiMode} onChange={setGrpcMultiMode} label={t('inbounds.multiMode')} colors={colors} />
                  </>
                )}

                {/* XHTTP */}
                {network === 'xhttp' && (
                  <>
                    <Field label={t('inbounds.host')} colors={colors}>
                      <TextInput value={xhttpHost} onChange={setXhttpHost} placeholder="comma-separated" colors={colors} />
                    </Field>
                    <Field label={t('inbounds.path')} colors={colors}>
                      <TextInput value={xhttpPath} onChange={setXhttpPath} placeholder="/path" colors={colors} />
                    </Field>
                    <Field label={t('inbounds.mode')} colors={colors}>
                      <Select value={xhttpMode} onChange={setXhttpMode} options={XHTTP_MODES} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.maxBufferedUpload')} colors={colors}>
                      <NumInput value={xhttpMaxBuf} onChange={setXhttpMaxBuf} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.maxUploadSize')} colors={colors}>
                      <NumInput value={xhttpMaxUpload} onChange={setXhttpMaxUpload} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.paddingBytes')} colors={colors} hint={t('inbounds.paddingRangeHint')}>
                      <div className="d-flex gap-1 align-items-center">
                        <NumInput value={xhttpPadMin} onChange={setXhttpPadMin} colors={colors} style={{ width: '80px' }} />
                        <span style={{ color: colors.text.tertiary }}>–</span>
                        <NumInput value={xhttpPadMax} onChange={setXhttpPadMax} colors={colors} style={{ width: '80px' }} />
                      </div>
                    </Field>
                    <Toggle id="xhttp-nosse" checked={xhttpNoSSE} onChange={setXhttpNoSSE} label={t('inbounds.noSseHeader')} colors={colors} />
                  </>
                )}

                {/* HTTPUpgrade */}
                {network === 'httpupgrade' && (
                  <>
                    <Field label={t('inbounds.host')} colors={colors}>
                      <TextInput value={huHost} onChange={setHuHost} placeholder={t('inbounds.exampleDomainPlaceholder')} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.path')} colors={colors}>
                      <TextInput value={huPath} onChange={setHuPath} placeholder="/path" colors={colors} />
                    </Field>
                  </>
                )}

                {/* Sockopt */}
                <SectionHeader title={t('inbounds.sockopt')} colors={colors} collapsible open={sockOpen} onToggle={() => setSockOpen(p => !p)} />
                {sockOpen && (
                  <>
                    <Toggle id="tcp-fast-open" checked={tcpFastOpen} onChange={setTcpFastOpen} label={t('inbounds.tcpFastOpen')} colors={colors} />
                    <Toggle id="multipath" checked={multiPath} onChange={setMultiPath} label={t('inbounds.multipathTcp')} colors={colors} />
                    <Toggle id="v6only" checked={v6Only} onChange={setV6Only} label={t('inbounds.v6Only')} colors={colors} />
                    <Field label={t('inbounds.domainStrategy')} colors={colors}>
                      <Select value={domainStrategy} onChange={setDomainStrategy} options={DOMAIN_STRATEGIES} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.tcpCongestion')} colors={colors}>
                      <TextInput value={tcpCongestion} onChange={setTcpCongestion} placeholder={t('inbounds.tcpCongestionPlaceholder')} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.tproxy')} colors={colors}>
                      <Select value={tproxy} onChange={setTproxy} options={['off', 'redirect', 'tproxy']} colors={colors} />
                    </Field>
                  </>
                )}

                {/* ─── SECURITY ───────────────────────────────────────────── */}
                <SectionHeader title={t('inbounds.security')} colors={colors} />

                <div className="d-flex gap-2 mb-3">
                  {(['none', 'reality', 'tls'] as Security[]).map(s => (
                    <button key={s} className={secTabCls(security === s)} role="tab" aria-selected={security === s} onClick={() => setSecurity(s)}>
                      {s === 'none' ? 'None' : s === 'reality' ? 'Reality' : 'TLS'}
                    </button>
                  ))}
                </div>

                {inbound.protocol === 'vless' && (
                  <Field label={t('inbounds.vlessDecryption')} colors={colors}>
                    <div className="d-flex align-items-center gap-2">
                      <TextInput
                        value={vlessDecryption}
                        onChange={setVlessDecryption}
                        placeholder={t('inbounds.vlessDecryptionPlaceholder')}
                        mono
                        colors={colors}
                      />
                      <button className="btn btn-sm"
                        style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary, fontSize: '0.75rem' }}
                        onClick={handleGenVlessEnc}
                        disabled={genVlessEncLoading || !nodeId}>
                        {genVlessEncLoading ? '…' : `⚙ ${t('inbounds.generateVlessDecryption')}`}
                      </button>
                    </div>
                  </Field>
                )}

                {/* Reality */}
                {security === 'reality' && (
                  <>
                    <Toggle id="real-show" checked={realShow} onChange={setRealShow} label={t('inbounds.show')} colors={colors} />
                    <Field label={t('inbounds.xver')} colors={colors}>
                      <NumInput value={realXver} onChange={setRealXver} colors={colors} />
                    </Field>
                    <Field label="uTLS" colors={colors}>
                      <Select value={realUtls} onChange={(v) => { setRealUtls(v); setRealFingerprint(v); }} options={FINGERPRINTS.filter(f => f)} colors={colors} />
                    </Field>
                    <Field label={t('inbounds.target')} colors={colors} hint={t('inbounds.realityTargetHint')}>
                      <TextInput value={realDest} onChange={setRealDest} placeholder={t('inbounds.realityTargetPlaceholder')} colors={colors} />
                    </Field>
                    <Field label="SNI" colors={colors}>
                      <TextInput value={realServerNames} onChange={setRealServerNames} placeholder="comma-separated" colors={colors} />
                    </Field>
                    <Field label={t('inbounds.shortIds')} colors={colors} hint={t('inbounds.commaSeparatedHexHint')}>
                      <TextInput value={realShortIds} onChange={setRealShortIds} placeholder={t('inbounds.shortIdsPlaceholder')} mono colors={colors} />
                    </Field>
                    <Field label="SpiderX" colors={colors}>
                      <TextInput value={realSpiderX} onChange={setRealSpiderX} placeholder="/" colors={colors} />
                    </Field>
                    <Field label={t('inbounds.publicKey')} colors={colors}>
                      <TextInput value={realPublicKey} onChange={setRealPublicKey} placeholder={t('inbounds.keyGenPlaceholder')} mono colors={colors} />
                    </Field>
                    <Field label={t('inbounds.privateKey')} colors={colors}>
                      <TextInput value={realPrivateKey} onChange={setRealPrivateKey} placeholder={t('inbounds.keyGenPlaceholder')} mono colors={colors} />
                    </Field>
                    <div className="d-flex gap-2 mt-1 mb-1">
                      <button className="btn btn-sm"
                        style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText, fontSize: '0.75rem' }}
                        onClick={handleGenKeys} disabled={genKeyLoading}>
                        {genKeyLoading ? '…' : `⚙ ${t('inbounds.getNewCert')}`}
                      </button>
                      <button className="btn btn-sm"
                        style={{ backgroundColor: colors.bg.tertiary, borderColor: colors.border, color: colors.text.secondary, fontSize: '0.75rem' }}
                        onClick={() => { setRealPrivateKey(''); setRealPublicKey(''); }}>
                        {t('common.clear')}
                      </button>
                    </div>
                  </>
                )}

                {/* TLS */}
                {security === 'tls' && (
                  <>
                    <Field label={t('inbounds.serverName')} colors={colors}>
                      <TextInput value={tlsServerName} onChange={setTlsServerName} placeholder={t('inbounds.exampleDomainPlaceholder')} colors={colors} />
                    </Field>
                    <Toggle id="tls-insecure" checked={tlsAllowInsecure} onChange={setTlsAllowInsecure} label={t('inbounds.allowInsecure')} colors={colors} />
                  </>
                )}

                {/* ─── SNIFFING ────────────────────────────────────────────── */}
                <SectionHeader title={t('inbounds.sniffing')} colors={colors} collapsible open={sniffOpen} onToggle={() => setSniffOpen(p => !p)} />
                {sniffOpen && (
                  <>
                    <Toggle id="sniff-en" checked={sniffEnabled} onChange={setSniffEnabled} label={t('common.enabled')} colors={colors} />
                    {sniffEnabled && (
                      <>
                        <div className="d-flex flex-wrap gap-2 mt-2 mb-1">
                          {[
                            { id: 'sniff-http', label: 'HTTP', val: sniffHTTP, set: setSniffHTTP },
                            { id: 'sniff-tls', label: 'TLS', val: sniffTLS, set: setSniffTLS },
                            { id: 'sniff-quic', label: 'QUIC', val: sniffQUIC, set: setSniffQUIC },
                            { id: 'sniff-fake', label: 'FAKEDNS', val: sniffFAKEDNS, set: setSniffFAKEDNS },
                          ].map(item => (
                            <label key={item.id} className="d-flex align-items-center gap-1" style={{ cursor: 'pointer', fontSize: '0.8rem', color: colors.text.secondary }}>
                              <input type="checkbox" checked={item.val} onChange={e => item.set(e.target.checked)} style={{ accentColor: colors.accent }} />
                              {item.label}
                            </label>
                          ))}
                        </div>
                        <Toggle id="sniff-meta" checked={sniffMetaOnly} onChange={setSniffMetaOnly} label={t('inbounds.metadataOnly')} colors={colors} />
                        <Toggle id="sniff-route" checked={sniffRouteOnly} onChange={setSniffRouteOnly} label={t('inbounds.routeOnly')} colors={colors} />
                        <Field label={t('inbounds.ipsExcluded')} colors={colors}>
                          <TextInput value={sniffIPsExcl} onChange={setSniffIPsExcl} placeholder={t('inbounds.ipRulesPlaceholder')} colors={colors} />
                        </Field>
                        <Field label={t('inbounds.domainsExcluded')} colors={colors}>
                          <TextInput value={sniffDomsExcl} onChange={setSniffDomsExcl} placeholder={t('inbounds.domainRulesPlaceholder')} colors={colors} />
                        </Field>
                      </>
                    )}
                  </>
                )}
              </>
            )}
          </div>

        {/* Footer */}
        <div className="drawer__footer">
          <button className="btn btn-sm btn-ghost-accent" onClick={onClose}>{t('common.close')}</button>
          <button className="btn btn-sm"
            style={{ backgroundColor: colors.accent, borderColor: colors.accent, color: colors.accentText, fontWeight: 700 }}
            onClick={handleSave} disabled={saving}>
            {saving ? '…' : t('common.update')}
          </button>
        </div>

      </div>
    </div>
  );
};
