import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UIIcon } from './UIIcon';
import {
  cn,
  codeInputClass,
  hintClass,
  inputClass,
  primaryButtonClass,
  secondaryButtonClass,
  titleClass,
} from './SubscriptionManager';

export interface HappRoutingConfig {
  Name?: string;
  GlobalProxy?: string | boolean;
  DirectSites?: string[];
  DirectIp?: string[];
  ProxySites?: string[];
  ProxyIp?: string[];
  BlockSites?: string[];
  BlockIp?: string[];
  [key: string]: any;
}

export type HappPreset = 'global' | 'lan' | 'russia' | 'china' | 'off' | 'custom';

export const HAPP_ROUTING_PRESETS: Record<
  Exclude<HappPreset, 'custom'>,
  {
    name: string;
    globalProxy: string;
    directSites: string[];
    directIp: string[];
    proxySites: string[];
    proxyIp: string[];
    blockSites: string[];
    blockIp: string[];
  }
> = {
  global: {
    name: 'Global',
    globalProxy: 'true',
    directSites: [],
    directIp: [],
    proxySites: [],
    proxyIp: [],
    blockSites: [],
    blockIp: [],
  },
  lan: {
    name: 'Bypass LAN',
    globalProxy: 'true',
    directSites: ['geosite:private'],
    directIp: ['geoip:private'],
    proxySites: [],
    proxyIp: [],
    blockSites: [],
    blockIp: [],
  },
  russia: {
    name: 'Bypass Russia & LAN',
    globalProxy: 'true',
    directSites: ['geosite:private', 'geosite:category-ru'],
    directIp: ['geoip:private', 'geoip:ru'],
    proxySites: [],
    proxyIp: [],
    blockSites: [],
    blockIp: [],
  },
  china: {
    name: 'Bypass China & LAN',
    globalProxy: 'true',
    directSites: ['geosite:private', 'geosite:cn'],
    directIp: ['geoip:private', 'geoip:cn'],
    proxySites: [],
    proxyIp: [],
    blockSites: [],
    blockIp: [],
  },
  off: {
    name: 'Off',
    globalProxy: 'false',
    directSites: [],
    directIp: [],
    proxySites: [],
    proxyIp: [],
    blockSites: [],
    blockIp: [],
  },
};

export function parseGlobalProxy(val: unknown): boolean {
  if (typeof val === 'boolean') {
    return val;
  }
  if (typeof val === 'string') {
    const s = val.trim().toLowerCase();
    if (s === 'false' || s === '0' || s === 'off' || s === 'no') {
      return false;
    }
    if (s === 'true' || s === '1' || s === 'on' || s === 'yes') {
      return true;
    }
  }
  return true;
}

export function utf8ToBase64(str: string): string {
  const bytes = new TextEncoder().encode(str);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export function base64ToUtf8(b64: string): string {
  const binary = atob(b64.trim());
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new TextDecoder('utf-8').decode(bytes);
}

export function encodeHappRouting(config: HappRoutingConfig): string {
  let normalized = config;
  if (typeof config.GlobalProxy === 'boolean') {
    normalized = {
      ...config,
      GlobalProxy: config.GlobalProxy ? 'true' : 'false',
    };
  }
  const jsonStr = JSON.stringify(normalized);
  return `happ://routing/onadd/${utf8ToBase64(jsonStr)}`;
}

export function decodeHappRouting(routingStr: string): {
  data?: HappRoutingConfig;
  isOff?: boolean;
  error?: string;
} {
  const trimmed = (routingStr || '').trim();
  if (!trimmed) {
    return { data: {} };
  }
  if (trimmed === 'happ://routing/off') {
    return { isOff: true, data: {} };
  }
  if (!trimmed.startsWith('happ://routing/onadd/')) {
    return { error: 'invalid_prefix' };
  }
  const payload = trimmed.slice('happ://routing/onadd/'.length).trim();
  try {
    const jsonStr = base64ToUtf8(payload);
    const parsed = JSON.parse(jsonStr);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { error: 'invalid_json_object' };
    }
    return { data: parsed };
  } catch (err: any) {
    return { error: err?.message || 'decode_failed' };
  }
}

export interface HappRoutingEditorProps {
  routingValue: string;
  onApply: (newRoutingValue: string) => void;
  onClose?: () => void;
}

