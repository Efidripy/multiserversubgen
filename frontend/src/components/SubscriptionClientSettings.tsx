import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { useToast } from './Toast';
import { ChoiceChips } from './ChoiceChips';
import { SelectMenu } from './SelectMenu';
import { UIIcon } from './UIIcon';
import {
  cn,
  panelClass,
  titleClass,
  hintClass,
  inputClass,
  codeInputClass,
  primaryButtonClass,
  secondaryButtonClass,
  iconButtonClass,
  metaLabelClass,
} from './SubscriptionManager';

export interface SubscriptionProfile {
  title: string;
  support_url: string;
  web_page_url: string;
  announce: string;
  update_interval_hours: number | null;
}

export interface ClientCustomHeader {
  key: string;
  value: string;
}

export interface SubscriptionClientRule {
  id: string;
  name: string;
  kind: 'happ' | 'incy' | 'mihomo' | 'generic';
  builtin: boolean;
  enabled: boolean;
  user_agent_regex: string;
  format: string;
  settings: Record<string, any>;
  headers: ClientCustomHeader[];
}

export interface SubscriptionClientSettingsModel {
  profile: SubscriptionProfile;
  clients: SubscriptionClientRule[];
}

export interface SchemaField {
  key: string;
  header: string | null;
  type: 'text' | 'url' | 'bool' | 'tristate' | 'enum' | 'lines';
  group: string;
  options?: string[];
}

export type ClientSchemaMap = Record<string, SchemaField[]>;

export interface SubscriptionClientSettingsApiResponse {
  settings: SubscriptionClientSettingsModel;
  schema: ClientSchemaMap;
  formats: string[];
}

export interface SubscriptionClientTestResponse {
  matched: boolean;
  client_id: string | null;
  name: string | null;
  format: string;
  headers: Record<string, string>;
}

const emptyProfile: SubscriptionProfile = {
  title: '',
  support_url: '',
  web_page_url: '',
  announce: '',
  update_interval_hours: null,
};

const defaultFormats = ['base64', 'mihomo', 'clash', 'singbox'];

