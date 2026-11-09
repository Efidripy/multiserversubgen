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
} from './SubscriptionManager';
import {
  SubscriptionSettingsSections,
  SectionSchemaMap,
} from './SubscriptionSettingsSections';
import { HappRoutingEditor } from './HappRoutingEditor';
import { SubscriptionDevicesPanel } from './SubscriptionDevicesPanel';

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
  [sectionKey: string]: any;
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
  section_schema?: SectionSchemaMap;
  formats: string[];
}

export type { SubscriptionClientTestResponse } from './SubscriptionUaTest';

const emptyProfile: SubscriptionProfile = {
  title: '',
  support_url: '',
  web_page_url: '',
  announce: '',
  update_interval_hours: null,
};

const defaultFormats = ['base64', 'mihomo', 'clash', 'singbox'];

export const CONTENT_TOKENS = [
  '{{EMAIL}}',
  '{{USERNAME}}',
  '{{SUB_ID}}',
  '{{NODE}}',
  '{{PROTOCOL}}',
  '{{INBOUND}}',
  '{{TRAFFIC_USED}}',
  '{{TRAFFIC_LEFT}}',
  '{{TRAFFIC_TOTAL}}',
  '{{DAYS_LEFT}}',
  '{{EXPIRE_DATE}}',
  '{{STATUS}}',
  '{{STATUS_EMOJI}}',
];

export const normalizeSettings = (raw?: any): SubscriptionClientSettingsModel => {
  const settings = raw || {};
  const normalized: SubscriptionClientSettingsModel = {
    ...settings,
    profile: { ...emptyProfile, ...settings.profile },
    clients: (settings.clients ?? []).map((client: any) => ({
      ...client,
      name: client.name || client.id,
      kind: client.kind || 'generic',
      builtin: Boolean(client.builtin),
      enabled: Boolean(client.enabled),
      user_agent_regex: client.user_agent_regex || '',
      format: client.format || 'base64',
      settings: client.settings || {},
      headers: (client.headers ?? []).map((h: any) => ({ key: h.key || '', value: h.value || '' })),
    })),
  };
  return normalized;
};