export const HappRoutingEditor: React.FC<HappRoutingEditorProps> = ({
  routingValue,
  onApply,
  onClose,
}) => {
  const { t } = useTranslation();

  const [preset, setPreset] = useState<HappPreset>('custom');
  const [name, setName] = useState('');
  const [globalProxy, setGlobalProxy] = useState(true);
  const [directSites, setDirectSites] = useState('');
  const [directIp, setDirectIp] = useState('');
  const [proxySites, setProxySites] = useState('');
  const [proxyIp, setProxyIp] = useState('');
  const [blockSites, setBlockSites] = useState('');
  const [blockIp, setBlockIp] = useState('');
  const [parseError, setParseError] = useState('');
  const [baseConfig, setBaseConfig] = useState<Record<string, any>>({});
  const prevRoutingRef = useRef<string | null>(null);

  useEffect(() => {
    if (prevRoutingRef.current === routingValue) {
      return;
    }
    prevRoutingRef.current = routingValue;

    if (!routingValue.trim()) {
      setParseError('');
      setBaseConfig({});
      setName('');
      setGlobalProxy(true);
      setDirectSites('');
      setDirectIp('');
      setProxySites('');
      setProxyIp('');
      setBlockSites('');
      setBlockIp('');
      setPreset('custom');
      return;
    }

    const res = decodeHappRouting(routingValue);
    if (res.error) {
      setParseError(t('subscriptionClients.happRouting.invalidString'));
      setBaseConfig({});
      return;
    }
    setParseError('');
    if (res.isOff) {
      setPreset('off');
      setBaseConfig({});
      setName(HAPP_ROUTING_PRESETS.off.name);
      setGlobalProxy(false);
      setDirectSites('');
      setDirectIp('');
      setProxySites('');
      setProxyIp('');
      setBlockSites('');
      setBlockIp('');
      return;
    }

    if (res.data) {
      const d = res.data;
      setBaseConfig({ ...d });
      setName(d.Name || '');
      setGlobalProxy(parseGlobalProxy(d.GlobalProxy));
      setDirectSites((d.DirectSites || []).join('\n'));
      setDirectIp((d.DirectIp || []).join('\n'));
      setProxySites((d.ProxySites || []).join('\n'));
      setProxyIp((d.ProxyIp || []).join('\n'));
      setBlockSites((d.BlockSites || []).join('\n'));
      setBlockIp((d.BlockIp || []).join('\n'));
      setPreset('custom');
    }
  }, [routingValue, t]);

  const applyPreset = (key: Exclude<HappPreset, 'custom'>) => {
    setPreset(key);
    setParseError('');
    setBaseConfig({});
    const p = HAPP_ROUTING_PRESETS[key];
    setName(p.name);
    setGlobalProxy(parseGlobalProxy(p.globalProxy));
    setDirectSites(p.directSites.join('\n'));
    setDirectIp(p.directIp.join('\n'));
    setProxySites(p.proxySites.join('\n'));
    setProxyIp(p.proxyIp.join('\n'));
    setBlockSites(p.blockSites.join('\n'));
    setBlockIp(p.blockIp.join('\n'));
  };

  const handleApply = () => {
    if (preset === 'off') {
      onApply('happ://routing/off');
      return;
    }
    const toLines = (text: string) =>
      text
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);

    const config: HappRoutingConfig = {
      ...baseConfig,
      Name: name.trim() || 'Custom',
      GlobalProxy: globalProxy ? 'true' : 'false',
      DirectSites: toLines(directSites),
      DirectIp: toLines(directIp),
      ProxySites: toLines(proxySites),
      ProxyIp: toLines(proxyIp),
      BlockSites: toLines(blockSites),
      BlockIp: toLines(blockIp),
    };

    const encoded = encodeHappRouting(config);
    onApply(encoded);
  };

  const presetList: Array<Exclude<HappPreset, 'custom'>> = ['global', 'lan', 'russia', 'china', 'off'];

  return (
    <div className="mt-3 rounded-lg border border-cyan-500/30 bg-[#070b14] p-3 sm:p-4 text-xs">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-cyan-500/20 pb-3">
        <div>
          <h5 className={cn(titleClass, 'text-cyan-300')}>
            {t('subscriptionClients.happRouting.openEditor')}
          </h5>
          <p className={hintClass}>
            {t('subscriptionClients.happRouting.onePerLine')}
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            className={cn(secondaryButtonClass, 'h-7 px-2 text-xs')}
            onClick={onClose}
          >
            {t('subscriptionClients.happRouting.closeEditor')}
          </button>
        )}
      </div>

      {parseError && (
        <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-200">
          <div className="flex items-center gap-2">
            <UIIcon name="warning" size={14} />
            <span>{parseError}</span>
          </div>
        </div>
      )}

      {/* Presets */}
      <div className="mt-3">
        <label className={cn(titleClass, 'text-[11px] text-slate-400')}>
          {t('subscriptionClients.happRouting.presetsTitle')}
        </label>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {presetList.map((pKey) => {
            const active = preset === pKey;
            return (
              <button
                key={pKey}
                type="button"
                className={cn(
                  'h-7 rounded border px-2.5 text-xs font-medium transition-colors',
                  active
                    ? 'border-cyan-400 bg-cyan-400/20 text-cyan-200'
                    : 'border-cyan-500/20 bg-slate-800/60 text-slate-400 hover:border-cyan-400/40 hover:text-slate-200',
                )}
                onClick={() => applyPreset(pKey)}
              >
                {t(`subscriptionClients.happRouting.presets.${pKey}`)}
              </button>
            );
          })}
        </div>
      </div>

      {preset !== 'off' && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.name')}</label>
              <input
                type="text"
                className={cn(inputClass, 'mt-1')}
                value={name}
                aria-label={t('subscriptionClients.happRouting.name')}
                placeholder={t('subscriptionClients.happRouting.name')}
                onChange={(e) => {
                  setName(e.target.value);
                  setPreset('custom');
                }}
              />
            </div>

            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.globalProxy')}</label>
              <div className="mt-2 flex items-center">
                <button
                  type="button"
                  role="switch"
                  aria-checked={globalProxy}
                  aria-label={t('subscriptionClients.happRouting.globalProxy')}
                  title={t('subscriptionClients.happRouting.globalProxy')}
                  onClick={() => {
                    setGlobalProxy(!globalProxy);
                    setPreset('custom');
                  }}
                  className={cn(
                    'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-cyan-400',
                    globalProxy ? 'bg-cyan-400' : 'bg-slate-700',
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-[#0a0e1a] shadow ring-0 transition duration-200 ease-in-out',
                      globalProxy ? 'translate-x-5' : 'translate-x-0',
                    )}
                  />
                </button>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.directSites')}</label>
              <textarea
                rows={4}
                className={cn(codeInputClass, 'mt-1')}
                value={directSites}
                aria-label={t('subscriptionClients.happRouting.directSites')}
                placeholder={t('subscriptionClients.happRouting.onePerLine')}
                onChange={(e) => {
                  setDirectSites(e.target.value);
                  setPreset('custom');
                }}
              />
            </div>

            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.directIp')}</label>
              <textarea
                rows={4}
                className={cn(codeInputClass, 'mt-1')}
                value={directIp}
                aria-label={t('subscriptionClients.happRouting.directIp')}
                placeholder={t('subscriptionClients.happRouting.onePerLine')}
                onChange={(e) => {
                  setDirectIp(e.target.value);
                  setPreset('custom');
                }}
              />
            </div>

            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.proxySites')}</label>
              <textarea
                rows={4}
                className={cn(codeInputClass, 'mt-1')}
                value={proxySites}
                aria-label={t('subscriptionClients.happRouting.proxySites')}
                placeholder={t('subscriptionClients.happRouting.onePerLine')}
                onChange={(e) => {
                  setProxySites(e.target.value);
                  setPreset('custom');
                }}
              />
            </div>

            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.proxyIp')}</label>
              <textarea
                rows={4}
                className={cn(codeInputClass, 'mt-1')}
                value={proxyIp}
                aria-label={t('subscriptionClients.happRouting.proxyIp')}
                placeholder={t('subscriptionClients.happRouting.onePerLine')}
                onChange={(e) => {
                  setProxyIp(e.target.value);
                  setPreset('custom');
                }}
              />
            </div>

            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.blockSites')}</label>
              <textarea
                rows={3}
                className={cn(codeInputClass, 'mt-1')}
                value={blockSites}
                aria-label={t('subscriptionClients.happRouting.blockSites')}
                placeholder={t('subscriptionClients.happRouting.onePerLine')}
                onChange={(e) => {
                  setBlockSites(e.target.value);
                  setPreset('custom');
                }}
              />
            </div>

            <div>
              <label className={titleClass}>{t('subscriptionClients.happRouting.blockIp')}</label>
              <textarea
                rows={3}
                className={cn(codeInputClass, 'mt-1')}
                value={blockIp}
                aria-label={t('subscriptionClients.happRouting.blockIp')}
                placeholder={t('subscriptionClients.happRouting.onePerLine')}
                onChange={(e) => {
                  setBlockIp(e.target.value);
                  setPreset('custom');
                }}
              />
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          className={cn(primaryButtonClass, 'h-8 px-4 text-xs')}
          onClick={handleApply}
        >
          <UIIcon name="check" size={14} />
          <span>{t('subscriptionClients.happRouting.apply')}</span>
        </button>
      </div>
    </div>
  );
};
