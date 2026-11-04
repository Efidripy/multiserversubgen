import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SelectMenu } from './SelectMenu';
import {
  cn,
  codeInputClass,
  hintClass,
  inputClass,
  titleClass,
} from './SubscriptionManager';

export interface SectionFieldSchema {
  key: string;
  type: 'bool' | 'number' | 'text' | 'url' | 'enum' | 'json';
  group: string;
  options?: string[];
}

export type SectionSchemaMap = Record<string, SectionFieldSchema[]>;

export interface SubscriptionSettingsSectionsProps {
  sectionKey: string;
  fields: SectionFieldSchema[];
  values: Record<string, any>;
  onChange: (fieldKey: string, value: any) => void;
  onValidityChange?: (isValid: boolean) => void;
  children?: React.ReactNode;
}

export const SubscriptionSettingsSections: React.FC<SubscriptionSettingsSectionsProps> = ({
  sectionKey,
  fields,
  values,
  onChange,
  onValidityChange,
  children,
}) => {
  const { t } = useTranslation();
  const [jsonErrors, setJsonErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const initialErrors: Record<string, string> = {};
    for (const field of fields) {
      if (field.type === 'json') {
        const raw = values?.[field.key];
        if (typeof raw === 'string' && raw.trim() !== '') {
          try {
            JSON.parse(raw.trim());
          } catch (err: any) {
            initialErrors[field.key] = err?.message || t('subscriptionClients.sections.invalidJson');
          }
        }
      }
    }
    setJsonErrors(initialErrors);
    onValidityChange?.(Object.keys(initialErrors).length === 0);
  }, [sectionKey]);

  const handleJsonChange = (fieldKey: string, rawValue: string) => {
    onChange(fieldKey, rawValue);
    const trimmed = rawValue.trim();
    const nextErrors = { ...jsonErrors };
    if (!trimmed) {
      delete nextErrors[fieldKey];
    } else {
      try {
        JSON.parse(trimmed);
        delete nextErrors[fieldKey];
      } catch (err: any) {
        nextErrors[fieldKey] = err?.message || t('subscriptionClients.sections.invalidJson');
      }
    }
    setJsonErrors(nextErrors);
    onValidityChange?.(Object.keys(nextErrors).length === 0);
  };

  // Group schema fields
  const schemaGroups: Array<[string, SectionFieldSchema[]]> = [];
  const groupMap = new Map<string, SectionFieldSchema[]>();
  for (const f of fields) {
    const grp = f.group || 'default';
    const list = groupMap.get(grp) || [];
    list.push(f);
    groupMap.set(grp, list);
  }
  for (const entry of groupMap.entries()) {
    schemaGroups.push(entry);
  }

  const sectionTitleKey = `subscriptionClients.sections.${sectionKey}.title`;
  const sectionTitle = t(sectionTitleKey);

  return (
    <div className="space-y-4">
      <div className="border-b border-cyan-500/20 pb-2">
        <h3 className={cn(titleClass, 'text-cyan-300 text-base font-semibold')}>
          {sectionTitle}
        </h3>
      </div>

      {schemaGroups.map(([groupKey, groupFields]) => (
        <div key={groupKey} className="min-w-0">
          {schemaGroups.length > 1 && (
            <h4 className={cn(titleClass, 'mb-2 text-cyan-300')}>
              {t(`subscriptionClients.groups.${groupKey}`, groupKey)}
            </h4>
          )}
          <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
            {groupFields.map((field) => {
              const fieldLabelKey = `subscriptionClients.sections.${sectionKey}.${field.key}`;
              const fieldLabel = t(fieldLabelKey);
              const hintKey = `subscriptionClients.sections.${sectionKey}.${field.key}Hint`;
              const fieldHint = t(hintKey);
              const showHint = Boolean(fieldHint && fieldHint !== hintKey);
              const currentValue = values?.[field.key];
              const isFullWidth = field.type === 'json';

              return (
                <div
                  key={field.key}
                  className={cn('min-w-0', isFullWidth ? 'sm:col-span-2' : '')}
                >
                  <label className={cn(titleClass, 'text-xs text-slate-300')}>
                    {fieldLabel}
                  </label>
                  <div className="mt-1 min-w-0">
                    {field.type === 'bool' && (
                      <div className="flex items-center pt-1">
                        <button
                          type="button"
                          role="switch"
                          aria-checked={Boolean(currentValue)}
                          aria-label={fieldLabel}
                          title={fieldLabel}
                          onClick={() => onChange(field.key, !currentValue)}
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

                    {field.type === 'number' && (
                      <input
                        type="number"
                        className={inputClass}
                        value={currentValue ?? ''}
                        aria-label={fieldLabel}
                        placeholder={fieldLabel}
                        onChange={(e) => {
                          const val = e.target.value.trim();
                          onChange(field.key, val === '' ? 0 : Number(val));
                        }}
                      />
                    )}

                    {(field.type === 'text' || field.type === 'url') && (
                      <input
                        type={field.type === 'url' ? 'url' : 'text'}
                        className={inputClass}
                        value={currentValue ?? ''}
                        aria-label={fieldLabel}
                        placeholder={fieldLabel}
                        onChange={(e) => onChange(field.key, e.target.value)}
                      />
                    )}

                    {field.type === 'enum' && (
                      <SelectMenu
                        ariaLabel={fieldLabel}
                        value={currentValue ?? ''}
                        options={[
                          { value: '', label: t('subscriptionClients.notSet') },
                          ...(field.options && field.options.length > 0
                            ? field.options.map((opt) => ({
                                value: opt,
                                label: t(`subscriptionClients.options.${opt}`, opt),
                              }))
                            : []),
                        ]}
                        onChange={(val) => onChange(field.key, String(val))}
                      />
                    )}

                    {field.type === 'json' && (
                      <div>
                        <textarea
                          rows={5}
                          className={cn(
                            codeInputClass,
                            jsonErrors[field.key] ? 'border-rose-500/80 focus:border-rose-400' : '',
                          )}
                          value={
                            typeof currentValue === 'string'
                              ? currentValue
                              : currentValue
                                ? JSON.stringify(currentValue, null, 2)
                                : ''
                          }
                          aria-label={fieldLabel}
                          placeholder={fieldLabel}
                          onChange={(e) => handleJsonChange(field.key, e.target.value)}
                        />
                        {jsonErrors[field.key] && (
                          <p className="mt-1 text-xs text-rose-400" role="alert">
                            {jsonErrors[field.key]}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                  {showHint && <p className={hintClass}>{fieldHint}</p>}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {children}
    </div>
  );
};
