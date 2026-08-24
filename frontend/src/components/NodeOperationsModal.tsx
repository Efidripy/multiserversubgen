import { useCallback, useEffect, useMemo, useState } from 'react';
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
  getXrayMetrics,
  getXrayObservatory,
  getXrayVersions,
  installXray,
  resetAllNodeTraffics,
  setApiTokenEnabled,
  updatePanel,
} from '../api/serverOps';
import { useToast } from './Toast';
import { UIIcon, type IconName } from './UIIcon';

export type NodeOpsTab =
  | 'traffic'
  | 'online'
  | 'metrics'
  | 'outbounds'
  | 'observatory'
  | 'config'
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

const overlayClass = 'fixed inset-0 z-50 flex items-center justify-center bg-black/75 px-3 py-5';
const panelClass = 'flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-cyan-300/20 bg-[#0f1420] text-slate-100 shadow-2xl ring-1 ring-cyan-300/10';
const panelHeaderClass = 'flex min-w-0 items-start justify-between gap-4 border-b border-cyan-300/20 px-4 py-4 sm:px-5';
const panelBodyClass = 'grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[220px_minmax(0,1fr)]';
const sideClass = 'min-w-0 border-b border-cyan-300/20 p-3 lg:border-b-0 lg:border-r lg:p-4';
const contentClass = 'min-w-0 overflow-y-auto p-4 sm:p-5';
const buttonBaseClass = 'inline-flex h-9 min-w-0 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-transparent px-3 text-xs font-medium uppercase tracking-[0.12em] transition disabled:cursor-not-allowed disabled:opacity-45';
const buttonPrimaryClass = `${buttonBaseClass} border-cyan-300/25 bg-cyan-400 text-[#06111f] hover:bg-cyan-300`;
const buttonSecondaryClass = `${buttonBaseClass} border-cyan-500/20 bg-[#0a0e1a] text-slate-300 hover:bg-[#101827] hover:text-cyan-200`;
const buttonDangerClass = `${buttonBaseClass} border-rose-400/25 bg-rose-500 text-white hover:bg-rose-400`;
const inputClass = 'h-9 min-w-0 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 font-mono text-xs font-light text-slate-100 outline-none transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10 placeholder:text-slate-600';
const preClass = 'max-h-[52vh] min-h-[220px] overflow-auto rounded-lg border border-cyan-500/20 bg-[#07101d] p-3 font-mono text-xs leading-5 text-slate-200';
const chipClass = 'inline-flex min-w-0 items-center gap-2 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-2 py-1 text-[11px] font-light text-slate-300';

