import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cn, codeInputClass, hintClass, inputClass, primaryButtonClass, secondaryButtonClass, titleClass } from './SubscriptionManager';

const DEFAULT_XRAY_TEMPLATE = {
  dns: { servers: ['1.1.1.1', '1.0.0.1'], queryStrategy: 'UseIP' },
  routing: { domainMatcher: 'hybrid', domainStrategy: 'IPIfNonMatch', rules: [{ type: 'field', protocol: ['bittorrent'], outboundTag: 'direct' }] },
  inbounds: [
    { tag: 'socks', port: 10808, listen: '127.0.0.1', protocol: 'socks', sniffing: { enabled: true, destOverride: ['http', 'tls'] }, settings: { auth: 'noauth', udp: true } },
    { tag: 'http', port: 10809, listen: '127.0.0.1', protocol: 'http', sniffing: { enabled: true, destOverride: ['http', 'tls'] }, settings: { allowTransparent: false } },
  ],
  outbounds: [{ tag: 'direct', protocol: 'freedom' }, { tag: 'block', protocol: 'blackhole' }],
};

export interface XrayTemplateEntry { name: string; template: string }

interface Props {
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
  onValidityChange?: (valid: boolean) => void;
}

export const XrayTemplatesEditor: React.FC<Props> = ({ values, onChange, onValidityChange }) => {
  const { t } = useTranslation();
  const templates: XrayTemplateEntry[] = Array.isArray(values.templates) ? values.templates : [];
  const active = typeof values.active === 'string' ? values.active : 'Default';
  const selected = active === 'Default' ? null : templates.find((item) => item.name === active);
  const text = selected?.template ?? JSON.stringify(DEFAULT_XRAY_TEMPLATE, null, 2);
  const [name, setName] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');

  const isValidJson = (value: string) => {
    try {
      const parsed = JSON.parse(value);
      return Boolean(parsed && typeof parsed === 'object' && !Array.isArray(parsed));
    } catch {
      return false;
    }
  };
  const valid = useMemo(() => templates.every((item) => isValidJson(item.template)), [templates]);
  const selectedValid = isValidJson(text);

  useEffect(() => {
    setError(selectedValid ? '' : t('subscriptionClients.sections.invalidJson'));
    onValidityChange?.(valid);
  }, [valid, selectedValid, onValidityChange, t]);

  const updateTemplate = (value: string) => {
    if (!selected) return;
    onChange('templates', templates.map((item) => item.name === selected.name ? { ...item, template: value } : item));
  };

  const addTemplate = () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > 64 || trimmed.toLowerCase() === 'default' || templates.some((item) => item.name.toLowerCase() === trimmed.toLowerCase()) || templates.length >= 20) {
      setError(t('subscriptionClients.sections.xray_json.invalidTemplateName'));
      return;
    }
    onChange('templates', [...templates, { name: trimmed, template: JSON.stringify(DEFAULT_XRAY_TEMPLATE, null, 2) }]);
    onChange('active', trimmed);
    setName('');
    setError('');
  };

  const deleteTemplate = () => {
    if (!selected) return;
    onChange('templates', templates.filter((item) => item.name !== selected.name));
    onChange('active', 'Default');
    setConfirmDelete(false);
  };

  const options = [{ value: 'Default', label: t('subscriptionClients.sections.xray_json.defaultTemplate') }, ...templates.map((item) => ({ value: item.name, label: item.name }))];

  return (
    <div className="space-y-4">
      <div className="border-b border-cyan-500/20 pb-2"><h3 className={cn(titleClass, 'text-cyan-300 text-base font-semibold')}>{t('subscriptionClients.sections.xray_json.title')}</h3></div>
      <label className="flex min-w-0 items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" className="form-check-input" role="switch" checked={Boolean(values.always_array)} aria-label={t('subscriptionClients.sections.xray_json.always_array')} onChange={(e) => onChange('always_array', e.target.checked)} />
        <span>{t('subscriptionClients.sections.xray_json.always_array')}</span>
      </label>
      <label className="flex min-w-0 items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" className="form-check-input" role="switch" checked={Boolean(values.enabled)} aria-label={t('subscriptionClients.sections.xray_json.enabled')} onChange={(e) => onChange('enabled', e.target.checked)} />
        <span>{t('subscriptionClients.sections.xray_json.enabled')}</span>
      </label>
      <p className={hintClass}>{t('subscriptionClients.sections.xray_json.enabledHint')}</p>
      <div className="min-w-0">
        <label className={cn(titleClass, 'text-xs text-slate-300')}>{t('subscriptionClients.sections.xray_json.template')}</label>
        <div className="mt-1 flex min-w-0 flex-col gap-2 sm:flex-row">
          <select className={cn(inputClass, 'min-w-0 w-full')} aria-label={t('subscriptionClients.sections.xray_json.template')} value={active} onChange={(event) => { onChange('active', event.target.value); setConfirmDelete(false); }}>
            {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          {selected && !confirmDelete && <button type="button" className={secondaryButtonClass} onClick={() => setConfirmDelete(true)}>{t('subscriptionClients.sections.xray_json.delete')}</button>}
          {selected && confirmDelete && <div className="flex gap-2"><button type="button" className={primaryButtonClass} onClick={deleteTemplate}>{t('subscriptionClients.sections.xray_json.confirmDelete')}</button><button type="button" className={secondaryButtonClass} onClick={() => setConfirmDelete(false)}>{t('subscriptionClients.sections.xray_json.cancel')}</button></div>}
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
        <input className={cn(inputClass, 'min-w-0 flex-1')} value={name} aria-label={t('subscriptionClients.sections.xray_json.newName')} placeholder={t('subscriptionClients.sections.xray_json.newName')} onChange={(e) => setName(e.target.value)} />
        <button type="button" className={secondaryButtonClass} onClick={addTemplate}>{t('subscriptionClients.sections.xray_json.add')}</button>
      </div>
      <textarea rows={24} readOnly={!selected} className={cn(codeInputClass, error ? 'border-rose-500/80 focus:border-rose-400' : '')} value={text} aria-label={t('subscriptionClients.sections.xray_json.jsonEditor')} onChange={(e) => updateTemplate(e.target.value)} />
      {error && <p className="text-xs text-rose-400" role="alert">{error}</p>}
      <p className={hintClass}>{t('subscriptionClients.sections.xray_json.templateHint')}</p>
    </div>
  );
};
