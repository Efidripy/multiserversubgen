import { lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
const Editor = lazy(() => import('./JsonCodeEditor'));
export function LazyJsonEditor(props: { value: string; onChange?: (value: string) => void; readOnly?: boolean; label: string }) {
  const { t } = useTranslation();
  return <Suspense fallback={<div className="min-h-0 flex-1">{t('nodeOps.editorLoading')}</div>}><Editor {...props} /></Suspense>;
}
