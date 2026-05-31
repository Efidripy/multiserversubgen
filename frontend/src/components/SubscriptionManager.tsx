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
        auth: { username: getAuth().user, password: getAuth().password }
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
        auth: { username: getAuth().user, password: getAuth().password }
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
          count: emailList.length
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

  if (loading && emails.length === 0) {
    return <div className="text-center py-5" style={{ color: 'var(--text-secondary)' }}>{t('app.loading')}</div>;
  }

  const compareText = (a: string, b: string) =>
    a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });

  const filteredEmails = emailSearch.trim()
    ? emails.filter(e => e.toLowerCase().includes(emailSearch.trim().toLowerCase()))
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
    individualSortField === field ? (individualSortDir === 'asc' ? ' ▲' : ' ▼') : '';

  const toggleNodeSelection = (nodeName: string) => {
    setSelectedNodes((prev) =>
      prev.includes(nodeName) ? prev.filter((node) => node !== nodeName) : [...prev, nodeName]
    );
  };

  return (
    <div className="subscription-manager">
      <div className="panel-grid panel-grid--compact mb-3">
        <section className="panel-block panel-block--wide">
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title">{t('subscriptions.controlsTitle')}</h6>
              <p className="panel-block__hint">{t('subscriptions.controlsHint')}</p>
            </div>
            <div className="panel-inline-actions">
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                onClick={loadEmails}
                disabled={loading}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name={loading ? 'spinner' : 'refresh'} size={14} />
                  {t('subscriptions.refreshEmails')}
                </span>
              </button>
              <input
                type="text"
                className="form-control form-control-sm"
                placeholder={t('subscriptions.searchEmailsPlaceholder')}
                value={emailSearch}
                onChange={e => setEmailSearch(e.target.value)}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)', width: '180px' }}
              />
              <button
                className="btn btn-sm"
                style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                title={t('subscriptions.copyAllLinksTitle')}
                onClick={async () => {
                  const allLinks = filteredEmails.map(email => buildSubscriptionUrl(email));
                  await copyToClipboard(allLinks.join('\n'));
                }}
                disabled={filteredEmails.length === 0}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="copy" size={14} />
                  {t('subscriptions.copyAllLinks', { count: filteredEmails.length })}
                </span>
              </button>
              <button
                className="btn btn-sm"
                style={{
                  backgroundColor: viewMode === 'individual' ? 'var(--accent)' : 'var(--bg-tertiary)',
                  borderColor: 'var(--border-color)',
                  color: viewMode === 'individual' ? '#000f14' : 'var(--text-primary)'
                }}
                onClick={() => setViewMode('individual')}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="user" size={14} />
                  {t('subscriptions.individual')}
                </span>
              </button>
              <button
                className="btn btn-sm"
                style={{
                  backgroundColor: viewMode === 'grouped' ? 'var(--accent)' : 'var(--bg-tertiary)',
                  borderColor: 'var(--border-color)',
                  color: viewMode === 'grouped' ? '#000f14' : 'var(--text-primary)'
                }}
                onClick={() => setViewMode('grouped')}
              >
                <span className="d-inline-flex align-items-center gap-1">
                  <UIIcon name="folder" size={14} />
                  {t('subscriptions.grouped')}
                </span>
              </button>
            </div>
          </div>

          {error && (
            <div className="alert mb-2" style={{ backgroundColor: 'color-mix(in srgb, var(--danger) 14%, transparent)', borderColor: 'var(--danger)', color: 'var(--danger)' }}>
              {error}
            </div>
          )}
          {successMessage && (
            <div className="alert mb-2" style={{ backgroundColor: 'color-mix(in srgb, var(--success) 14%, transparent)', borderColor: 'var(--success)', color: 'var(--success)' }}>
              {successMessage}
            </div>
          )}

          <div className="row g-2 mb-2">
            <div className="col-12">
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>{t('subscriptions.nodeFilter')}</label>
              <div className="panel-inline-actions">
                {nodes.map((node) => (
                  <button
                    key={node.id}
                    className="btn btn-sm"
                    style={{
                      backgroundColor: selectedNodes.includes(node.name) ? 'var(--accent)' : 'var(--bg-tertiary)',
                      borderColor: 'var(--border-color)',
                      color: selectedNodes.includes(node.name) ? '#000f14' : 'var(--text-primary)'
                    }}
                    onClick={() => toggleNodeSelection(node.name)}
                  >
                    <span className="d-inline-flex align-items-center gap-1">
                      {selectedNodes.includes(node.name) && <UIIcon name="check" size={12} />}
                      {node.name}
                    </span>
                  </button>
                ))}
                {selectedNodes.length > 0 && (
                  <button
                    className="btn btn-sm"
                    style={{ backgroundColor: 'var(--warning)', borderColor: 'var(--warning)', color: 'var(--text-primary)' }}
                    onClick={() => setSelectedNodes([])}
                  >
                    <span className="d-inline-flex align-items-center gap-1">
                      <UIIcon name="x" size={12} />
                      {t('common.clear')}
                    </span>
                  </button>
                )}
              </div>
            </div>
          </div>

          {(filterProtocol || selectedNodes.length > 0 || deliveryTransport !== 'all' || deliveryFormat !== 'base64') && (
            <div className="alert mt-2 mb-0" style={{ backgroundColor: 'color-mix(in srgb, var(--info) 14%, transparent)', borderColor: 'var(--info)', color: 'var(--text-primary)' }}>
              <small>
                <strong>{t('subscriptions.activeFilters')}:</strong>
                {filterProtocol && ` ${t('subscriptions.protocolFilter')}: ${filterProtocol.toUpperCase()}`}
                {selectedNodes.length > 0 && ` | ${t('subscriptions.nodeFilters')}: ${selectedNodes.join(', ')}`}
                {deliveryTransport !== 'all' && ` | ${t('subscriptions.transportHint')}: ${deliveryTransport.toUpperCase()}`}
                {deliveryFormat !== 'base64' && ` | ${t('subscriptions.outputFormat')}: ${deliveryFormat.toUpperCase()}`}
              </small>
            </div>
          )}
        </section>

        <aside className="panel-block">
          <div className="panel-block__header">
            <div>
              <h6 className="panel-block__title">{t('subscriptions.deliveryProfile')}</h6>
              <p className="panel-block__hint">{t('subscriptions.deliveryHint')}</p>
            </div>
          </div>
          <div className="panel-block__stack">
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>{t('subscriptions.subscriptionProfile')}</label>
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
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>{t('subscriptions.transportHint')}</label>
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
            <div>
              <label className="form-label small" style={{ color: 'var(--text-secondary)' }}>{t('subscriptions.outputFormat')}</label>
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
        </aside>
      </div>

      <section className="panel-block">
        <div className="d-flex justify-content-between align-items-center mb-3 gap-2">
          <h6 className="mb-0" style={{ color: 'var(--text-primary)' }}>
            {viewMode === 'individual' ? t('subscriptions.individualTitle', { count: emails.length }) : t('subscriptions.groupedTitle', { count: groups.length })}
          </h6>
          {viewMode === 'grouped' ? (
            <div className="d-flex gap-2">
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
          ) : (
            <div className="small" style={{ color: 'var(--text-secondary)' }}>{t('traffic.sortHint')}</div>
          )}
        </div>

        {emails.length === 0 ? (
          <p className="text-center py-3 mb-0" style={{ color: 'var(--text-secondary)' }}>{t('subscriptions.noUsersFound')}</p>
        ) : viewMode === 'individual' ? (
          <div className="table-responsive table-shell">
            <table className="table table-hover small mb-0" style={{ color: 'var(--text-primary)' }}>
              <thead>
                <tr style={{ borderColor: 'var(--border-color)' }}>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyIndividualSortFromHeader('email')}>
                      {t('clients.email')}{individualSortIndicator('email')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyIndividualSortFromHeader('downloads')}>
                      {t('subscriptions.downloads')}{individualSortIndicator('downloads')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>
                    <button className="btn btn-link btn-sm p-0 text-decoration-none" style={{ color: 'var(--text-secondary)' }} onClick={() => applyIndividualSortFromHeader('last')}>
                      {t('subscriptions.lastSeen')}{individualSortIndicator('last')}
                    </button>
                  </th>
                  <th style={{ color: 'var(--text-secondary)' }}>{t('subscriptions.link')}</th>
                </tr>
              </thead>
              <tbody>
                {sortedEmails.map((email) => (
                  <tr key={email} style={{ borderColor: 'var(--border-color)' }}>
                    <td className="align-middle">
                      <strong style={{ color: 'var(--text-primary)' }}>{email}</strong>
                    </td>
                    <td className="align-middle">
                      <span className="badge" style={{ backgroundColor: 'var(--info)' }}>
                        {stats[email]?.count || 0}
                      </span>
                    </td>
                    <td className="align-middle">
                      <small style={{ color: 'var(--text-secondary)' }}>{stats[email]?.last || '--'}</small>
                    </td>
                    <td className="align-middle">
                      <div className="input-group input-group-sm">
                        <input
                          type="text"
                          id={`sub-${email}`}
                          className="form-control form-control-sm"
                          readOnly
                          value={buildSubscriptionUrl(email)}
                          style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                        />
                        <button
                          className="btn"
                          style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                          onClick={() => copyToClipboard(buildSubscriptionUrl(email))}
                        >
                          {t('common.copy')}
                        </button>
                        <button
                          className="btn"
                          style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                          title={t('subscriptions.showQrCode')}
                          onClick={() => { setQrUrl(buildSubscriptionUrl(email)); setShowQr(true); }}
                        >
                          ▦
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="row g-3">
            {sortedGroups.map((group, idx) => (
              <div className="col-md-6" key={idx}>
                <div className="panel-block h-100">
                  <div className="d-flex justify-content-between align-items-center mb-2">
                    <div>
                      <h6 className="mb-0" style={{ color: 'var(--accent)' }}>
                        <span className="d-inline-flex align-items-center gap-1">
                          <UIIcon name="folder" size={13} />
                          {group.identifier}
                        </span>
                      </h6>
                      <small style={{ color: 'var(--text-secondary)' }}>
                        {t('subscriptions.clientCount', { count: group.count })}
                        {group.emails && group.emails.length > 0 && group.emails.length !== group.count && (
                          <span style={{ color: 'var(--text-secondary)' }}> · {t('subscriptions.emailCount', { count: group.emails.length })}</span>
                        )}
                      </small>
                    </div>
                    <span className="badge" style={{ backgroundColor: 'var(--accent)' }}>{group.count}</span>
                  </div>

                  <div className="mb-2" style={{ maxHeight: '120px', overflowY: 'auto' }}>
                    {group.emails.map((email, i) => (
                      <div key={i} className="small" style={{ color: 'var(--text-secondary)' }}>
                        • {email}
                      </div>
                    ))}
                  </div>

                  <div className="input-group input-group-sm">
                    <input
                      type="text"
                      className="form-control form-control-sm"
                      readOnly
                      value={buildSubscriptionUrl(group.identifier, true)}
                      style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
                    />
                    <button
                      className="btn"
                      style={{ backgroundColor: 'var(--accent)', borderColor: 'var(--accent)', color: '#000f14' }}
                      onClick={() => copyToClipboard(buildSubscriptionUrl(group.identifier, true))}
                    >
                      {t('common.copy')}
                    </button>
                    <button
                      className="btn"
                      style={{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                      title={t('subscriptions.copyGroupLinksTitle')}
                      onClick={async () => {
                        const links = group.emails.map(e => buildSubscriptionUrl(e)).join('\n');
                        await copyToClipboard(links);
                      }}
                    >
                      {t('subscriptions.allLinks')}
                    </button>
                  </div>
                </div>
              </div>
            ))}
            {groups.length === 0 && (
              <div className="col-12">
                <p className="text-center py-3 mb-0" style={{ color: 'var(--text-secondary)' }}>
                  {t('subscriptions.noGroupsFound')}
                </p>
              </div>
            )}
          </div>
        )}
      </section>

      {/* QR Code Modal */}
      {showQr && qrUrl && (
        <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }} onClick={e => { if (e.target === e.currentTarget) setShowQr(false); }}>
          <div className="modal-dialog modal-dialog-centered">
            <div className="modal-content" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
              <div className="modal-header" style={{ borderColor: 'var(--border-color)' }}>
                <h6 className="modal-title" style={{ color: 'var(--text-primary)' }}>▦ {t('subscriptions.qrCodeTitle')}</h6>
                <button type="button" className="btn-close btn-close-white" onClick={() => setShowQr(false)} />
              </div>
              <div className="modal-body d-flex flex-column align-items-center gap-3">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=${encodeURIComponent(qrUrl)}`}
                  alt={t('subscriptions.qrCodeAlt')}
                  width={280} height={280}
                  style={{ border: '2px solid var(--border-color)', borderRadius: '8px', backgroundColor: '#fff' }}
                />
                <div className="d-flex gap-2 w-100">
                  <input readOnly className="form-control form-control-sm" value={qrUrl}
                    style={{ fontFamily: 'monospace', fontSize: '11px', backgroundColor: 'var(--bg-primary)', color: 'var(--text-secondary)', borderColor: 'var(--border-color)' }} />
                  <button className="btn btn-sm" style={{ backgroundColor: 'var(--accent)', color: '#000f14', whiteSpace: 'nowrap' }}
                    onClick={() => copyToClipboard(qrUrl)}>{t('common.copy')}</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