const tabs: Array<{ id: NodeOpsTab; labelKey: string; icon: IconName }> = [
  { id: 'traffic', labelKey: 'nav.traffic', icon: 'traffic' },
  { id: 'online', labelKey: 'serverStatus.onlineClients', icon: 'clients' },
  { id: 'metrics', labelKey: 'serverStatus.xrayMetricsTitle', icon: 'monitoring' },
  { id: 'outbounds', labelKey: 'serverStatus.outboundTraffic', icon: 'upload' },
  { id: 'observatory', labelKey: 'serverStatus.xrayObservatory', icon: 'statusOn' },
  { id: 'config', labelKey: 'serverStatus.viewXrayConfig', icon: 'note' },
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

  const loadTab = useCallback(async (tab: NodeOpsTab) => {
    if (tab === 'keys' || tab === 'panel') return;
    setLoadingTab(tab);
    setError('');
    try {
      if (tab === 'traffic') {
        const payload = await getNodeTraffic(nodeId);
        setDataByTab((current) => ({ ...current, traffic: payload }));
      } else if (tab === 'online') {
        const payload = await getNodeOnlineClients(nodeId);
        setDataByTab((current) => ({ ...current, online: payload }));
      } else if (tab === 'metrics') {
        const payload = await getXrayMetrics(nodeId);
        setDataByTab((current) => ({ ...current, metrics: payload }));
      } else if (tab === 'outbounds') {
        const payload = await getOutboundsTraffic(nodeId);
        setDataByTab((current) => ({ ...current, outbounds: payload }));
      } else if (tab === 'observatory') {
        const payload = await getXrayObservatory(nodeId);
        setDataByTab((current) => ({ ...current, observatory: payload }));
      } else if (tab === 'config') {
        const payload = await getXrayConfig(nodeId);
        setDataByTab((current) => ({ ...current, config: payload }));
      } else if (tab === 'versions') {
        const payload = await getXrayVersions(nodeId);
        setVersions(payload);
        setSelectedVersion((current) => current || payload[0] || '');
      } else if (tab === 'tokens') {
        const payload = await getApiTokens(nodeId);
        setTokens(payload as ApiTokenItem[]);
      }
    } catch (err: any) {
      setError(getErrorMessage(err, t('common.failed')));
    } finally {
      setLoadingTab(null);
    }
  }, [nodeId, t]);

  useEffect(() => {
    void loadTab(activeTab);
  }, [activeTab, loadTab]);

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
      <div className="space-y-3">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <span className={chipClass}>
            <UIIcon name={loadingTab === activeTab ? 'spinner' : 'check'} size={13} />
            {loadingTab === activeTab ? t('app.loading') : activeTabLabel}
          </span>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button type="button" className={buttonSecondaryClass} onClick={() => void loadTab(activeTab)} disabled={loadingTab !== null}>
              <UIIcon name="refresh" size={14} />
              {t('common.refresh')}
            </button>
            <button type="button" className={buttonSecondaryClass} onClick={() => void copyValue(value)} disabled={!text}>
              <UIIcon name="copy" size={14} />
              {t('common.copy')}
            </button>
          </div>
        </div>
        <pre className={preClass}>{text || emptyLabel}</pre>
      </div>
    );
  };

  const renderVersions = () => (
    <div className="space-y-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <select
          className={`${inputClass} min-w-[220px]`}
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
        <button type="button" className={buttonSecondaryClass} onClick={() => void loadTab('versions')} disabled={loadingTab !== null}>
          <UIIcon name="refresh" size={14} />
          {t('common.refresh')}
        </button>
      </div>
      {versions.length === 0 ? (
        <div className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
          {loadingTab === 'versions' ? t('app.loading') : t('serverStatus.noVersionsAvailable')}
        </div>
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {versions.map((version) => (
            <button
              key={version}
              type="button"
              className={`${buttonSecondaryClass} justify-start ${selectedVersion === version ? 'border-cyan-300/50 bg-cyan-400/10 text-cyan-200' : ''}`}
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
        <button type="button" className={buttonSecondaryClass} onClick={() => void loadTab('tokens')} disabled={loadingTab !== null}>
          <UIIcon name="refresh" size={14} />
          {t('common.refresh')}
        </button>
      </div>
      {createdToken !== null && (
        <div className="space-y-2 rounded-lg border border-emerald-400/20 bg-emerald-400/5 p-3">
          <div className="flex min-w-0 items-center justify-between gap-2">
            <span className="text-xs font-medium uppercase tracking-[0.14em] text-emerald-200">{t('app.success')}</span>
            <button type="button" className={buttonSecondaryClass} onClick={() => void copyValue(createdToken)}>
              <UIIcon name="copy" size={14} />
              {t('common.copy')}
            </button>
          </div>
          <pre className="max-h-48 overflow-auto rounded-md bg-[#07101d] p-3 font-mono text-xs text-slate-200">{stringify(createdToken)}</pre>
        </div>
      )}
      {tokens.length === 0 ? (
        <div className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
          {loadingTab === 'tokens' ? t('app.loading') : t('serverStatus.noApiTokens')}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-cyan-500/20">
          <table className="w-full table-fixed border-collapse text-left text-xs">
            <thead className="bg-[#0a0e1a] text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-3 py-2">{t('common.name')}</th>
                <th className="w-28 px-3 py-2">{t('common.status')}</th>
                <th className="w-40 px-3 py-2 text-right">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {tokens.map((token, index) => {
                const tokenId = tokenIdOf(token);
                const tokenLabel = String(token.name || token.token || tokenId || `token-${index + 1}`);
                return (
                  <tr key={`${tokenId ?? index}:${tokenLabel}`} className="bg-[#0f1420]">
                    <td className="min-w-0 px-3 py-2">
                      <span className="block truncate font-mono text-slate-200" title={tokenLabel}>{tokenLabel}</span>
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
      <div className="grid min-w-0 grid-cols-2 gap-2 lg:grid-cols-4">
        {[
          { kind: 'uuid' as const, label: 'UUID' },
          { kind: 'x25519' as const, label: 'X25519' },
          { kind: 'vless' as const, label: t('clients.generateVlessEncryption') },
          { kind: 'mldsa65' as const, label: 'ML-DSA-65' },
        ].map((item) => (
          <button
            key={item.kind}
            type="button"
            className={buttonSecondaryClass}
            onClick={() => void handleGenerateKey(item.kind)}
            disabled={keyLoading !== null}
          >
            <UIIcon name={keyLoading === item.kind ? 'spinner' : 'snowflake'} size={14} />
            {item.label}
          </button>
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
        <div className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
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
            <h3 className="truncate text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">{activeTabLabel}</h3>
            <p className="mt-1 truncate font-mono text-xs text-slate-500">{nodeName} / #{nodeId}</p>
          </div>
          <button type="button" className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-cyan-500/20 bg-[#0a0e1a] text-slate-300 hover:text-cyan-200" onClick={onClose} aria-label={t('common.close')}>
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
                  className={`${buttonSecondaryClass} justify-start ${activeTab === tab.id ? 'border-cyan-300/50 bg-cyan-400/10 text-cyan-200' : ''}`}
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
              <div className="mb-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                {error}
              </div>
            )}

            {activeTab === 'versions' ? renderVersions()
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
