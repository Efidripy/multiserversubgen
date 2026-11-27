import './NodeOperationsModal.css';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  createApiToken,
  deleteApiToken,
  generateNodeMldsa65,
  generateNodeUuid,
  generateNodeVlessEncryption,
  generateNodeX25519,
  getApiTokens,
  getNodeOnlineClients,
  getNodeTraffic,
  getOutboundsTraffic,
  getXrayConfig,
  getXrayObservatory,
  getXrayVersions,
  installXray,
  resetAllNodeTraffics,
  setApiTokenEnabled,
  updatePanel,
} from '../api/serverOps';
import { LazyJsonEditor } from './LazyJsonEditor';
import { XrayTemplateEditor } from './XrayTemplateEditor';
import { SystemHistory } from './SystemHistory';
import { NodeDataView } from './NodeDataView';
import { useToast } from './Toast';
import { UIIcon, type IconName } from './UIIcon';

export type NodeOpsTab =
  | 'traffic'
  | 'online'
  | 'outbounds'
  | 'outboundsConfig'
  | 'routing'
  | 'history'
  | 'config'
  | 'observatory'
  | 'versions'
  | 'tokens'
  | 'keys'
  | 'panel';

interface NodeOperationsModalProps {
  nodeId: number;
  nodeName: string;
  initialTab?: NodeOpsTab;
  onClose: () => void;
  onNodeChanged?: () => void;
}

interface ApiTokenItem {
  id?: number | string;
  token_id?: number | string;
  name?: string;
  token?: string;
  enabled?: boolean;
  [key: string]: unknown;
}

type KeyKind = 'uuid' | 'x25519' | 'vless' | 'mldsa65';

const overlayClass = 'fixed inset-0 z-50 flex items-center justify-center node-ops-overlay px-3 py-5';
const panelClass = 'modal-content node-ops-panel flex h-[min(92vh,820px)] w-full max-w-6xl flex-col overflow-hidden';
const panelHeaderClass = 'modal-header flex min-w-0 items-start justify-between gap-4 px-4 py-4';
const panelBodyClass = 'flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row';
const sideClass = 'node-ops-side max-h-[28%] min-w-0 shrink-0 overflow-y-auto p-3 lg:max-h-none lg:w-[220px]';
const contentClass = 'modal-body flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto p-4';
const buttonBaseClass = 'btn btn-sm';
const buttonPrimaryClass = `${buttonBaseClass} btn-primary`;
const buttonSecondaryClass = `${buttonBaseClass} btn-ghost-secondary`;
const buttonDangerClass = `${buttonBaseClass} btn-danger`;
const inputClass = 'form-control';
const preClass = 'node-ops-pre min-h-0 flex-1 overflow-auto p-3 font-mono text-xs';
const chipClass = 'node-ops-chip inline-flex min-w-0 items-center gap-2 px-2 py-1';

const observatoryExample = `"metrics": { "tag": "metrics_out", "listen": "127.0.0.1:11111" },
"observatory": {
  "subjectSelector": ["outbound-tag"],
  "probeURL": "https://www.google.com/generate_204",
  "probeInterval": "1m"
}`;

const tabs: Array<{ id: NodeOpsTab; labelKey: string; icon: IconName }> = [
  { id: 'traffic', labelKey: 'nav.traffic', icon: 'traffic' },
  { id: 'online', labelKey: 'serverStatus.onlineClients', icon: 'clients' },
  { id: 'outbounds', labelKey: 'serverStatus.outboundTraffic', icon: 'upload' },
  { id: 'history', labelKey: 'nodeOps.history', icon: 'monitoring' },
  { id: 'outboundsConfig', labelKey: 'nodeOps.outbounds', icon: 'upload' },
  { id: 'routing', labelKey: 'nodeOps.routing', icon: 'note' },
  { id: 'config', labelKey: 'serverStatus.xrayConfig', icon: 'note' },
  { id: 'observatory', labelKey: 'serverStatus.xrayObservatory', icon: 'statusOn' },
  { id: 'versions', labelKey: 'serverStatus.xrayVersionsTitle', icon: 'download' },
  { id: 'tokens', labelKey: 'serverStatus.apiTokensTitle', icon: 'attach' },
  { id: 'keys', labelKey: 'serverStatus.keyGenerator', icon: 'snowflake' },
  { id: 'panel', labelKey: 'serverStatus.panelUpdate', icon: 'servers' },
];