export const SubscriptionClientSettings: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState<string>('profile');
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
  const [sectionSchema, setSectionSchema] = useState<SectionSchemaMap>({});
  const [formats, setFormats] = useState<string[]>(defaultFormats);

  const [selectedClientId, setSelectedClientId] = useState<string>('');
  const [openHappRouting, setOpenHappRouting] = useState<Record<string, boolean>>({});
  const [invalidSections, setInvalidSections] = useState<Record<string, boolean>>({});

  const hasInvalidJson = useMemo(() => {
    return Object.values(invalidSections).some(Boolean);
  }, [invalidSections]);

  const hasChanges = useMemo(() => {
    return JSON.stringify(settings) !== savedBaseline;
  }, [settings, savedBaseline]);

  const loadSettings = async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/v1/subscription-client-settings', { signal });
      const data: SubscriptionClientSettingsApiResponse = res.data;
      const loadedSettings = normalizeSettings(data.settings);

      setSettings(loadedSettings);
      setSavedBaseline(JSON.stringify(loadedSettings));
      setSelectedClientId((prevId) => {
        if (prevId && loadedSettings.clients.some((c) => c.id === prevId)) {
          return prevId;
        }
        return loadedSettings.clients[0]?.id || '';
      });
      if (data.schema) setSchema(data.schema);
      if (data.section_schema) setSectionSchema(data.section_schema);
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
    if (!hasChanges || saving || hasInvalidJson) return;
    setSaving(true);
    setError('');
    setSuccessMessage('');
    try {
      const res = await api.put('/v1/subscription-client-settings', settings);
      const data = res.data;
      if (data?.settings) {
        const updated = normalizeSettings(data.settings);
        setSettings(updated);
        setSavedBaseline(JSON.stringify(updated));
        setSelectedClientId((prevId) => {
          if (prevId && updated.clients.some((c) => c.id === prevId)) {
            return prevId;
          }
          return updated.clients[0]?.id || '';
        });
      } else {
        setSavedBaseline(JSON.stringify(settings));
      }
      if (data?.schema) setSchema(data.schema);
      if (data?.section_schema) setSectionSchema(data.section_schema);
      if (Array.isArray(data?.formats)) setFormats(data.formats);

      setSuccessMessage(t('subscriptionClients.saveSuccess'));
      toast(t('subscriptionClients.saveSuccess'), 'success');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      let formattedDetail = '';
      if (detail === 'headers') {
        formattedDetail = t('subscriptionClients.errorHeaders');
      } else if (typeof detail === 'string') {
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

  const updateSectionField = (sectionKey: string, fieldKey: string, value: any) => {
    setSettings((prev) => ({
      ...prev,
      [sectionKey]: {
        ...(prev[sectionKey] || {}),
        [fieldKey]: value,
      },
    }));
  };

  const handleSectionValidityChange = (sectionKey: string, isValid: boolean) => {
    setInvalidSections((prev) => {
      if (isValid && prev[sectionKey]) {
        const next = { ...prev };
        delete next[sectionKey];
        return next;
      }
      if (!isValid && !prev[sectionKey]) {
        return { ...prev, [sectionKey]: true };
      }
      return prev;
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
    setSelectedClientId(newRule.id);
  };

  const handleDeleteClient = (index: number) => {
    const nextClients = settings.clients.filter((_, i) => i !== index);
    if (nextClients.length === 0) {
      setSelectedClientId('');
    } else {
      const nextIndex = Math.min(index, nextClients.length - 1);
      setSelectedClientId(nextClients[nextIndex].id);
    }
    setSettings((prev) => ({
      ...prev,
      clients: prev.clients.filter((_, i) => i !== index),
    }));
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

  const selectedIndex = useMemo(() => {
    if (settings.clients.length === 0) return -1;
    const idx = settings.clients.findIndex((c) => c.id === selectedClientId);
    return idx >= 0 ? idx : 0;
  }, [settings.clients, selectedClientId]);

  const selectedClient = selectedIndex >= 0 ? settings.clients[selectedIndex] : null;

  const clientTabOptions = useMemo(() => {
    return settings.clients.map((client) => {
      const baseName = client.name || client.id;
      const label = client.enabled
        ? baseName
        : `${baseName} (${t('subscriptionClients.clients.disabled')})`;
      return {
        value: client.id,
        label,
        title: baseName,
      };
    });
  }, [settings.clients, t]);

  const tabOptions = useMemo(() => {
    const tabs: Array<{ value: string; label: string }> = [
      { value: 'profile', label: t('subscriptionClients.tabs.profile') },
    ];
    if ('content' in sectionSchema) {
      tabs.push({
        value: 'content',
        label: t(
          'subscriptionClients.tabs.content',
          t('subscriptionClients.sections.content.title', 'content'),
        ),
      });
    }
    tabs.push({ value: 'clients', label: t('subscriptionClients.tabs.clients') });

    for (const secKey of Object.keys(sectionSchema)) {
      if (secKey === 'content' || secKey === 'encryption') continue;
      tabs.push({
        value: secKey,
        label: t(
          `subscriptionClients.tabs.${secKey}`,
          t(`subscriptionClients.sections.${secKey}.title`, secKey),
        ),
      });
    }
    return tabs;
  }, [sectionSchema, t]);

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
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button
              type="button"
              className={primaryButtonClass}
              disabled={saving || !hasChanges || hasInvalidJson}
              onClick={() => void handleSave()}
            >
              <UIIcon name={saving ? 'spinner' : 'check'} size={15} />
              <span className="whitespace-nowrap">
                {saving ? t('subscriptionClients.saving') : t('subscriptionClients.save')}
              </span>
            </button>
          </div>
        </div>

        <div className="mt-3 min-w-0">
          <ChoiceChips
            options={tabOptions}
            value={activeTab}
            onChange={(val) => setActiveTab(String(val))}
          />
        </div>

        {hasInvalidJson && (
          <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {t('subscriptionClients.sections.fixJsonErrors')}
          </div>
        )}

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

          {settings.clients.length > 0 && selectedClient && (
            <>
              <div className="mb-4 min-w-0">
                <ChoiceChips
                  options={clientTabOptions}
                  value={selectedClient.id}
                  onChange={(val) => setSelectedClientId(String(val))}
                />
              </div>

              {(() => {
                const clientSchema = schema[selectedClient.kind] || [];

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
                    key={selectedClient.id}
                    className="min-w-0 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-3 sm:p-4 shadow-sm"
                  >
                    <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            className={cn(iconButtonClass, 'h-8 w-8')}
                            disabled={selectedIndex === 0}
                            aria-label={t('subscriptionClients.clients.moveUp')}
                            title={t('subscriptionClients.clients.moveUp')}
                            onClick={() => handleMoveUp(selectedIndex)}
                          >
                            <span className="text-xs">▲</span>
                          </button>
                          <button
                            type="button"
                            className={cn(iconButtonClass, 'h-8 w-8')}
                            disabled={selectedIndex === settings.clients.length - 1}
                            aria-label={t('subscriptionClients.clients.moveDown')}
                            title={t('subscriptionClients.clients.moveDown')}
                            onClick={() => handleMoveDown(selectedIndex)}
                          >
                            <span className="text-xs">▼</span>
                          </button>
                        </div>

                        <input
                          className="form-check-input"
                          type="checkbox"
                          role="switch"
                          checked={selectedClient.enabled}
                          aria-checked={selectedClient.enabled}
                          aria-label={t('subscriptionClients.clients.enabled')}
                          title={t('subscriptionClients.clients.enabled')}
                          onChange={(e) => updateClient(selectedIndex, { enabled: e.target.checked })}
                        />

                        {selectedClient.builtin ? (
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-100">{selectedClient.name}</span>
                            <span className="rounded border border-cyan-400/20 bg-cyan-400/10 px-2 py-0.5 font-mono text-[10px] text-cyan-200 uppercase">
                              {t('subscriptionClients.clients.builtin')}
                            </span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              className={cn(inputClass, 'h-8 w-40 text-xs')}
                              value={selectedClient.name}
                              aria-label={t('subscriptionClients.clients.ruleName')}
                              placeholder={t('subscriptionClients.clients.ruleName')}
                              onChange={(e) => updateClient(selectedIndex, { name: e.target.value })}
                            />
                            <span className="rounded border border-slate-700 bg-slate-800/60 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                              {selectedClient.id}
                            </span>
                          </div>
                        )}
                      </div>

                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <div className="w-32">
                          <SelectMenu
                            ariaLabel={t('subscriptionClients.clients.format')}
                            value={selectedClient.format}
                            options={formats.map((f) => ({ value: f, label: f }))}
                            onChange={(val) => updateClient(selectedIndex, { format: String(val) })}
                          />
                        </div>

                        {!selectedClient.builtin && (
                          <button
                            type="button"
                            className={cn(iconButtonClass, 'text-rose-400 hover:text-rose-300')}
                            aria-label={t('subscriptionClients.clients.deleteClient')}
                            title={t('subscriptionClients.clients.deleteClient')}
                            onClick={() => handleDeleteClient(selectedIndex)}
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
                        value={selectedClient.user_agent_regex}
                        aria-label={t('subscriptionClients.clients.userAgentRegex')}
                        placeholder={t('subscriptionClients.clients.userAgentRegex')}
                        onChange={(e) => updateClient(selectedIndex, { user_agent_regex: e.target.value })}
                      />
                    </div>

                    <div className="mt-4 space-y-4 border-t border-cyan-500/20 pt-4">
                      {schemaGroups.map(([groupKey, fields]) => (
                        <div key={groupKey} className="min-w-0">
                          <h4 className={cn(titleClass, 'text-cyan-300')}>
                            {t(`subscriptionClients.groups.${groupKey}`)}
                          </h4>
                          <div className="mt-2 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                            {fields.map((field) => {
                              const fieldLabel = t(`subscriptionClients.fields.${selectedClient.kind}.${field.key}`);
                              const currentValue = selectedClient.settings?.[field.key];
                              const isHappRouting = selectedClient.kind === 'happ' && field.key === 'routing';
                              const isHappPlatform = selectedClient.kind === 'happ' && ['routing_ios', 'routing_android', 'routing_windows'].includes(field.key);
                              const checked = Boolean(currentValue ?? (isHappPlatform ? true : false));

                              return (
                                <div key={field.key} className={cn('min-w-0', isHappRouting ? 'sm:col-span-2' : '')}>
                                  <label className={cn(titleClass, 'text-[11px]')}>{fieldLabel}</label>
                                  <div className="mt-1 min-w-0">
                                    {(field.type === 'text' || field.type === 'url') && (
                                      <>
                                        {isHappRouting ? (
                                          <div>
                                            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                                              <input
                                                type="text"
                                                className={cn(inputClass, 'flex-1')}
                                                value={currentValue ?? ''}
                                                aria-label={fieldLabel}
                                                placeholder={fieldLabel}
                                                onChange={(e) => updateClientSetting(selectedIndex, field.key, e.target.value)}
                                              />
                                              <button
                                                type="button"
                                                className={cn(secondaryButtonClass, 'h-9 px-3 text-xs whitespace-nowrap')}
                                                onClick={() =>
                                                  setOpenHappRouting((prev) => ({
                                                    ...prev,
                                                    [selectedClient.id]: !prev[selectedClient.id],
                                                  }))
                                                }
                                              >
                                                {openHappRouting[selectedClient.id]
                                                  ? t('subscriptionClients.happRouting.closeEditor')
                                                  : t('subscriptionClients.happRouting.openEditor')}
                                              </button>
                                            </div>
                                            {openHappRouting[selectedClient.id] && (
                                              <HappRoutingEditor
                                                routingValue={currentValue || ''}
                                                onApply={(val) => {
                                                  updateClientSetting(selectedIndex, 'routing', val);
                                                  updateClientSetting(selectedIndex, 'routing_enable', true);
                                                }}
                                                onClose={() =>
                                                  setOpenHappRouting((prev) => ({
                                                    ...prev,
                                                    [selectedClient.id]: false,
                                                  }))
                                                }
                                              />
                                            )}
                                          </div>
                                        ) : (
                                          <input
                                            type={field.type === 'url' ? 'url' : 'text'}
                                            className={inputClass}
                                            value={currentValue ?? ''}
                                            aria-label={fieldLabel}
                                            placeholder={fieldLabel}
                                            onChange={(e) => updateClientSetting(selectedIndex, field.key, e.target.value)}
                                          />
                                        )}
                                      </>
                                    )}

                                    {field.type === 'lines' && (
                                      <textarea
                                        rows={3}
                                        className={codeInputClass}
                                        value={currentValue ?? ''}
                                        aria-label={fieldLabel}
                                        placeholder={fieldLabel}
                                        onChange={(e) => updateClientSetting(selectedIndex, field.key, e.target.value)}
                                      />
                                    )}

                                    {field.type === 'bool' && (
                                      <div className="flex items-center pt-1">
                                        <input
                                          className="form-check-input"
                                          type="checkbox"
                                          role="switch"
                                          checked={checked}
                                          aria-checked={checked}
                                          aria-label={fieldLabel}
                                          title={fieldLabel}
                                          onChange={(e) =>
                                            updateClientSetting(selectedIndex, field.key, e.target.checked)
                                          }
                                        />
                                        {isHappPlatform && (
                                          <span className="ml-2 min-w-0 text-xs text-gray-400">{t('subscriptionClients.happRouting.platformHint')}</span>
                                        )}
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
                                        onChange={(val) => updateClientSetting(selectedIndex, field.key, String(val))}
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

                      {selectedClient.kind === 'happ' && (
                        <div className="min-w-0 border-t border-cyan-500/10 pt-3">
                          <h4 className={cn(titleClass, 'text-cyan-300')}>
                            {t('subscriptionClients.sections.encryption.title')}
                          </h4>
                          <div className="mt-2 min-w-0">
                            <label className={cn(titleClass, 'text-xs text-slate-300')}>
                              {t('subscriptionClients.sections.encryption.happ_links')}
                            </label>
                            <div className="mt-1 min-w-0">
                              <div className="flex items-center pt-1">
                                <input
                                  className="form-check-input"
                                  type="checkbox"
                                  role="switch"
                                  checked={Boolean(settings.encryption?.happ_links)}
                                  aria-checked={Boolean(settings.encryption?.happ_links)}
                                  aria-label={t('subscriptionClients.sections.encryption.happ_links')}
                                  title={t('subscriptionClients.sections.encryption.happ_links')}
                                  onChange={(e) =>
                                    updateSectionField('encryption', 'happ_links', e.target.checked)
                                  }
                                />
                              </div>
                              <p className={cn(hintClass, 'mt-1 text-[11px] text-slate-400')}>
                                {t('subscriptionClients.sections.encryption.happ_linksHint')}
                              </p>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Custom headers editor */}
                      <div className="min-w-0 border-t border-cyan-500/10 pt-3">
                        <div className="flex min-w-0 items-center justify-between gap-2">
                          <h4 className={cn(titleClass, 'text-cyan-300')}>
                            {t('subscriptionClients.clients.customHeaders')}
                          </h4>
                          <button
                            type="button"
                            className={cn(secondaryButtonClass, 'h-8 px-3 text-xs')}
                            onClick={() => addClientHeader(selectedIndex)}
                          >
                            <UIIcon name="plus" size={13} />
                            <span className="whitespace-nowrap">{t('subscriptionClients.clients.addHeader')}</span>
                          </button>
                        </div>

                        {selectedClient.headers.length > 0 && (
                          <div className="mt-2 space-y-2">
                            {selectedClient.headers.map((header, hIdx) => (
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
                                  onChange={(e) => updateClientHeader(selectedIndex, hIdx, e.target.value, header.value)}
                                />
                                <input
                                  type="text"
                                  className={cn(codeInputClass, 'flex-1')}
                                  value={header.value}
                                  aria-label={t('subscriptionClients.clients.headerValue')}
                                  placeholder={t('subscriptionClients.clients.headerValue')}
                                  onChange={(e) => updateClientHeader(selectedIndex, hIdx, header.key, e.target.value)}
                                />
                                <button
                                  type="button"
                                  className={cn(iconButtonClass, 'h-9 w-9 text-rose-400 hover:text-rose-300')}
                                  aria-label={t('subscriptionClients.clients.deleteHeader')}
                                  title={t('subscriptionClients.clients.deleteHeader')}
                                  onClick={() => deleteClientHeader(selectedIndex, hIdx)}
                                >
                                  <UIIcon name="trash" size={14} />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })()}
            </>
          )}
        </section>
      )}

      {/* Sections dynamically rendered from section_schema */}
      {activeTab !== 'profile' && activeTab !== 'clients' && sectionSchema[activeTab] && (
        <section className={panelClass}>
          <SubscriptionSettingsSections
            sectionKey={activeTab}
            fields={sectionSchema[activeTab] || []}
            values={settings[activeTab] || {}}
            onChange={(fieldKey, val) => updateSectionField(activeTab, fieldKey, val)}
            onValidityChange={(isValid) => handleSectionValidityChange(activeTab, isValid)}
          >
            {activeTab === 'content' && (
              <div className="mt-6 rounded-lg border border-cyan-500/20 bg-[#0a0e1a] p-3 sm:p-4">
                <h4 className={cn(titleClass, 'text-cyan-300')}>
                  {t('subscriptionClients.content.tokensTitle')}
                </h4>
                <p className={hintClass}>
                  {t('subscriptionClients.content.tokensHint')}
                </p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {CONTENT_TOKENS.map((token) => (
                    <button
                      key={token}
                      type="button"
                      className={cn(
                        secondaryButtonClass,
                        'h-7 px-2 font-mono text-xs text-cyan-200 hover:border-cyan-400',
                      )}
                      title={t('subscriptionClients.content.insertToken')}
                      aria-label={`${t('subscriptionClients.content.insertToken')} ${token}`}
                      onClick={() => {
                        const current = (settings.content?.remark_template as string) || '';
                        updateSectionField('content', 'remark_template', current + token);
                      }}
                    >
                      <span>+</span>
                      <span>{token}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {activeTab === 'devices' && <SubscriptionDevicesPanel />}
          </SubscriptionSettingsSections>
        </section>
      )}
    </div>
  );
};