export const SubscriptionClientSettings: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState<'profile' | 'clients'>('profile');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const [settings, setSettings] = useState<SubscriptionClientSettingsModel>({
    profile: emptyProfile,
    clients: [],
  });
  const [savedBaseline, setSavedBaseline] = useState<string>('');
  const [schema, setSchema] = useState<ClientSchemaMap>({});
  const [formats, setFormats] = useState<string[]>(defaultFormats);

  const [expandedClients, setExpandedClients] = useState<Record<string, boolean>>({});

  const [testUa, setTestUa] = useState('');
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<SubscriptionClientTestResponse | null>(null);

  const hasChanges = useMemo(() => {
    return JSON.stringify(settings) !== savedBaseline;
  }, [settings, savedBaseline]);

  const loadSettings = async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/v1/subscription-client-settings', { signal });
      const data: SubscriptionClientSettingsApiResponse = res.data;
      const loadedSettings: SubscriptionClientSettingsModel = {
        profile: {
          title: data.settings?.profile?.title ?? '',
          support_url: data.settings?.profile?.support_url ?? '',
          web_page_url: data.settings?.profile?.web_page_url ?? '',
          announce: data.settings?.profile?.announce ?? '',
          update_interval_hours: data.settings?.profile?.update_interval_hours ?? null,
        },
        clients: (data.settings?.clients ?? []).map((client) => ({
          id: client.id,
          name: client.name || client.id,
          kind: client.kind || 'generic',
          builtin: Boolean(client.builtin),
          enabled: Boolean(client.enabled),
          user_agent_regex: client.user_agent_regex || '',
          format: client.format || 'base64',
          settings: client.settings || {},
          headers: Array.isArray(client.headers)
            ? client.headers.map((h) => ({ key: h.key || '', value: h.value || '' }))
            : [],
        })),
      };

      setSettings(loadedSettings);
      setSavedBaseline(JSON.stringify(loadedSettings));
      if (data.schema) setSchema(data.schema);
      if (Array.isArray(data.formats) && data.formats.length > 0) {
        setFormats(data.formats);
      }
    } catch (err: any) {
      if (signal?.aborted) return;
      const message = err.response?.data?.detail || err.message || t('subscriptionClients.loadFailed');
      setError(typeof message === 'string' ? message : JSON.stringify(message));
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void loadSettings(controller.signal);
    return () => {
      controller.abort();
    };
  }, []);

  const handleSave = async () => {
    if (!hasChanges || saving) return;
    setSaving(true);
    setError('');
    setSuccessMessage('');
    try {
      const res = await api.put('/v1/subscription-client-settings', settings);
      const data = res.data;
      if (data?.settings) {
        const updated: SubscriptionClientSettingsModel = {
          profile: {
            title: data.settings?.profile?.title ?? '',
            support_url: data.settings?.profile?.support_url ?? '',
            web_page_url: data.settings?.profile?.web_page_url ?? '',
            announce: data.settings?.profile?.announce ?? '',
            update_interval_hours: data.settings?.profile?.update_interval_hours ?? null,
          },
          clients: (data.settings?.clients ?? []).map((client: SubscriptionClientRule) => ({
            id: client.id,
            name: client.name || client.id,
            kind: client.kind || 'generic',
            builtin: Boolean(client.builtin),
            enabled: Boolean(client.enabled),
            user_agent_regex: client.user_agent_regex || '',
            format: client.format || 'base64',
            settings: client.settings || {},
            headers: Array.isArray(client.headers)
              ? client.headers.map((h) => ({ key: h.key || '', value: h.value || '' }))
              : [],
          })),
        };
        setSettings(updated);
        setSavedBaseline(JSON.stringify(updated));
      } else {
        setSavedBaseline(JSON.stringify(settings));
      }
      if (data?.schema) setSchema(data.schema);
      if (Array.isArray(data?.formats)) setFormats(data.formats);

      setSuccessMessage(t('subscriptionClients.saveSuccess'));
      toast(t('subscriptionClients.saveSuccess'), 'success');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      let formattedDetail = '';
      if (typeof detail === 'string') {
        formattedDetail = detail;
      } else if (Array.isArray(detail)) {
        formattedDetail = detail
          .map((item: any) => (typeof item === 'string' ? item : item.msg || JSON.stringify(item)))
          .join('; ');
      } else if (detail && typeof detail === 'object') {
        formattedDetail = JSON.stringify(detail);
      } else {
        formattedDetail = err.message || t('subscriptionClients.saveFailed');
      }
      setError(formattedDetail);
      toast(formattedDetail, 'error');
    } finally {
      setSaving(false);
    }
  };

  const updateProfile = <K extends keyof SubscriptionProfile>(field: K, value: SubscriptionProfile[K]) => {
    setSettings((prev) => ({
      ...prev,
      profile: {
        ...prev.profile,
        [field]: value,
      },
    }));
  };

  const updateClient = (index: number, patch: Partial<SubscriptionClientRule>) => {
    setSettings((prev) => {
      const nextClients = [...prev.clients];
      nextClients[index] = {
        ...nextClients[index],
        ...patch,
      };
      return { ...prev, clients: nextClients };
    });
  };

  const updateClientSetting = (index: number, settingKey: string, value: any) => {
    setSettings((prev) => {
      const nextClients = [...prev.clients];
      const target = nextClients[index];
      nextClients[index] = {
        ...target,
        settings: {
          ...target.settings,
          [settingKey]: value,
        },
      };
      return { ...prev, clients: nextClients };
    });
  };

  const handleMoveUp = (index: number) => {
    if (index <= 0) return;
    setSettings((prev) => {
      const nextClients = [...prev.clients];
      const temp = nextClients[index - 1];
      nextClients[index - 1] = nextClients[index];
      nextClients[index] = temp;
      return { ...prev, clients: nextClients };
    });
  };

  const handleMoveDown = (index: number) => {
    if (index >= settings.clients.length - 1) return;
    setSettings((prev) => {
      const nextClients = [...prev.clients];
      const temp = nextClients[index + 1];
      nextClients[index + 1] = nextClients[index];
      nextClients[index] = temp;
      return { ...prev, clients: nextClients };
    });
  };

  const handleAddClient = () => {
    const randomSuffix = Math.random().toString(36).replace(/[^a-z0-9]/g, '').slice(0, 8);
    const newRule: SubscriptionClientRule = {
      id: `custom-${randomSuffix}`,
      name: `${t('subscriptionClients.clients.custom')} ${settings.clients.length + 1}`,
      kind: 'generic',
      builtin: false,
      enabled: false,
      user_agent_regex: '',
      format: 'base64',
      settings: {},
      headers: [],
    };
    setSettings((prev) => ({
      ...prev,
      clients: [...prev.clients, newRule],
    }));
    setExpandedClients((prev) => ({ ...prev, [newRule.id]: true }));
  };

  const handleDeleteClient = (index: number) => {
    setSettings((prev) => {
      const nextClients = prev.clients.filter((_, i) => i !== index);
      return { ...prev, clients: nextClients };
    });
  };

  const toggleExpanded = (id: string) => {
    setExpandedClients((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const addClientHeader = (clientIndex: number) => {
    setSettings((prev) => {
      const nextClients = [...prev.clients];
      const target = nextClients[clientIndex];
      nextClients[clientIndex] = {
        ...target,
        headers: [...target.headers, { key: '', value: '' }],
      };
      return { ...prev, clients: nextClients };
    });
  };

  const updateClientHeader = (clientIndex: number, headerIndex: number, key: string, value: string) => {
    setSettings((prev) => {
      const nextClients = [...prev.clients];
      const target = nextClients[clientIndex];
      const nextHeaders = [...target.headers];
      nextHeaders[headerIndex] = { key, value };
      nextClients[clientIndex] = {
        ...target,
        headers: nextHeaders,
      };
      return { ...prev, clients: nextClients };
    });
  };

  const deleteClientHeader = (clientIndex: number, headerIndex: number) => {
    setSettings((prev) => {
      const nextClients = [...prev.clients];
      const target = nextClients[clientIndex];
      nextClients[clientIndex] = {
        ...target,
        headers: target.headers.filter((_, i) => i !== headerIndex),
      };
      return { ...prev, clients: nextClients };
    });
  };

  const runTest = async () => {
    setTestLoading(true);
    setTestResult(null);
    try {
      const res = await api.post('/v1/subscription-client-settings/test', {
        user_agent: testUa,
      });
      setTestResult(res.data);
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message || t('subscriptionClients.test.failed');
      toast(typeof detail === 'string' ? detail : JSON.stringify(detail), 'error');
    } finally {
      setTestLoading(false);
    }
  };

  if (loading) {
    return (
      <section className={panelClass}>
        <div className="flex min-w-0 items-center justify-center gap-3 py-16 text-slate-400">
          <UIIcon name="spinner" size={20} />
          <span className="text-sm">{t('common.loading')}</span>
        </div>
      </section>
    );
  }

  return (
    <div className="min-w-0 space-y-4">
      <section className={panelClass}>
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h3 className="text-sm font-medium uppercase tracking-[0.14em] text-cyan-300">
              {t('subscriptionClients.title')}
            </h3>
            <div className="mt-2 min-w-0">
              <ChoiceChips
                options={[
                  { value: 'profile', label: t('subscriptionClients.tabs.profile') },
                  { value: 'clients', label: t('subscriptionClients.tabs.clients') },
                ]}
                value={activeTab}
                onChange={(val) => setActiveTab(val as 'profile' | 'clients')}
              />
            </div>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button
              type="button"
              className={primaryButtonClass}
              disabled={saving || !hasChanges}
              onClick={() => void handleSave()}
            >
              <UIIcon name={saving ? 'spinner' : 'check'} size={15} />
              <span className="whitespace-nowrap">
                {saving ? t('subscriptionClients.saving') : t('subscriptionClients.save')}
              </span>
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </div>
        )}
        {successMessage && (
          <div className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {successMessage}
          </div>
        )}
      </section>

      {activeTab === 'profile' && (
        <section className={panelClass}>
          <div className="space-y-4">
            <div className="min-w-0">
              <label className={titleClass}>{t('subscriptionClients.profile.title')}</label>
              <input
                type="text"
                className={cn(inputClass, 'mt-1')}
                value={settings.profile.title}
                onChange={(e) => updateProfile('title', e.target.value)}
                placeholder={t('subscriptionClients.profile.title')}
              />
            </div>

            <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
              <div className="min-w-0">
                <label className={titleClass}>{t('subscriptionClients.profile.supportUrl')}</label>
                <input
                  type="url"
                  className={cn(inputClass, 'mt-1')}
                  value={settings.profile.support_url}
                  onChange={(e) => updateProfile('support_url', e.target.value)}
                  placeholder={t('subscriptionClients.profile.supportUrl')}
                />
              </div>

              <div className="min-w-0">
                <label className={titleClass}>{t('subscriptionClients.profile.webPageUrl')}</label>
                <input
                  type="url"
                  className={cn(inputClass, 'mt-1')}
                  value={settings.profile.web_page_url}
                  onChange={(e) => updateProfile('web_page_url', e.target.value)}
                  placeholder={t('subscriptionClients.profile.webPageUrl')}
                />
              </div>
            </div>

            <div className="min-w-0">
              <label className={titleClass}>{t('subscriptionClients.profile.announce')}</label>
              <textarea
                rows={3}
                className={cn(inputClass, 'mt-1')}
                value={settings.profile.announce}
                onChange={(e) => updateProfile('announce', e.target.value)}
                placeholder={t('subscriptionClients.profile.announce')}
              />
            </div>

            <div className="min-w-0">
              <label className={titleClass}>{t('subscriptionClients.profile.updateIntervalHours')}</label>
              <input
                type="number"
                min={0}
                max={8760}
                className={cn(inputClass, 'mt-1')}
                value={settings.profile.update_interval_hours ?? ''}
                onChange={(e) => {
                  const val = e.target.value.trim();
                  updateProfile('update_interval_hours', val === '' ? null : Number(val));
                }}
                placeholder={t('subscriptionClients.profile.updateIntervalHours')}
              />
              <p className={hintClass}>{t('subscriptionClients.profile.updateIntervalHoursHint')}</p>
            </div>
          </div>
        </section>
      )}

      {activeTab === 'clients' && (
        <section className={panelClass}>
          <div className="mb-4 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className={hintClass}>{t('subscriptionClients.clients.firstMatchWins')}</p>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={handleAddClient}
            >
              <UIIcon name="plus" size={15} />
              <span className="whitespace-nowrap">{t('subscriptionClients.clients.addClient')}</span>
            </button>
          </div>

          <div className="space-y-4">
            {settings.clients.map((client, index) => {
              const isExpanded = Boolean(expandedClients[client.id]);
              const clientSchema = schema[client.kind] || [];

              // Group schema fields
              const schemaGroups: Array<[string, SchemaField[]]> = [];
              const groupMap = new Map<string, SchemaField[]>();
              for (const f of clientSchema) {
                const grp = f.group || 'default';
                const list = groupMap.get(grp) || [];
                list.push(f);
                groupMap.set(grp, list);
              }
              for (const entry of groupMap.entries()) {
                schemaGroups.push(entry);
              }

              return (
                <article
                  key={client.id}
                  className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-3 sm:p-4 shadow-sm"
                >
                  <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          className={cn(iconButtonClass, 'h-8 w-8')}
                          disabled={index === 0}
                          aria-label={t('subscriptionClients.clients.moveUp')}
                          title={t('subscriptionClients.clients.moveUp')}
                          onClick={() => handleMoveUp(index)}
                        >
                          <span className="text-xs">▲</span>
                        </button>
                        <button
                          type="button"
                          className={cn(iconButtonClass, 'h-8 w-8')}
                          disabled={index === settings.clients.length - 1}
                          aria-label={t('subscriptionClients.clients.moveDown')}
                          title={t('subscriptionClients.clients.moveDown')}
                          onClick={() => handleMoveDown(index)}
                        >
                          <span className="text-xs">▼</span>
                        </button>
                      </div>

                      <button
                        type="button"
                        role="switch"
                        aria-checked={client.enabled}
                        aria-label={t('subscriptionClients.clients.enabled')}
                        title={t('subscriptionClients.clients.enabled')}
                        onClick={() => updateClient(index, { enabled: !client.enabled })}
                        className={cn(
                          'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-cyan-400',
                          client.enabled ? 'bg-cyan-400' : 'bg-slate-700',
                        )}
                      >
                        <span
                          aria-hidden="true"
                          className={cn(
                            'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-[#0a0e1a] shadow ring-0 transition duration-200 ease-in-out',
                            client.enabled ? 'translate-x-5' : 'translate-x-0',
                          )}
                        />
                      </button>

                      {client.builtin ? (
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-100">{client.name}</span>
                          <span className="rounded border border-cyan-400/20 bg-cyan-400/10 px-2 py-0.5 font-mono text-[10px] text-cyan-200 uppercase">
                            {t('subscriptionClients.clients.builtin')}
                          </span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            className={cn(inputClass, 'h-8 w-40 text-xs')}
                            value={client.name}
                            aria-label={t('subscriptionClients.clients.ruleName')}
                            placeholder={t('subscriptionClients.clients.ruleName')}
                            onChange={(e) => updateClient(index, { name: e.target.value })}
                          />
                          <span className="rounded border border-slate-700 bg-slate-800/60 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                            {client.id}
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <div className="w-32">
                        <SelectMenu
                          ariaLabel={t('subscriptionClients.clients.format')}
                          value={client.format}
                          options={formats.map((f) => ({ value: f, label: f }))}
                          onChange={(val) => updateClient(index, { format: String(val) })}
                        />
                      </div>

                      <button
                        type="button"
                        className={secondaryButtonClass}
                        onClick={() => toggleExpanded(client.id)}
                      >
                        <span className="whitespace-nowrap">
                          {isExpanded
                            ? t('subscriptionClients.clients.collapseSettings')
                            : t('subscriptionClients.clients.expandSettings')}
                        </span>
                      </button>

                      {!client.builtin && (
                        <button
                          type="button"
                          className={cn(iconButtonClass, 'text-rose-400 hover:text-rose-300')}
                          aria-label={t('subscriptionClients.clients.deleteClient')}
                          title={t('subscriptionClients.clients.deleteClient')}
                          onClick={() => handleDeleteClient(index)}
                        >
                          <UIIcon name="trash" size={15} />
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="mt-3 min-w-0">
                    <label className={titleClass}>{t('subscriptionClients.clients.userAgentRegex')}</label>
                    <input
                      type="text"
                      className={cn(codeInputClass, 'mt-1')}
                      value={client.user_agent_regex}
                      aria-label={t('subscriptionClients.clients.userAgentRegex')}
                      placeholder={t('subscriptionClients.clients.userAgentRegex')}
                      onChange={(e) => updateClient(index, { user_agent_regex: e.target.value })}
                    />
                  </div>

                  {isExpanded && (
                    <div className="mt-4 space-y-4 border-t border-cyan-500/20 pt-4">
                      {schemaGroups.map(([groupKey, fields]) => (
                        <div key={groupKey} className="min-w-0">
                          <h4 className={cn(titleClass, 'text-cyan-300')}>
                            {t(`subscriptionClients.groups.${groupKey}`)}
                          </h4>
                          <div className="mt-2 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                            {fields.map((field) => {
                              const fieldLabel = t(`subscriptionClients.fields.${client.kind}.${field.key}`);
                              const currentValue = client.settings?.[field.key];

                              return (
                                <div key={field.key} className="min-w-0">
                                  <label className={cn(titleClass, 'text-[11px]')}>{fieldLabel}</label>
                                  <div className="mt-1 min-w-0">
                                    {(field.type === 'text' || field.type === 'url') && (
                                      <input
                                        type={field.type === 'url' ? 'url' : 'text'}
                                        className={inputClass}
                                        value={currentValue ?? ''}
                                        aria-label={fieldLabel}
                                        placeholder={fieldLabel}
                                        onChange={(e) => updateClientSetting(index, field.key, e.target.value)}
                                      />
                                    )}

                                    {field.type === 'lines' && (
                                      <textarea
                                        rows={3}
                                        className={codeInputClass}
                                        value={currentValue ?? ''}
                                        aria-label={fieldLabel}
                                        placeholder={fieldLabel}
                                        onChange={(e) => updateClientSetting(index, field.key, e.target.value)}
                                      />
                                    )}

                                    {field.type === 'bool' && (
                                      <div className="flex items-center pt-1">
                                        <button
                                          type="button"
                                          role="switch"
                                          aria-checked={Boolean(currentValue)}
                                          aria-label={fieldLabel}
                                          title={fieldLabel}
                                          onClick={() => updateClientSetting(index, field.key, !currentValue)}
                                          className={cn(
                                            'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-cyan-400',
                                            currentValue ? 'bg-cyan-400' : 'bg-slate-700',
                                          )}
                                        >
                                          <span
                                            aria-hidden="true"
                                            className={cn(
                                              'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-[#0a0e1a] shadow ring-0 transition duration-200 ease-in-out',
                                              currentValue ? 'translate-x-5' : 'translate-x-0',
                                            )}
                                          />
                                        </button>
                                      </div>
                                    )}

                                    {(field.type === 'tristate' || field.type === 'enum') && (
                                      <SelectMenu
                                        ariaLabel={fieldLabel}
                                        value={currentValue ?? ''}
                                        options={[
                                          { value: '', label: t('subscriptionClients.notSet') },
                                          ...(field.options && field.options.length > 0
                                            ? field.options.map((opt) => ({
                                                value: opt,
                                                label: t(`subscriptionClients.options.${opt}`),
                                              }))
                                            : field.type === 'tristate'
                                              ? [
                                                  { value: 'on', label: t('subscriptionClients.options.on') },
                                                  { value: 'off', label: t('subscriptionClients.options.off') },
                                                ]
                                              : []),
                                        ]}
                                        onChange={(val) => updateClientSetting(index, field.key, String(val))}
                                      />
                                    )}
                                  </div>
                                  {field.header && (
                                    <span
                                      className="mt-1 block truncate font-mono text-[10px] text-slate-500"
                                      title={field.header}
                                    >
                                      {field.header}
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))}

                      {/* Custom headers editor */}
                      <div className="min-w-0 border-t border-cyan-500/10 pt-3">
                        <div className="flex min-w-0 items-center justify-between gap-2">
                          <h4 className={cn(titleClass, 'text-cyan-300')}>
                            {t('subscriptionClients.clients.customHeaders')}
                          </h4>
                          <button
                            type="button"
                            className={cn(secondaryButtonClass, 'h-8 px-3 text-xs')}
                            onClick={() => addClientHeader(index)}
                          >
                            <UIIcon name="plus" size={13} />
                            <span className="whitespace-nowrap">{t('subscriptionClients.clients.addHeader')}</span>
                          </button>
                        </div>

                        {client.headers.length > 0 && (
                          <div className="mt-2 space-y-2">
                            {client.headers.map((header, hIdx) => (
                              <div
                                key={hIdx}
                                className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center"
                              >
                                <input
                                  type="text"
                                  className={cn(codeInputClass, 'sm:w-1/3')}
                                  value={header.key}
                                  aria-label={t('subscriptionClients.clients.headerKey')}
                                  placeholder={t('subscriptionClients.clients.headerKey')}
                                  onChange={(e) => updateClientHeader(index, hIdx, e.target.value, header.value)}
                                />
                                <input
                                  type="text"
                                  className={cn(codeInputClass, 'flex-1')}
                                  value={header.value}
                                  aria-label={t('subscriptionClients.clients.headerValue')}
                                  placeholder={t('subscriptionClients.clients.headerValue')}
                                  onChange={(e) => updateClientHeader(index, hIdx, header.key, e.target.value)}
                                />
                                <button
                                  type="button"
                                  className={cn(iconButtonClass, 'h-9 w-9 text-rose-400 hover:text-rose-300')}
                                  aria-label={t('subscriptionClients.clients.deleteHeader')}
                                  title={t('subscriptionClients.clients.deleteHeader')}
                                  onClick={() => deleteClientHeader(index, hIdx)}
                                >
                                  <UIIcon name="trash" size={14} />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )}

      {/* Test User-Agent block */}
      <section className={panelClass}>
        <h4 className={titleClass}>{t('subscriptionClients.test.title')}</h4>
        <p className={hintClass}>{t('subscriptionClients.test.hint')}</p>
        <div className="mt-3 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
          <input
            type="text"
            className={cn(codeInputClass, 'flex-1')}
            placeholder={t('subscriptionClients.test.userAgentPlaceholder')}
            aria-label={t('subscriptionClients.test.title')}
            value={testUa}
            onChange={(e) => setTestUa(e.target.value)}
          />
          <button
            type="button"
            className={primaryButtonClass}
            disabled={testLoading}
            onClick={() => void runTest()}
          >
            <UIIcon name={testLoading ? 'spinner' : 'check'} size={15} />
            <span className="whitespace-nowrap">
              {testLoading ? t('subscriptionClients.test.testing') : t('subscriptionClients.test.testButton')}
            </span>
          </button>
        </div>

        {testResult && (
          <div className="mt-3 min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-3 text-xs">
            <h5 className={titleClass}>{t('subscriptionClients.test.resultTitle')}</h5>
            <div className="mt-2 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 text-slate-300">
              <div className="min-w-0">
                <span className={metaLabelClass}>{t('subscriptionClients.test.matchedRule')}: </span>
                <span className="font-semibold text-cyan-200">
                  {testResult.matched
                    ? testResult.name || testResult.client_id || t('subscriptionClients.test.matchedRule')
                    : t('subscriptionClients.test.noMatch')}
                </span>
              </div>
              <div className="min-w-0">
                <span className={metaLabelClass}>{t('subscriptionClients.test.format')}: </span>
                <span className="font-mono text-cyan-200">{testResult.format}</span>
              </div>
            </div>

            <div className="mt-3 min-w-0">
              <span className={metaLabelClass}>{t('subscriptionClients.test.headers')}:</span>
              {Object.keys(testResult.headers || {}).length === 0 ? (
                <p className="mt-1 italic text-slate-500">{t('subscriptionClients.test.noHeaders')}</p>
              ) : (
                <div className="mt-2 space-y-1 font-mono text-xs text-slate-200">
                  {Object.entries(testResult.headers).map(([k, v]) => (
                    <div key={k} className="flex min-w-0 flex-wrap gap-1">
                      <span className="text-cyan-400">{k}:</span>
                      <span className="break-all text-slate-300">{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
};
