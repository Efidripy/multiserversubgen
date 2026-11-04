import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import { useToast } from './Toast';
import { UIIcon } from './UIIcon';
import {
  cn,
  panelClass,
  titleClass,
  hintClass,
  codeInputClass,
  primaryButtonClass,
  metaLabelClass,
} from './SubscriptionManager';

export interface SubscriptionClientTestResponse {
  matched: boolean;
  client_id: string | null;
  name: string | null;
  format: string;
  headers: Record<string, string>;
}

export const SubscriptionUaTest: React.FC = () => {
  const { t } = useTranslation();
  const { toast } = useToast();

  const [testUa, setTestUa] = useState('');
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<SubscriptionClientTestResponse | null>(null);

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

  return (
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
  );
};
