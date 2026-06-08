import React, { useEffect, useState } from 'react';
import { useToast } from './Toast';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { getAuth } from '../auth';
import { ChoiceChips } from './ChoiceChips';
import { UIIcon } from './UIIcon';

interface Stats {
  count: number;
  last: string;
}

interface Node {
  id: number;
  name: string;
  ip: string;
  port: string;
}

interface SubscriptionGroup {
  identifier: string;
  emails: string[];
  count: number;
}

const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const shellClass = 'min-h-screen min-w-0 overflow-hidden bg-[#0a0e1a] p-4 text-slate-100 sm:p-5 lg:p-6';
const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]';
const insetPanelClass = 'min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4';
const titleClass = 'text-xs font-medium uppercase tracking-[0.14em] text-slate-300';
const hintClass = 'mt-1 text-xs font-light leading-5 text-slate-500';
const metricClass = 'font-mono tabular-nums whitespace-nowrap';
const headerButtonClass = 'inline-flex whitespace-nowrap text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500 transition hover:text-cyan-300';
const primaryButtonClass = 'inline-flex h-10 min-w-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/25 bg-gradient-to-r from-cyan-400 to-emerald-300 px-5 text-xs font-medium uppercase tracking-[0.14em] text-[#06111f] shadow-[0_14px_38px_rgba(34,211,238,0.18)] transition hover:from-cyan-300 hover:to-emerald-200 disabled:cursor-not-allowed disabled:opacity-45';
const secondaryButtonClass = 'inline-flex h-10 min-w-0 items-center justify-center gap-2 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 text-xs font-medium uppercase tracking-[0.14em] text-slate-300 transition hover:bg-[#0f1420] hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const iconButtonClass = 'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-cyan-500/20 bg-[#0a0e1a] text-slate-300 transition hover:bg-[#0f1420] hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const inputClass = 'block w-full min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2.5 text-sm font-light text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10';
const codeInputClass = 'block w-full min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-3 py-2.5 font-mono text-xs font-light text-slate-200 outline-none focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/10';
const metaLabelClass = 'text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500';
const metaValueClass = 'mt-1 block min-w-0 text-xs font-light text-slate-200';
const cardMetaValueClass = 'mt-1 block min-w-0 truncate text-right text-xs font-light text-slate-200';

export const SubscriptionManager: React.FC<{ apiUrl: string }> = ({ apiUrl }) => {
  const { toast } = useToast();
  const { t } = useTranslation();
  const [emails, setEmails] = useState<string[]>([]);
  const [qrUrl, setQrUrl] = useState('');
  const [showQr, setShowQr] = useState(false);
  const [emailSearch, setEmailSearch] = useState('');
  const [stats, setStats] = useState<Record<string, Stats>>({});
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'individual' | 'grouped'>('individual');
  const [groups, setGroups] = useState<SubscriptionGroup[]>([]);
  const [filterProtocol, setFilterProtocol] = useState('');
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [individualSortField, setIndividualSortField] = useState<'email' | 'downloads' | 'last'>('email');
  const [individualSortDir, setIndividualSortDir] = useState<'asc' | 'desc'>('asc');
  const [groupSortField, setGroupSortField] = useState<'name' | 'count'>('count');
  const [groupSortDir, setGroupSortDir] = useState<'asc' | 'desc'>('desc');
  const [deliveryTransport, setDeliveryTransport] = useState<'all' | 'ws' | 'grpc'>('all');
  const [deliveryFormat, setDeliveryFormat] = useState<'base64' | 'json' | 'raw'>('base64');

  const loadEmails = async () => {
    setLoading(true);
    setError('');
    setSuccessMessage('');
    try {
      const res = await api.get('/v1/emails', {
        params: { _ts: Date.now() },
        headers: { 'Cache-Control': 'no-cache' },
        auth: { username: getAuth().user, password: getAuth().password },
      });
      setEmails(res.data.emails || []);
      setStats(res.data.stats || {});
      setSuccessMessage(t('subscriptions.emailsRefreshed'));
      setTimeout(() => setSuccessMessage(''), 3000);
    } catch (err: any) {
      console.error('Failed to load subscriptions:', err);
      setError(err.response?.data?.detail || t('subscriptions.refreshEmailsFailed'));
    } finally {
      setLoading(false);
    }
  };

  const loadNodes = async () => {
    try {
      const res = await api.get('/v1/nodes', {
        auth: { username: getAuth().user, password: getAuth().password },
      });
      setNodes(res.data || []);
    } catch (err) {
      console.error('Failed to load nodes:', err);
    }
  };

  const analyzeGroups = () => {
    const groupMap = new Map<string, string[]>();

    emails.forEach((email) => {
      const domain = email.split('@')[1] || 'unknown';
      if (!groupMap.has(domain)) groupMap.set(domain, []);
      groupMap.get(domain)!.push(email);

      const match = email.match(/^([a-zA-Z]{3,})/);
      if (match) {
        const prefix = match[1].toLowerCase();
        if (!groupMap.has(prefix)) groupMap.set(prefix, []);
        groupMap.get(prefix)!.push(email);
      }
    });

    const groupList: SubscriptionGroup[] = [];
    groupMap.forEach((emailList, identifier) => {
      if (emailList.length >= 2) {
        groupList.push({
          identifier,
          emails: emailList,
          count: emailList.length,
        });
      }
    });

    groupList.sort((a, b) => b.count - a.count);
    setGroups(groupList);
  };

  useEffect(() => {
    loadEmails();
    loadNodes();
  }, []);

  useEffect(() => {
    if (viewMode === 'grouped') {
      analyzeGroups();
    }
  }, [emails, viewMode]);

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast(t('subscriptions.copied'), 'info');
    } catch {
      const el = document.createElement('textarea');
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
  };

  const buildSubscriptionUrl = (email: string, isGrouped = false) => {
    const baseUrl = isGrouped ? `${apiUrl}/v1/sub-grouped/${email}` : `${apiUrl}/v1/sub/${email}`;
    const params = new URLSearchParams();
    if (filterProtocol) params.append('protocol', filterProtocol);
    if (selectedNodes.length > 0) params.append('nodes', selectedNodes.join(','));
    if (deliveryTransport !== 'all') params.append('transport', deliveryTransport);
    if (deliveryFormat !== 'base64') params.append('format', deliveryFormat);
    return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
  };

  const compareText = (a: string, b: string) =>
    a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });

  const filteredEmails = emailSearch.trim()
    ? emails.filter((email) => email.toLowerCase().includes(emailSearch.trim().toLowerCase()))
    : emails;

  const sortedEmails = [...filteredEmails].sort((a, b) => {
    const factor = individualSortDir === 'asc' ? 1 : -1;
    const byEmail = compareText(a, b);
    const byDownloads = (stats[a]?.count || 0) - (stats[b]?.count || 0);
    const aLast = Date.parse(stats[a]?.last || '') || 0;
    const bLast = Date.parse(stats[b]?.last || '') || 0;
    const byLast = aLast - bLast;

    if (individualSortField === 'email') {
      if (byEmail !== 0) return byEmail * factor;
      return byDownloads * factor;
    }
    if (individualSortField === 'downloads') {
      if (byDownloads !== 0) return byDownloads * factor;
      return byEmail;
    }
    if (byLast !== 0) return byLast * factor;
    return byEmail;
  });

  const sortedGroups = [...groups].sort((a, b) => {
    const factor = groupSortDir === 'asc' ? 1 : -1;
    const byName = compareText(a.identifier, b.identifier);
    const byCount = a.count - b.count;
    if (groupSortField === 'name') {
      if (byName !== 0) return byName * factor;
      return byCount * factor;
    }
    if (byCount !== 0) return byCount * factor;
    return byName;
  });

  const groupSortDirectionLabels = groupSortField === 'name'
    ? { asc: t('subscriptions.sortAZ'), desc: t('subscriptions.sortZA') }
    : { asc: t('subscriptions.sortSmallLarge'), desc: t('subscriptions.sortLargeSmall') };

  const applyIndividualSortFromHeader = (field: 'email' | 'downloads' | 'last') => {
    if (individualSortField === field) {
      setIndividualSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setIndividualSortField(field);
    setIndividualSortDir(field === 'downloads' || field === 'last' ? 'desc' : 'asc');
  };

  const individualSortIndicator = (field: 'email' | 'downloads' | 'last') =>
    individualSortField === field ? (individualSortDir === 'asc' ? ' ^' : ' v') : '';

  const toggleNodeSelection = (nodeName: string) => {
    setSelectedNodes((prev) =>
      prev.includes(nodeName) ? prev.filter((node) => node !== nodeName) : [...prev, nodeName],
    );
  };

  const renderIndividualActions = (email: string) => {
    const subscriptionUrl = buildSubscriptionUrl(email);
    return (
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          className={iconButtonClass}
          title={t('common.copy')}
          aria-label={t('common.copy')}
          onClick={() => copyToClipboard(subscriptionUrl)}
        >
          <UIIcon name="copy" size={15} />
        </button>
        <button
          type="button"
          className={iconButtonClass}
          title={t('subscriptions.showQrCode')}
          aria-label={t('subscriptions.showQrCode')}
          onClick={() => {
            setQrUrl(subscriptionUrl);
            setShowQr(true);
          }}
        >
          <UIIcon name="subscriptions" size={15} />
        </button>
      </div>
    );
  };

  const renderGroupActions = (group: SubscriptionGroup) => {
    const groupedUrl = buildSubscriptionUrl(group.identifier, true);
    return (
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          className={iconButtonClass}
          title={t('common.copy')}
          aria-label={t('common.copy')}
          onClick={() => copyToClipboard(groupedUrl)}
        >
          <UIIcon name="copy" size={15} />
        </button>
        <button
          type="button"
          className={iconButtonClass}
          title={t('subscriptions.copyGroupLinksTitle')}
          aria-label={t('subscriptions.copyGroupLinksTitle')}
          onClick={async () => {
            const links = group.emails.map((email) => buildSubscriptionUrl(email)).join('\n');
            await copyToClipboard(links);
          }}
        >
          <UIIcon name="link" size={15} />
        </button>
      </div>
    );
  };

  const filtersActive = Boolean(
    filterProtocol || selectedNodes.length > 0 || deliveryTransport !== 'all' || deliveryFormat !== 'base64',
  );

  if (loading && emails.length === 0) {
    return (
      <div className={shellClass}>
        <div className="rounded-lg border border-cyan-500/20 bg-[#0f1420] px-4 py-8 text-center text-sm text-slate-500">
          {t('app.loading')}
        </div>
      </div>
    );
  }

  return (
    <div className={shellClass}>
      <section className={cn(panelClass, 'mb-4')}>
        <div className="mb-4 flex min-w-0 flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <h2 className="flex min-w-0 items-center gap-2 text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">
              <UIIcon name="subscriptions" size={16} />
              {t('subscriptions.controlsTitle')}
            </h2>
            <p className={hintClass}>{t('subscriptions.controlsHint')}</p>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button type="button" className={primaryButtonClass} onClick={loadEmails} disabled={loading}>
              <UIIcon name={loading ? 'spinner' : 'refresh'} size={15} />
              <span className="whitespace-nowrap">{t('subscriptions.refreshEmails')}</span>
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              title={t('subscriptions.copyAllLinksTitle')}
              onClick={async () => {
                const allLinks = filteredEmails.map((email) => buildSubscriptionUrl(email));
                await copyToClipboard(allLinks.join('\n'));
              }}
              disabled={filteredEmails.length === 0}
            >
              <UIIcon name="copy" size={15} />
              <span className="whitespace-nowrap">{t('subscriptions.copyAllLinks', { count: filteredEmails.length })}</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </div>
        )}
        {successMessage && (
          <div className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {successMessage}
          </div>
        )}

        <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className={insetPanelClass}>
            <div className="mb-4 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <h3 className={titleClass}>{t('subscriptions.deliveryProfile')}</h3>
                <p className={hintClass}>{t('subscriptions.deliveryHint')}</p>
              </div>
              <div className="flex min-w-0 flex-wrap gap-2">
                <button
                  type="button"
                  className={cn(
                    secondaryButtonClass,
                    viewMode === 'individual' && 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200',
                  )}
                  onClick={() => setViewMode('individual')}
                >
                  <UIIcon name="user" size={14} />
                  <span className="whitespace-nowrap">{t('subscriptions.individual')}</span>
                </button>
                <button
                  type="button"
                  className={cn(
                    secondaryButtonClass,
                    viewMode === 'grouped' && 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200',
                  )}
                  onClick={() => setViewMode('grouped')}
                >
                  <UIIcon name="folder" size={14} />
                  <span className="whitespace-nowrap">{t('subscriptions.grouped')}</span>
                </button>
              </div>
            </div>

            <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-3">
              <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4">
                <label className={titleClass}>{t('subscriptions.subscriptionProfile')}</label>
                <div className="mt-3 min-w-0">
                  <ChoiceChips
                    options={[
                      { value: '', label: t('common.all') },
                      { value: 'vless', label: 'VLESS' },
                      { value: 'vmess', label: 'VMess' },
                      { value: 'trojan', label: 'Trojan' },
                    ]}
                    value={filterProtocol}
                    onChange={(value) => setFilterProtocol(value)}
                  />
                </div>
              </div>
              <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4">
                <label className={titleClass}>{t('subscriptions.transportHint')}</label>
                <div className="mt-3 min-w-0">
                  <ChoiceChips
                    options={[
                      { value: 'all', label: t('common.all') },
                      { value: 'ws', label: 'WS' },
                      { value: 'grpc', label: 'gRPC' },
                    ]}
                    value={deliveryTransport}
                    onChange={(value) => setDeliveryTransport(value)}
                  />
                </div>
              </div>
              <div className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4">
                <label className={titleClass}>{t('subscriptions.outputFormat')}</label>
                <div className="mt-3 min-w-0">
                  <ChoiceChips
                    options={[
                      { value: 'base64', label: 'Base64' },
                      { value: 'json', label: 'JSON' },
                      { value: 'raw', label: 'Raw' },
                    ]}
                    value={deliveryFormat}
                    onChange={(value) => setDeliveryFormat(value)}
                  />
                </div>
              </div>
            </div>
          </div>

          <aside className={insetPanelClass}>
            <div className="min-w-0">
              <h3 className={titleClass}>{t('subscriptions.nodeFilter')}</h3>
              <p className={hintClass}>{t('subscriptions.searchEmailsPlaceholder')}</p>
            </div>

            <div className="mt-4">
              <div className="relative min-w-0">
                <UIIcon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-600" />
                <input
                  type="text"
                  className={cn(inputClass, 'pl-10')}
                  placeholder={t('subscriptions.searchEmailsPlaceholder')}
                  value={emailSearch}
                  onChange={(e) => setEmailSearch(e.target.value)}
                />
              </div>
            </div>

            <div className="mt-4 flex min-w-0 flex-wrap gap-2">
              {nodes.map((node) => {
                const active = selectedNodes.includes(node.name);
                return (
                  <button
                    key={node.id}
                    type="button"
                    className={cn(
                      secondaryButtonClass,
                      'h-9 px-3 text-[11px]',
                      active && 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200',
                    )}
                    onClick={() => toggleNodeSelection(node.name)}
                  >
                    {active && <UIIcon name="check" size={13} />}
                    <span className="min-w-0 truncate">{node.name}</span>
                  </button>
                );
              })}
              {selectedNodes.length > 0 && (
                <button type="button" className={secondaryButtonClass} onClick={() => setSelectedNodes([])}>
                  <UIIcon name="clear" size={14} />
                  <span className="whitespace-nowrap">{t('common.clear')}</span>
                </button>
              )}
            </div>

            {filtersActive && (
              <div className="mt-4 rounded-lg border border-cyan-400/20 bg-cyan-400/5 px-3 py-3 text-xs text-slate-300">
                <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-cyan-200">
                  {t('subscriptions.activeFilters')}
                </span>
                <div className="mt-2 flex min-w-0 flex-wrap gap-2 text-slate-400">
                  {filterProtocol && <span className={metricClass}>{t('subscriptions.protocolFilter')}: {filterProtocol.toUpperCase()}</span>}
                  {selectedNodes.length > 0 && <span className="min-w-0 truncate">{t('subscriptions.nodeFilters')}: {selectedNodes.join(', ')}</span>}
                  {deliveryTransport !== 'all' && <span className={metricClass}>{t('subscriptions.transportHint')}: {deliveryTransport.toUpperCase()}</span>}
                  {deliveryFormat !== 'base64' && <span className={metricClass}>{t('subscriptions.outputFormat')}: {deliveryFormat.toUpperCase()}</span>}
                </div>
              </div>
            )}
          </aside>
        </div>
      </section>

      <section className={panelClass}>
        <div className="mb-4 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <h3 className="text-sm font-medium uppercase tracking-[0.14em] text-slate-100">
              {viewMode === 'individual'
                ? t('subscriptions.individualTitle', { count: emails.length })
                : t('subscriptions.groupedTitle', { count: groups.length })}
            </h3>
            <p className={hintClass}>
              {viewMode === 'grouped' ? t('subscriptions.copyGroupLinksTitle') : t('traffic.sortHint')}
            </p>
          </div>
          {viewMode === 'grouped' && (
            <div className="flex min-w-0 flex-wrap gap-2">
              <ChoiceChips
                options={[
                  { value: 'count', label: t('subscriptions.count') },
                  { value: 'name', label: t('subscriptions.group') },
                ]}
                value={groupSortField}
                onChange={(value) => setGroupSortField(value)}
              />
              <ChoiceChips
                options={[
                  { value: 'asc', label: groupSortDirectionLabels.asc },
                  { value: 'desc', label: groupSortDirectionLabels.desc },
                ]}
                value={groupSortDir}
                onChange={(value) => setGroupSortDir(value)}
              />
            </div>
          )}
        </div>

        {emails.length === 0 ? (
          <p className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
            {t('subscriptions.noUsersFound')}
          </p>
        ) : viewMode === 'individual' ? (
          <div className="min-w-0">
            <div className="hidden min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 lg:block">
              <table className="w-full table-fixed border-collapse text-left text-xs">
                <thead className="bg-[#0a0e1a] text-[10px] uppercase tracking-wider text-slate-500">
                  <tr className="border-b border-cyan-500/20">
                    <th className="px-4 py-3">
                      <button type="button" className={headerButtonClass} onClick={() => applyIndividualSortFromHeader('email')}>
                        {t('clients.email')}{individualSortIndicator('email')}
                      </button>
                    </th>
                    <th className="w-32 px-4 py-3 text-right">
                      <button
                        type="button"
                        className={cn(headerButtonClass, 'justify-end')}
                        onClick={() => applyIndividualSortFromHeader('downloads')}
                      >
                        {t('subscriptions.downloads')}{individualSortIndicator('downloads')}
                      </button>
                    </th>
                    <th className="w-40 px-4 py-3 text-right">
                      <button
                        type="button"
                        className={cn(headerButtonClass, 'justify-end')}
                        onClick={() => applyIndividualSortFromHeader('last')}
                      >
                        {t('subscriptions.lastSeen')}{individualSortIndicator('last')}
                      </button>
                    </th>
                    <th className="px-4 py-3">{t('subscriptions.link')}</th>
                    <th className="w-28 px-4 py-3 text-right">{t('common.actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-200">
                  {sortedEmails.map((email) => {
                    const subscriptionUrl = buildSubscriptionUrl(email);
                    return (
                      <tr key={email} className="bg-[#0f1420] transition hover:bg-cyan-400/5">
                        <td className="min-w-0 px-4 py-3">
                          <div className="min-w-0">
                            <strong className="block truncate text-sm text-slate-100" title={email}>{email}</strong>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <span className={cn(metricClass, 'inline-flex rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2 py-1 text-cyan-200')}>
                            {stats[email]?.count || 0}
                          </span>
                        </td>
                        <td className={cn(metricClass, 'px-4 py-3 text-right text-slate-400')}>
                          {stats[email]?.last || '--'}
                        </td>
                        <td className="min-w-0 px-4 py-3">
                          <div className="min-w-0">
                            <input
                              type="text"
                              readOnly
                              value={subscriptionUrl}
                              className={cn(codeInputClass, 'truncate whitespace-nowrap')}
                            />
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            {renderIndividualActions(email)}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="grid min-w-0 grid-cols-1 gap-3 lg:hidden">
              {sortedEmails.map((email) => {
                const subscriptionUrl = buildSubscriptionUrl(email);
                return (
                  <article key={email} className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-4">
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <strong className="block truncate text-sm text-slate-100" title={email}>{email}</strong>
                        <div className="mt-3 grid min-w-0 grid-cols-2 gap-3">
                          <div className="min-w-0">
                            <span className={metaLabelClass}>{t('subscriptions.downloads')}</span>
                            <span className={cn(metaValueClass, metricClass)}>{stats[email]?.count || 0}</span>
                          </div>
                          <div className="min-w-0 text-right">
                            <span className={metaLabelClass}>{t('subscriptions.lastSeen')}</span>
                            <span className={cn(cardMetaValueClass, metricClass)}>{stats[email]?.last || '--'}</span>
                          </div>
                        </div>
                        <div className="mt-3 min-w-0">
                          <span className={metaLabelClass}>{t('subscriptions.link')}</span>
                          <div className="mt-2 min-w-0 rounded-lg border border-cyan-500/20 bg-[#0f1420] px-3 py-2">
                            <span className="block min-w-0 truncate font-mono text-xs text-slate-300" title={subscriptionUrl}>
                              {subscriptionUrl}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col gap-2">
                        {renderIndividualActions(email)}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="grid min-w-0 grid-cols-1 gap-6 md:grid-cols-3">
            {sortedGroups.map((group) => {
              const groupedUrl = buildSubscriptionUrl(group.identifier, true);
              return (
                <article
                  key={group.identifier}
                  className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0f1420] p-5 shadow-[0_18px_50px_rgba(0,0,0,0.22)]"
                >
                  <div className="mb-4 flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-cyan-200">
                        <UIIcon name="folder" size={12} />
                        <span className="whitespace-nowrap">{t('subscriptions.group')}</span>
                      </div>
                      <h4 className="mt-3 truncate text-base font-semibold text-slate-100" title={group.identifier}>
                        {group.identifier}
                      </h4>
                      <p className="mt-2 text-sm text-slate-400">
                        <span className={metricClass}>{t('subscriptions.clientCount', { count: group.count })}</span>
                        {group.emails.length > 0 && group.emails.length !== group.count && (
                          <span className={cn(metricClass, 'ml-2 text-slate-500')}>
                            {t('subscriptions.emailCount', { count: group.emails.length })}
                          </span>
                        )}
                      </p>
                    </div>
                    <span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2.5 py-1 font-mono text-xs tabular-nums text-cyan-200 whitespace-nowrap">
                      {group.count}
                    </span>
                  </div>

                  <div className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-3">
                    <span className={titleClass}>{t('subscriptions.link')}</span>
                    <div className="mt-2 min-w-0 rounded-lg border border-cyan-500/20 bg-[#0f1420] px-3 py-2">
                      <span className="block min-w-0 truncate font-mono text-xs text-slate-300" title={groupedUrl}>
                        {groupedUrl}
                      </span>
                    </div>
                  </div>

                  <div className="mt-4 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className={titleClass}>{t('clients.email')}</span>
                      <span className={cn(metricClass, 'text-[11px] text-slate-500')}>{group.emails.length}</span>
                    </div>
                    <div className="max-h-32 space-y-2 overflow-y-auto pr-1">
                      {group.emails.map((email) => (
                        <div key={email} className="min-w-0 rounded-lg border border-cyan-500/15 bg-[#0f1420] px-3 py-2">
                          <span className="block min-w-0 truncate font-mono text-xs text-slate-300" title={email}>
                            {email}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="mt-4 flex items-center justify-end gap-2">
                    {renderGroupActions(group)}
                  </div>
                </article>
              );
            })}

            {groups.length === 0 && (
              <div className="md:col-span-3">
                <p className="rounded-lg border border-cyan-500/20 bg-[#0a0e1a] px-4 py-8 text-center text-sm text-slate-500">
                  {t('subscriptions.noGroupsFound')}
                </p>
              </div>
            )}
          </div>
        )}
      </section>

      {showQr && qrUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 px-4 py-6"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowQr(false);
          }}
        >
          <div className="w-full max-w-md rounded-lg border border-cyan-500/20 bg-[#0f1420] shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
            <div className="flex items-center justify-between border-b border-cyan-500/20 px-5 py-4">
              <div className="min-w-0">
                <h4 className="flex items-center gap-2 text-sm font-medium uppercase tracking-[0.14em] text-slate-100">
                  <UIIcon name="subscriptions" size={15} />
                  {t('subscriptions.qrCodeTitle')}
                </h4>
                <p className="mt-1 text-xs text-slate-500">{t('subscriptions.qrCodeAlt')}</p>
              </div>
              <button
                type="button"
                className={iconButtonClass}
                aria-label={t('common.close', 'Close')}
                onClick={() => setShowQr(false)}
              >
                <UIIcon name="x" size={15} />
              </button>
            </div>
            <div className="space-y-4 px-5 py-5">
              <div className="flex justify-center rounded-lg border border-cyan-500/20 bg-white p-4">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=${encodeURIComponent(qrUrl)}`}
                  alt={t('subscriptions.qrCodeAlt')}
                  width={280}
                  height={280}
                  className="h-auto w-full max-w-[280px]"
                />
              </div>
              <div className="min-w-0">
                <label className={titleClass}>{t('subscriptions.link')}</label>
                <div className="mt-2 flex min-w-0 items-center gap-2">
                  <input type="text" readOnly value={qrUrl} className={cn(codeInputClass, 'truncate whitespace-nowrap')} />
                  <button type="button" className={secondaryButtonClass} onClick={() => copyToClipboard(qrUrl)}>
                    <UIIcon name="copy" size={15} />
                    <span className="whitespace-nowrap">{t('common.copy')}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