const stringify = (value: unknown) => {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const getErrorMessage = (error: any, fallback: string) => (
  error?.response?.data?.detail
  || error?.response?.data?.error
  || error?.message
  || fallback
);

const tokenIdOf = (token: ApiTokenItem): number | null => {
  const raw = token.id ?? token.token_id;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
};

export function NodeOperationsModal({
  nodeId,
  nodeName,
  initialTab = 'traffic',
  onClose,
  onNodeChanged,
}: NodeOperationsModalProps) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [configMode, setConfigMode] = useState<'template' | 'running'>('template');
  const [activeTab, setActiveTab] = useState<NodeOpsTab>(initialTab);
  const [dataByTab, setDataByTab] = useState<Partial<Record<NodeOpsTab, unknown>>>({});
  const [loadingTab, setLoadingTab] = useState<NodeOpsTab | null>(null);
  const [error, setError] = useState('');
  const [versions, setVersions] = useState<string[]>([]);
  const [selectedVersion, setSelectedVersion] = useState('');
  const [tokens, setTokens] = useState<ApiTokenItem[]>([]);
  const [tokenName, setTokenName] = useState('');
  const [createdToken, setCreatedToken] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [keyLoading, setKeyLoading] = useState<KeyKind | null>(null);
  const [generatedKey, setGeneratedKey] = useState<{ label: string; value: unknown } | null>(null);
  const tabRequestIdRef = useRef(0);
  const tabAbortRef = useRef<AbortController | null>(null);

  const activeData = dataByTab[activeTab];
  const activeTabMeta = useMemo(() => tabs.find((tab) => tab.id === activeTab), [activeTab]);
  const activeTabLabel = t(activeTabMeta?.labelKey || 'common.details');

  const copyValue = useCallback(async (value: unknown, label = t('common.copy')) => {
    const text = stringify(value);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label}: ${t('subscriptions.copied', { defaultValue: 'Copied' })}`, 'success');
    } catch {
      toast(t('serverStatus.clipboardUnavailable'), 'error');
    }
  }, [t, toast]);

  const loadTab = useCallback(async (tab: NodeOpsTab, force = false) => {
    const requestId = ++tabRequestIdRef.current;
    const isCurrentRequest = () => requestId === tabRequestIdRef.current;
    tabAbortRef.current?.abort();
    tabAbortRef.current = null;
    setError('');
    if (tab === 'keys' || tab === 'panel' || tab === 'history' || tab === 'outboundsConfig' || tab === 'routing' || (tab === 'config' && configMode === 'template')) return;
    const controller = new AbortController();
    tabAbortRef.current = controller;
    setLoadingTab(tab);
    setError('');
    try {
      if (tab === 'traffic') {
        const payload = await getNodeTraffic(nodeId, { signal: controller.signal, force });
        if (isCurrentRequest()) setDataByTab((current) => ({ ...current, traffic: payload }));
      } else if (tab === 'online') {
        const payload = await getNodeOnlineClients(nodeId, { signal: controller.signal, force });
        if (isCurrentRequest()) setDataByTab((current) => ({ ...current, online: payload }));
      } else if (tab === 'outbounds') {
        const payload = await getOutboundsTraffic(nodeId, { signal: controller.signal, force });
        if (isCurrentRequest()) setDataByTab((current) => ({ ...current, outbounds: payload }));
      } else if (tab === 'observatory') {
        const payload = await getXrayObservatory(nodeId, { signal: controller.signal, force });
        if (isCurrentRequest()) setDataByTab((current) => ({ ...current, observatory: payload }));
      } else if (tab === 'config') {
        const payload = await getXrayConfig(nodeId, { signal: controller.signal, force });
        if (isCurrentRequest()) setDataByTab((current) => ({ ...current, config: payload }));
      } else if (tab === 'versions') {
        const payload = await getXrayVersions(nodeId, { signal: controller.signal, force });
        if (isCurrentRequest()) {
          setVersions(payload);
          setSelectedVersion((current) => current || payload[0] || '');
        }
      } else if (tab === 'tokens') {
        const payload = await getApiTokens(nodeId, { signal: controller.signal, force });
        if (isCurrentRequest()) setTokens(payload as ApiTokenItem[]);
      }
    } catch (err: any) {
      if (isCurrentRequest() && !controller.signal.aborted) setError(getErrorMessage(err, t(tab === 'outbounds' ? 'nodeOps.nodeUnavailable' : 'common.failed')));
    } finally {
      if (isCurrentRequest()) {
        setLoadingTab(null);
        tabAbortRef.current = null;
      }
    }
  }, [nodeId, t, configMode]);

  useEffect(() => {
    void loadTab(activeTab);
  }, [activeTab, loadTab]);

  useEffect(() => () => {
    tabRequestIdRef.current += 1;
    tabAbortRef.current?.abort();
    tabAbortRef.current = null;
  }, []);

  const handleInstallXray = async () => {
    if (!selectedVersion) return;
    if (!window.confirm(t('serverStatus.confirmInstallXray', { version: selectedVersion }))) return;
    setSaving(true);
    try {
      await installXray(nodeId, selectedVersion);
      toast(t('serverStatus.panelUpdateStarted'), 'success');
      onNodeChanged?.();
    } catch (err: any) {
      toast(getErrorMessage(err, t('common.failed')), 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdatePanel = async () => {
    if (!window.confirm(t('serverStatus.confirmUpdatePanel'))) return;
    setSaving(true);
    try {
      await updatePanel(nodeId);
      toast(t('serverStatus.panelUpdateStarted'), 'success');
      onNodeChanged?.();
    } catch (err: any) {
      toast(getErrorMessage(err, t('common.failed')), 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleResetAllTraffics = async () => {
    if (!window.confirm(t('serverStatus.confirmResetAllTraffics'))) return;
    setSaving(true);
    try {
      await resetAllNodeTraffics(nodeId);
      toast(t('nodes.resetAllTrafficsDone', { node: nodeName }), 'success');
      onNodeChanged?.();
    } catch (err: any) {
      toast(getErrorMessage(err, t('nodes.resetAllTrafficsFailed')), 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleCreateToken = async () => {
    const name = tokenName.trim();
    if (!name) return;
    setSaving(true);
    try {
      const payload = await createApiToken(nodeId, name);
      setCreatedToken(payload);
      setTokenName('');
      await loadTab('tokens');
      toast(t('app.success'), 'success');
    } catch (err: any) {
      toast(getErrorMessage(err, t('common.failed')), 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteToken = async (token: ApiTokenItem) => {
    const tokenId = tokenIdOf(token);
    if (tokenId === null) return;
    if (!window.confirm(t('serverStatus.confirmDeleteApiToken'))) return;
    setSaving(true);
    try {
      await deleteApiToken(nodeId, tokenId);
      await loadTab('tokens');
      toast(t('serverStatus.apiTokenDeleted'), 'success');
    } catch (err: any) {
      toast(getErrorMessage(err, t('common.failed')), 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleToken = async (token: ApiTokenItem) => {
    const tokenId = tokenIdOf(token);
    if (tokenId === null) return;
    const nextEnabled = !Boolean(token.enabled);
    setSaving(true);
    try {
      await setApiTokenEnabled(nodeId, tokenId, nextEnabled);
      await loadTab('tokens');
      toast(t(nextEnabled ? 'serverStatus.apiTokenEnabled' : 'serverStatus.apiTokenDisabled'), 'success');
    } catch (err: any) {
      toast(getErrorMessage(err, t('common.failed')), 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateKey = async (kind: KeyKind) => {
    setKeyLoading(kind);
    try {
      let label = '';
      let value: unknown;
      if (kind === 'uuid') {
        label = 'UUID';
        value = await generateNodeUuid(nodeId);
      } else if (kind === 'x25519') {
        label = 'X25519';
        value = await generateNodeX25519(nodeId);
      } else if (kind === 'vless') {
        label = t('inbounds.vlessDecryption');
        value = await generateNodeVlessEncryption(nodeId);
      } else {
        label = 'ML-DSA-65';
        value = await generateNodeMldsa65(nodeId);
      }
      setGeneratedKey({ label, value });
      await copyValue(value, label);
    } catch (err: any) {
      toast(getErrorMessage(err, t('common.failed')), 'error');
    } finally {
      setKeyLoading(null);
    }
  };

  const renderJsonPanel = (value: unknown, emptyLabel: string) => {
    const text = stringify(value);
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <span className={chipClass}>
            <UIIcon name={loadingTab === activeTab ? 'spinner' : 'check'} size={13} />
            {loadingTab === activeTab ? t('app.loading') : activeTabLabel}
          </span>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button type="button" className={buttonSecondaryClass} onClick={() => void loadTab(activeTab, true)} disabled={loadingTab !== null}>
              <UIIcon name="refresh" size={14} />
              {t('common.refresh')}
            </button>
            <button type="button" className={buttonSecondaryClass} onClick={() => void copyValue(value)} disabled={!text}>
              <UIIcon name="copy" size={14} />
              {t('common.copy')}
            </button>
          </div>
        </div>
        <LazyJsonEditor readOnly label={activeTabLabel} value={text || ''} />
        {!text && <span>{emptyLabel}</span>}
      </div>
    );
  };

  const renderVersions = () => (
    <div className="space-y-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <select
          className="form-select min-w-[220px]"
          value={selectedVersion}
          onChange={(event) => setSelectedVersion(event.target.value)}
          disabled={loadingTab === 'versions' || versions.length === 0}
        >
          {versions.map((version) => <option key={version} value={version}>{version}</option>)}
        </select>
        <button type="button" className={buttonPrimaryClass} onClick={handleInstallXray} disabled={!selectedVersion || saving}>
          <UIIcon name="download" size={14} />
          {t('serverStatus.install')}
        </button>
        <button type="button" className={buttonSecondaryClass} onClick={() => void loadTab('versions', true)} disabled={loadingTab !== null}>
          <UIIcon name="refresh" size={14} />
          {t('common.refresh')}
        </button>
      </div>
      {versions.length === 0 ? (
        <div className="panel-block px-4 py-8 text-center text-sm">
          {loadingTab === 'versions' ? t('app.loading') : t('serverStatus.noVersionsAvailable')}
        </div>
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {versions.map((version) => (
            <button
              key={version}
              type="button"
              aria-pressed={selectedVersion === version}
              className={`${buttonSecondaryClass} justify-start ${selectedVersion === version ? 'node-ops-selected' : ''}`}
              onClick={() => setSelectedVersion(version)}
            >
              <UIIcon name={selectedVersion === version ? 'check' : 'download'} size={14} />
              {version}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const renderTokens = () => (
    <div className="space-y-4">
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
        <input
          className={`${inputClass} flex-1`}
          value={tokenName}
          onChange={(event) => setTokenName(event.target.value)}
          placeholder={t('serverStatus.newTokenName')}
        />
        <button type="button" className={buttonPrimaryClass} onClick={handleCreateToken} disabled={saving || !tokenName.trim()}>
          <UIIcon name="plus" size={14} />
          {t('serverStatus.createTokenShort')}
        </button>
        <button type="button" className={buttonSecondaryClass} onClick={() => void loadTab('tokens', true)} disabled={loadingTab !== null}>
          <UIIcon name="refresh" size={14} />
          {t('common.refresh')}
        </button>
      </div>
      {createdToken !== null && (
        <div className="panel-block space-y-2 p-3">
          <div className="flex min-w-0 items-center justify-between gap-2">
            <span className="text-xs node-ops-success">{t('app.success')}</span>
            <button type="button" className={buttonSecondaryClass} onClick={() => void copyValue(createdToken)}>
              <UIIcon name="copy" size={14} />
              {t('common.copy')}
            </button>
          </div>
          <pre className="node-ops-pre max-h-48 overflow-auto p-3 font-mono text-xs">{stringify(createdToken)}</pre>
        </div>
      )}
      {tokens.length === 0 ? (
        <div className="panel-block px-4 py-8 text-center text-sm">
          {loadingTab === 'tokens' ? t('app.loading') : t('serverStatus.noApiTokens')}
        </div>
      ) : (
        <div className="overflow-auto">
          <table className="table table-sm w-full">
            <thead>
              <tr>
                <th className="px-3 py-2">{t('common.name')}</th>
                <th className="w-28 px-3 py-2">{t('common.status')}</th>
                <th className="w-40 px-3 py-2 text-right">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((token, index) => {
                const tokenId = tokenIdOf(token);
                const tokenLabel = String(token.name || token.token || tokenId || `token-${index + 1}`);
                return (
                  <tr key={`${tokenId ?? index}:${tokenLabel}`}>
                    <td className="min-w-0 px-3 py-2">
                      <span className="block truncate font-mono " title={tokenLabel}>{tokenLabel}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={chipClass}>{token.enabled === false ? t('common.disabled') : t('common.enabled')}</span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-2">
                        <button type="button" className={buttonSecondaryClass} onClick={() => void handleToggleToken(token)} disabled={saving || tokenId === null}>
                          {token.enabled === false ? t('common.enable') : t('common.disable')}
                        </button>
                        <button type="button" className={buttonDangerClass} onClick={() => void handleDeleteToken(token)} disabled={saving || tokenId === null}>
                          <UIIcon name="trash" size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  const renderKeys = () => (
    <div className="space-y-4">
      <p className="text-sm ">{t('nodeOps.keyExplanation')}</p>
      <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
        {[
          { kind: 'uuid' as const, label: 'UUID' },
          { kind: 'x25519' as const, label: 'X25519' },
          { kind: 'vless' as const, label: t('nodeOps.vlessEncryption') },
          { kind: 'mldsa65' as const, label: 'ML-DSA-65' },
        ].map((item) => (
          <div key={item.kind} className="min-w-0 space-y-1"><button
            type="button"
            className={buttonSecondaryClass}
            onClick={() => void handleGenerateKey(item.kind)}
            disabled={keyLoading !== null}
          >
            <UIIcon name={keyLoading === item.kind ? 'spinner' : 'snowflake'} size={14} />
            {t('nodeOps.generateKey', { type: item.label })}
          </button><p className="text-xs node-ops-muted">{t(`nodeOps.keyHint_${item.kind}`)}</p></div>
        ))}
      </div>
      {generatedKey ? (
        <div className="space-y-3">
          <div className="flex min-w-0 items-center justify-between gap-2">
            <span className={chipClass}>{generatedKey.label}</span>
            <button type="button" className={buttonSecondaryClass} onClick={() => void copyValue(generatedKey.value, generatedKey.label)}>
              <UIIcon name="copy" size={14} />
              {t('common.copy')}
            </button>
          </div>
          <pre className={preClass}>{stringify(generatedKey.value)}</pre>
        </div>
      ) : (
        <div className="panel-block px-4 py-8 text-center text-sm">
          {t('serverStatus.keyGenerator')}
        </div>
      )}
    </div>
  );

  const renderPanelActions = () => (
    <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
      <button type="button" className={buttonPrimaryClass} onClick={handleUpdatePanel} disabled={saving}>
        <UIIcon name="servers" size={14} />
        {t('serverStatus.updatePanel')}
      </button>
      <button type="button" className={buttonDangerClass} onClick={handleResetAllTraffics} disabled={saving}>
        <UIIcon name="warning" size={14} />
        {t('nodes.resetAllTraffics')}
      </button>
    </div>
  );

  return (
    <div
      data-node-operations
      className={overlayClass}
      role="dialog"
      aria-modal="true"
      aria-label={`${nodeName} ${activeTabLabel}`}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={panelClass}>
        <div className={panelHeaderClass}>
          <div className="min-w-0">
            <h3 className="modal-title truncate">{activeTabLabel}</h3>
            <p className="mt-1 truncate font-mono text-xs node-ops-muted">{nodeName} / #{nodeId}</p>
          </div>
          <button type="button" className="btn btn-sm btn-ghost-secondary" onClick={onClose} aria-label={t('common.close')}>
            <UIIcon name="x" size={15} />
          </button>
        </div>

        <div className={panelBodyClass}>
          <aside className={sideClass}>
            <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-1">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  aria-current={activeTab === tab.id ? 'page' : undefined}
                  className={`${buttonSecondaryClass} justify-start ${activeTab === tab.id ? 'node-ops-selected' : ''}`}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <UIIcon name={tab.icon} size={14} />
                  <span className="min-w-0 truncate">{t(tab.labelKey)}</span>
                </button>
              ))}
            </div>
          </aside>

          <main className={contentClass}>
            {error && (
              <div className="node-ops-error mb-4 text-sm">
                {error}
              </div>
            )}

            {activeTab === 'history' ? <SystemHistory nodeId={nodeId} />
              : activeTab === 'outboundsConfig' ? <XrayTemplateEditor key="outbounds" nodeId={nodeId} section="outbounds" />
              : activeTab === 'routing' ? <XrayTemplateEditor key="routing" nodeId={nodeId} section="routing" />
              : activeTab === 'config' ? <div className="flex min-h-0 flex-1 flex-col gap-3"><div className="flex flex-wrap gap-2">{(['template', 'running'] as const).map((mode) => <button type="button" key={mode} aria-pressed={configMode === mode} className={`seg-tab ${configMode === mode ? 'seg-tab--active' : ''}`} onClick={() => setConfigMode(mode)}>{t(`nodeOps.${mode}`)}</button>)}</div>{configMode === 'template' ? <XrayTemplateEditor nodeId={nodeId} section="all" /> : renderJsonPanel(activeData, t('common.noRecordsFound'))}</div>
              : activeTab === 'traffic' || activeTab === 'online' || activeTab === 'outbounds' ? <NodeDataView key={activeTab} nodeId={nodeId} kind={activeTab} data={activeData} loading={loadingTab === activeTab} refresh={() => void loadTab(activeTab, true)} copy={() => void copyValue(activeData)} />
              : activeTab === 'observatory' ? <div className="flex min-h-0 flex-1 flex-col gap-3"><div className="panel-block p-3 text-sm"><p>{t('nodeOps.observatoryHint')}</p><pre className="node-ops-pre mt-2 overflow-auto p-2 font-mono text-xs">{observatoryExample}</pre></div>{renderJsonPanel(activeData, t('common.noRecordsFound'))}</div>
              : activeTab === 'versions' ? renderVersions()
              : activeTab === 'tokens' ? renderTokens()
                : activeTab === 'keys' ? renderKeys()
                  : activeTab === 'panel' ? renderPanelActions()
                    : renderJsonPanel(activeData, t('common.noRecordsFound'))}
          </main>
        </div>
      </div>
    </div>
  );
}
